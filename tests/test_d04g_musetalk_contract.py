"""D04-G — hàng rào gate, hợp đồng adapter và provenance của MuseTalk.

Batch này dựng đường code **trước** khi có quyền chạy thật. Nên mọi test ở đây
trả lời đúng một câu: *cái gì xảy ra khi chưa được phép, hoặc khi thiếu thứ gì đó?*

Không test nào ở đây được phép chạm WSL, GPU, mạng, Docker hay media thật.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import time
import uuid
import wave
from pathlib import Path

import pytest

from ai_video_agent import GATES, gate_is_open
from ai_video_agent.clock import FixedClock, now_utc
from ai_video_agent.composer.runner import MockComposer
from ai_video_agent.config import Config
from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import ProjectState, ProviderMode, RenderStage
from ai_video_agent.domain.project import Approval, Project, ProviderSelection
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import GateNotReachedError, ProviderError
from ai_video_agent.jsonschemas import SchemaName, validate
from ai_video_agent.orchestrator.pipeline import Pipeline, RenderOptions
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers.base import AvatarRequest
from ai_video_agent.providers.duix import DuixAvatarProvider, MockDuixAvatarProvider
from ai_video_agent.providers.musetalk import MockMuseTalkProvider, MuseTalkAvatarProvider
from ai_video_agent.providers.musetalk.adapter import _to_wsl_path
from ai_video_agent.providers.musetalk.capability import (
    GATE,
    MUSETALK_CAPABILITY,
    REPO_COMMIT,
    REQUIRED_WEIGHTS,
    UNET_SHA256,
)
from ai_video_agent.providers.registry import KNOWN_AVATAR, build_provider_set
from ai_video_agent.providers.resource_budget import ResourceBudget, check_resources

ADAPTER_MODULE = "ai_video_agent.providers.musetalk.adapter"


def _wav(path: Path, seconds: float = 1.0, rate: int = 48_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _request(tmp_path: Path, **kw: object) -> AvatarRequest:
    audio = _wav(tmp_path / "audio.wav")
    source = tmp_path / "avatar.mp4"
    source.write_bytes(b"nguon avatar gia")
    base: dict[str, object] = {
        "shot_id": "shot-01", "audio_path": audio, "avatar_source": source,
        "width": 1080, "height": 1920, "fps": 30, "duration_sec": 1.0,
    }
    base.update(kw)
    return AvatarRequest(**base)  # type: ignore[arg-type]


def _fake_install(tmp_path: Path, *, missing: tuple[str, ...] = ()) -> Path:
    """Cây thư mục giả trông như bản cài MuseTalk. Không byte weights thật nào."""
    repo = tmp_path / "MuseTalk"
    for rel in REQUIRED_WEIGHTS:
        if rel in missing:
            continue
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"khong phai weights that")
    repo.mkdir(parents=True, exist_ok=True)
    return repo


def _bom(*_a: object, **_k: object) -> object:
    raise AssertionError("Đã gọi subprocess dù chưa được phép — sai thứ tự hàng rào.")


# --- 1. Nhận diện được nhưng KHÔNG chạy được ------------------------------


def test_musetalk_co_trong_registry() -> None:
    assert "musetalk" in KNOWN_AVATAR


def test_registry_dung_duoc_ca_hai_che_do(tmp_path: Path) -> None:
    config = Config(runtime_dir=tmp_path)
    mock = build_provider_set(
        ProviderSelection(avatar="musetalk"), mode=ProviderMode.MOCK, config=config
    )
    real = build_provider_set(
        ProviderSelection(avatar="musetalk"), mode=ProviderMode.REAL, config=config
    )

    assert isinstance(mock.avatar, MockMuseTalkProvider)
    assert isinstance(real.avatar, MuseTalkAvatarProvider)


def test_adapter_that_khong_chay_duoc_vi_gate_dong(tmp_path: Path) -> None:
    """Dựng được, hỏi được danh tính — nhưng generate() thì không."""
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))

    assert provider.info().name == "musetalk"
    with pytest.raises(GateNotReachedError):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


# --- 2. requires_gate đúng duy nhất "D04G" --------------------------------


def test_gate_khai_dung_o_moi_noi() -> None:
    assert GATE == "D04G"
    assert MUSETALK_CAPABILITY.requires_gate == "D04G"
    assert MuseTalkAvatarProvider().info().gate == "D04G"


def test_gate_d04g_dong_theo_cau_truc() -> None:
    """``D04G`` không nằm trong GATES, mà ``gate_is_open`` từ chối tên gate lạ.

    Nghĩa là gate đóng **theo cấu trúc**, không phụ thuộc vào việc ai đó nhớ
    đóng nó. Mở D04G = thêm tên vào ``GATES`` — thấy được trong diff.
    """
    assert "D04G" not in GATES
    assert gate_is_open("D04G") is False
    #: Kể cả khi giả định gate hiện tại đã lên tới D05.
    assert gate_is_open("D04G", current="D05") is False


def test_mock_khong_muon_gate_cua_ban_that() -> None:
    """Mock chạy từ D01; mượn gate D04G sẽ khoá luôn cả đường mock."""
    assert MockMuseTalkProvider().info().gate == "D01"
    assert MockMuseTalkProvider().capability().requires_gate == "D01"


# --- 3. Gate chặn TRƯỚC khi có subprocess ---------------------------------


def test_gate_chan_truoc_khi_goi_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gài bom vào subprocess: chạm tới nó nghĩa là hàng rào đứng sai chỗ."""
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))

    with pytest.raises(GateNotReachedError):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_bom_that_su_no_khi_moi_hang_rao_da_qua(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kiểm chính cái bẫy: mở gate ra thì luồng PHẢI chạm tới subprocess.

    Không có test này thì test trên có thể xanh vì adapter chết sớm ở chỗ khác,
    và ta tưởng đã chứng minh được thứ tự.
    """
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.shutil.which", lambda _n: "/usr/bin/wsl.exe")
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))

    with pytest.raises(AssertionError, match="sai thứ tự hàng rào"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_quote_va_capability_chay_duoc_khi_gate_dong(tmp_path: Path) -> None:
    """Xem giá và xem năng lực không được đòi quyền chạy."""
    provider = MuseTalkAvatarProvider()
    request = _request(tmp_path)

    assert provider.quote(request).estimated_usd == 0.0
    assert provider.capability().backend_id == "musetalk"
    assert provider.estimate_resources(request).vram_mib == 9_798


# --- 4. Mock đi trọn pipeline và ghi manifest đúng hợp đồng ---------------


@pytest.fixture
def musetalk_pipeline(
    repo: ProjectRepository, config: Config, clock: FixedClock
) -> Pipeline:
    providers = build_provider_set(
        ProviderSelection(avatar="musetalk"), mode=ProviderMode.MOCK, config=config
    )
    return Pipeline(
        repository=repo,
        providers=providers,
        config=config,
        composer=MockComposer(),
        now=clock.now_utc,
        make_run_id=clock.new_run_id,
    )


def _render(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    assets: AssetManifest,
) -> object:
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.transition_to(ProjectState.APPROVED)
    repo.save_project(project)
    return pipeline.render(project, storyboard, assets, RenderOptions(dry_run=False))


def test_pipeline_chay_tron_voi_musetalk_mock(
    musetalk_pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(musetalk_pipeline, repo, project, storyboard, granted_assets)
    assert manifest.status == "succeeded"  # type: ignore[attr-defined]


def test_manifest_khai_dung_musetalk_va_khong_ton_tien(
    musetalk_pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(musetalk_pipeline, repo, project, storyboard, granted_assets)
    avatar = [r for r in manifest.records if r.stage is RenderStage.AVATAR]  # type: ignore[attr-defined]

    assert avatar
    for record in avatar:
        assert record.provider == "musetalk"
        assert record.billable is False
        assert record.actual_cost_usd == 0.0
        prov = record.avatar_provenance
        assert prov is not None
        assert prov.backend_id == "musetalk"
        assert prov.audio_encoder == "whisper-tiny"
        assert prov.languages_verified == ["multi"]
        assert prov.native_fps == 25


def test_manifest_mang_van_tay_vao_va_ra(
    musetalk_pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(musetalk_pipeline, repo, project, storyboard, granted_assets)
    avatar = next(r for r in manifest.records if r.stage is RenderStage.AVATAR)  # type: ignore[attr-defined]
    prov = avatar.avatar_provenance

    assert prov is not None
    assert len(prov.audio_sha256) == 64
    assert len(prov.output_sha256) == 64
    assert prov.audio_sha256 != prov.output_sha256


def test_manifest_khop_schema_va_doc_lai_duoc(
    musetalk_pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(musetalk_pipeline, repo, project, storyboard, granted_assets)
    validate(SchemaName.RENDER_MANIFEST, manifest.model_dump(mode="json"))  # type: ignore[attr-defined]

    reloaded = repo.load_render_manifest(project.id, manifest.run_id)  # type: ignore[attr-defined]
    avatar = next(r for r in reloaded.records if r.stage is RenderStage.AVATAR)
    assert avatar.avatar_provenance is not None
    assert avatar.avatar_provenance.backend_id == "musetalk"


def test_khong_co_broll_ngoai_y_muon(
    musetalk_pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(musetalk_pipeline, repo, project, storyboard, granted_assets)
    assert not [r for r in manifest.records if r.stage is RenderStage.BROLL]  # type: ignore[attr-defined]


def test_khong_co_canh_bao_ngon_ngu_cho_musetalk(
    musetalk_pipeline: Pipeline,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Whisper đa ngôn ngữ ⇒ không cảnh báo. Đây là giả thuyết D04-G đi kiểm."""
    manifest = musetalk_pipeline.render(project, storyboard, empty_assets)
    assert not [w for w in manifest.warnings if "NGÔN NGỮ" in w]


def test_danh_tinh_upstream_duoc_ghim_trong_provenance(tmp_path: Path) -> None:
    """Mock phải mang mã ghim của upstream để truy vết bản nào đang được thử."""
    result = MockMuseTalkProvider().generate(_request(tmp_path), tmp_path / "out.mp4")
    prov = result.provenance

    assert prov is not None
    assert prov.params["mock_declares_target_commit"] == REPO_COMMIT[:8]
    assert prov.params["mock_declares_target_unet_sha256"] == UNET_SHA256[:8]
    assert prov.checkpoint_sha256 == "", "mock chưa từng đọc checkpoint — không được khai băm"


def test_mock_khong_mang_ten_khoa_giong_bang_chung_runtime(tmp_path: Path) -> None:
    """Công cụ grep commit hash không được hiểu manifest mock là đã chạy thật."""
    result = MockMuseTalkProvider().generate(_request(tmp_path), tmp_path / "out.mp4")
    assert result.provenance is not None

    for khoa in result.provenance.params:
        if "commit" in khoa or "sha256" in khoa:
            assert khoa.startswith("mock_declares_"), (
                f"khoá {khoa!r} trông như bằng chứng runtime; mock phải nói rõ nó chỉ khai target"
            )


def test_adapter_that_khai_bam_checkpoint_that() -> None:
    """Khác Duix: MuseTalk có file checkpoint RỜI nên băm được thật."""
    info = MuseTalkAvatarProvider().info()
    assert REPO_COMMIT[:8] in info.version
    assert UNET_SHA256[:8] in info.version


# --- 5. Thiếu thứ gì cũng phải hỏng RÕ ------------------------------------


def test_thieu_install_dir_hong_ro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    provider = MuseTalkAvatarProvider(install_dir=None)

    with pytest.raises(ProviderError, match="KHÔNG tự đoán đường dẫn"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_thieu_repo_hong_ro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    provider = MuseTalkAvatarProvider(install_dir=tmp_path / "khong-ton-tai")

    with pytest.raises(ProviderError, match="không tự clone"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_thieu_weights_noi_ro_thieu_file_nao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    thieu = ("models/musetalkV15/unet.pth", "models/whisper/pytorch_model.bin")
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path, missing=thieu))

    with pytest.raises(ProviderError) as exc:
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    text = str(exc.value)
    assert "KHÔNG tự tải" in text
    for rel in thieu:
        assert rel in text, "phải nói rõ thiếu file nào, không nói chung chung"


def test_thieu_wsl_hong_ro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.shutil.which", lambda _n: None)
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))

    with pytest.raises(ProviderError, match="không tự khởi động WSL"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def _mo_hang_rao_moi_truong(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cho mọi hàng rào môi trường đi qua — gate, PATH host, ffmpeg trong WSL.

    Tách riêng vì nó cũng cần cho các test dựng provider trực tiếp. Đặc biệt
    ``_wsl_file_is_executable`` **phải** bị thay: mặc định nó gọi ``wsl.exe``,
    và không test nào được chạm WSL thật.
    """
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.shutil.which", lambda _n: "/usr/bin/wsl.exe")
    monkeypatch.setattr(f"{ADAPTER_MODULE}._wsl_file_is_executable", lambda *_a: True)


def _armed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MuseTalkAvatarProvider:
    """Adapter đã qua hết hàng rào, chỉ còn lớp subprocess do test điều khiển."""
    _mo_hang_rao_moi_truong(monkeypatch)
    return MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))


class _Completed:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def test_job_that_bai_thi_hong_ro_va_khong_thu_lai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed(tmp_path, monkeypatch)
    goi = {"n": 0}

    def _fail(*_a: object, **_k: object) -> _Completed:
        goi["n"] += 1
        return _Completed(1, stderr="CUDA out of memory")

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _fail)

    with pytest.raises(ProviderError, match="THẤT BẠI"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")
    assert goi["n"] == 1, "hỏng thì DỪNG, không được tự chạy lại"


def test_loi_job_mang_theo_stderr_de_chan_doan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        f"{ADAPTER_MODULE}.subprocess.run",
        lambda *_a, **_k: _Completed(1, stderr="CUDA out of memory"),
    )

    with pytest.raises(ProviderError, match="CUDA out of memory"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_exit_0_nhung_khong_co_output_thi_van_hong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mặc định thành công khi thiếu dữ liệu là cách tệ nhất để hỏng."""
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", lambda *_a, **_k: _Completed(0))

    with pytest.raises(ProviderError, match=r"không có file \.mp4 nào"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_output_rong_thi_hong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _armed(tmp_path, monkeypatch)

    def _ghi_file_rong(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        (provider.last_job.result_dir / "ket-qua.mp4").write_bytes(b"")
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _ghi_file_rong)

    with pytest.raises(ProviderError, match="file rỗng"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_nhieu_output_thi_khong_doan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _armed(tmp_path, monkeypatch)

    def _ghi_hai_file(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        for name in ("a.mp4", "b.mp4"):
            (provider.last_job.result_dir / name).write_bytes(b"x")
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _ghi_hai_file)

    with pytest.raises(ProviderError, match="Không đoán"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_timeout_khong_thu_lai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _armed(tmp_path, monkeypatch)

    def _timeout(*_a: object, **_k: object) -> _Completed:
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _timeout)

    with pytest.raises(ProviderError, match="KHÔNG tự chạy lại"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


# --- Dòng lệnh: kiểm được mà không chạy gì --------------------------------


def test_dong_lenh_tro_dung_venv_va_repo(tmp_path: Path) -> None:
    repo = _fake_install(tmp_path)
    provider = MuseTalkAvatarProvider(install_dir=repo)
    cmd = provider.build_command(repo / "cfg.yaml", tmp_path / "res")
    text = " ".join(cmd)

    assert cmd[0] == "wsl.exe"
    assert "bakeoff-envs/musetalk/bin/python" in text, "phải dùng python CỦA VENV"
    assert "-m scripts.inference" in text
    assert "--version v15" in text
    assert "--use_float16" in text


def test_dong_lenh_khong_tu_cai_dat_gi(tmp_path: Path) -> None:
    """Không được có pip/apt/git clone/wget/curl trong lệnh."""
    repo = _fake_install(tmp_path)
    provider = MuseTalkAvatarProvider(install_dir=repo)
    text = " ".join(provider.build_command(repo / "c.yaml", tmp_path))

    for cam in ("pip ", "apt ", "apt-get", "git clone", "wget", "curl", "conda", "huggingface-cli"):
        assert cam not in text, f"lệnh không được chứa {cam!r}"


def _parse_config(yaml_text: str) -> dict[str, str]:
    """Đọc lại config. YAML 1.2 là tập cha của JSON nên ``json.loads`` hợp lệ.

    Parse lại thay vì so chuỗi: chỉ có parse mới chứng minh được giá trị đến nơi
    **nguyên vẹn**, chứ không phải chỉ "có xuất hiện đâu đó trong file".
    """
    return json.loads(yaml_text)["task_0"]


def test_dau_vao_di_qua_yaml_chu_khong_qua_co_dong_lenh(tmp_path: Path) -> None:
    """MuseTalk đọc video/audio TỪ FILE YAML. Truyền qua cờ sẽ bị bỏ qua im lặng."""
    request = _request(tmp_path)
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))
    task = _parse_config(provider.config_yaml(request))

    assert task["video_path"].endswith("/avatar.mp4")
    assert task["audio_path"].endswith("/audio.wav")


def test_duong_dan_windows_doi_sang_dang_wsl(tmp_path: Path) -> None:
    request = _request(tmp_path)
    task = _parse_config(
        MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path)).config_yaml(request)
    )

    for value in task.values():
        assert "\\" not in value, "đường dẫn Windows phải đổi sang dạng WSL"
    if str(tmp_path)[1:2] == ":":
        assert all(v.startswith("/mnt/") for v in task.values())


@pytest.mark.parametrize(
    "ten_thu_muc",
    ["co khoang trang", "co'nhay-don", "tiếng-việt-ừ", "co  hai   khoang", "dau#thang&and"],
)
def test_config_giu_nguyen_duong_dan_la(tmp_path: Path, ten_thu_muc: str) -> None:
    """Parse lại phải ra ĐÚNG giá trị ban đầu, không mất và không méo ký tự."""
    la = tmp_path / ten_thu_muc
    la.mkdir()
    request = _request(la)
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))

    task = _parse_config(provider.config_yaml(request))

    assert request.avatar_source is not None
    assert task["video_path"] == _to_wsl_path(request.avatar_source)
    assert task["audio_path"] == _to_wsl_path(request.audio_path)
    assert ten_thu_muc in task["video_path"]


# --- HIGH-2: quote an toàn cho bash ---------------------------------------


def _script_of(cmd: tuple[str, ...]) -> str:
    """Phần script thật sự đưa cho ``bash -lc`` — token cuối của argv."""
    assert cmd[:6] == ("wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc")
    return cmd[6]


def _argv_python(script: str) -> list[str]:
    """Tách đoạn lệnh python ra khỏi script, mô phỏng đúng cách bash tách token."""
    doan = script.split(" && ")[-1]
    return shlex.split(doan)


@pytest.mark.parametrize(
    "ten_thu_muc",
    ["co khoang trang", "co'nhay-don", "tiếng-việt-ừ", "co  hai   khoang", "dau$dola"],
)
def test_bash_nhan_dung_tung_gia_tri_du_duong_dan_la(tmp_path: Path, ten_thu_muc: str) -> None:
    """Chứng minh bằng cách TÁCH LẠI script như bash, không phải tìm chuỗi con.

    Đây là điểm mấu chốt: một đường dẫn có khoảng trắng vẫn "xuất hiện trong
    chuỗi" ngay cả khi bash sẽ tách nó thành hai tham số. Chỉ shlex.split mới
    phân biệt được hai tình huống đó.
    """
    la = tmp_path / ten_thu_muc
    la.mkdir()
    repo = _fake_install(la)
    provider = MuseTalkAvatarProvider(install_dir=repo, hf_home=la / "hf cache")

    config_path = la / "job dir" / "inference.yaml"
    result_dir = la / "job dir"
    argv = _argv_python(_script_of(provider.build_command(config_path, result_dir)))

    assert argv[argv.index("--inference_config") + 1] == _to_wsl_path(config_path)
    assert argv[argv.index("--result_dir") + 1] == _to_wsl_path(result_dir)
    assert argv[1:3] == ["-m", "scripts.inference"]


def test_cd_va_hf_home_cung_duoc_quote(tmp_path: Path) -> None:
    la = tmp_path / "thu muc co khoang trang"
    la.mkdir()
    repo = _fake_install(la)
    provider = MuseTalkAvatarProvider(install_dir=repo, hf_home=la / "hf cache")

    script = _script_of(provider.build_command(la / "c.yaml", la))
    cd_doan, hf_doan = script.split(" && ")[0], script.split(" && ")[1]

    assert shlex.split(cd_doan) == ["cd", _to_wsl_path(repo)]
    assert shlex.split(hf_doan) == ["export", f"HF_HOME={_to_wsl_path(la / 'hf cache')}"]


def test_khong_dung_shell_true(tmp_path: Path) -> None:
    """argv ngoài cùng vẫn là list; không bao giờ giao cả chuỗi cho shell của host."""
    repo = _fake_install(tmp_path)
    cmd = MuseTalkAvatarProvider(install_dir=repo).build_command(repo / "c.yaml", tmp_path)

    assert isinstance(cmd, tuple)
    assert cmd[0] == "wsl.exe"
    assert "shell=True" not in " ".join(cmd)


# --- HIGH-1: cô lập job và chặn output cũ ---------------------------------


def _armed_with_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, duration: str = "14.080000"
) -> MuseTalkAvatarProvider:
    """Qua hết hàng rào; subprocess và ffprobe do test điều khiển."""
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", lambda *_a, **_k: duration)
    return provider


def _stub_run_ghi_output(
    provider: MuseTalkAvatarProvider, monkeypatch: pytest.MonkeyPatch, name: str = "ket-qua.mp4"
) -> None:
    def _ghi(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        (provider.last_job.result_dir / name).write_bytes(b"video gia")
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _ghi)


def test_output_moi_hop_le_thi_duoc_nhan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert result.path.is_file()
    assert result.path.name == "ket-qua.mp4"
    assert result.is_placeholder is False


def test_output_cu_bi_tu_choi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """File có sẵn từ trước job không được nhận là kết quả của lượt này."""
    provider = _armed_with_probe(tmp_path, monkeypatch)

    def _dat_file_cu(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        cu = provider.last_job.result_dir / "cu.mp4"
        cu.write_bytes(b"output cua lan truoc")
        # Lùi mtime về một giờ trước — xa hơn dung sai filesystem rất nhiều.
        cu_gio = provider.last_job.started_wall - 3600
        os.utime(cu, (cu_gio, cu_gio))
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _dat_file_cu)

    with pytest.raises(ProviderError, match="output CŨ"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_output_cu_khong_bi_xoa_de_bien_thanh_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Xoá file cũ rồi chạy tiếp sẽ giấu mất tình huống đáng điều tra."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    duong_cu: dict[str, Path] = {}

    def _dat_file_cu(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        cu = provider.last_job.result_dir / "cu.mp4"
        cu.write_bytes(b"x")
        os.utime(cu, (provider.last_job.started_wall - 3600,) * 2)
        duong_cu["p"] = cu
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _dat_file_cu)

    with pytest.raises(ProviderError):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")
    assert duong_cu["p"].is_file(), "adapter không được xoá bằng chứng"


def test_thu_muc_job_da_ton_tai_thi_hong_truoc_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    #: Ép mã job cố định để dựng đúng tình huống trùng thư mục.
    monkeypatch.setattr(f"{ADAPTER_MODULE}.uuid.uuid4", lambda: uuid.UUID(int=0))
    monkeypatch.setattr(f"{ADAPTER_MODULE}.time.time", lambda: 1_700_000_000.0)

    out = tmp_path / "cache" / "out.mp4"
    out.parent.mkdir(parents=True)
    code = f"aiva-shot-01-1700000000-{uuid.UUID(int=0).hex[:12]}"
    (out.parent / f"musetalk-{code}").mkdir()

    with pytest.raises(ProviderError, match="đã tồn tại"):
        provider.generate(_request(tmp_path), out)


def test_hai_job_cung_shot_khong_dung_chung_thu_muc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cùng shot, cùng giây vẫn phải ra hai thư mục khác nhau."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.time.time", lambda: 1_700_000_000.0)

    request = _request(tmp_path)
    provider.generate(request, tmp_path / "a" / "out.mp4")
    dir_1 = provider.last_job.result_dir if provider.last_job else None
    provider.generate(request, tmp_path / "a" / "out.mp4")
    dir_2 = provider.last_job.result_dir if provider.last_job else None

    assert dir_1 is not None and dir_2 is not None
    assert dir_1 != dir_2, "hai lượt cùng shot cùng giây vẫn phải tách thư mục"


# --- MEDIUM-1/2: config nằm trong job dir và hash là SHA-256 thật ----------


def test_config_khong_ghi_vao_repo_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Làm bẩn repo đã ghim khiến việc xác minh đúng commit về sau khó hơn."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)
    repo = tmp_path / "MuseTalk"

    provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert provider.last_job is not None
    config_path = provider.last_job.config_path
    assert repo not in config_path.parents, "config không được nằm trong repo upstream"
    assert config_path.parent == provider.last_job.result_dir
    assert not (repo / "configs").exists(), "không tạo thư mục nào trong repo upstream"


def test_config_sha256_la_bam_that_cua_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert provider.last_job is not None
    mong_doi = hashlib.sha256(provider.last_job.config_path.read_bytes()).hexdigest()
    assert provider.last_job.config_sha256 == mong_doi
    assert result.provenance is not None
    assert result.provenance.params["config_yaml_sha256"] == mong_doi
    assert len(mong_doi) == 64


def test_khong_con_ten_khoa_sha256_gia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tên có 'sha256' mà giá trị không phải hash là nói dối trong bản ghi kiểm chứng."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert result.provenance is not None
    for khoa, gia_tri in result.provenance.params.items():
        if "sha256" in khoa:
            assert len(gia_tri) == 64 and all(c in "0123456789abcdef" for c in gia_tri), (
                f"{khoa} tự nhận là sha256 nhưng giá trị {gia_tri!r} không phải hash"
            )


# --- HIGH-3: thời lượng đến từ MP4, không từ WAV --------------------------


def test_output_duration_lay_tu_probe_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WAV dài 1,0 s nhưng video báo 14,08 s — kết quả phải theo VIDEO."""
    provider = _armed_with_probe(tmp_path, monkeypatch, duration="14.080000")
    _stub_run_ghi_output(provider, monkeypatch)
    request = _request(tmp_path)

    result = provider.generate(request, tmp_path / "out.mp4")

    assert result.duration_sec == 14.08
    assert result.duration_sec != pytest.approx(1.0), "không được lấy thời lượng WAV"


def test_probe_duoc_goi_dung_file_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    da_do: list[Path] = []

    def _spy(_bin: str, clip: Path, _entries: str, **_k: object) -> str:
        da_do.append(clip)
        return "9.5"

    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", _spy)
    _stub_run_ghi_output(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert da_do == [result.path], "phải đo đúng file output, không đo file khác"


def test_thoi_luong_audio_ghi_rieng_va_dung_ten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed_with_probe(tmp_path, monkeypatch, duration="14.080000")
    _stub_run_ghi_output(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert result.provenance is not None
    audio_sec = float(result.provenance.params["input_audio_duration_sec"])
    assert audio_sec == pytest.approx(1.0, abs=0.05)
    assert result.duration_sec == 14.08


@pytest.mark.parametrize("tra_ve", ["", "khong-phai-so", "N/A", "nan", "inf", "0", "-3.0"])
def test_probe_hong_hoac_vo_ly_thi_fail_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tra_ve: str
) -> None:
    """Không có nhánh lùi về WAV — chưa đo được thì phải nói là chưa đo được."""
    provider = _armed_with_probe(tmp_path, monkeypatch, duration=tra_ve)
    _stub_run_ghi_output(provider, monkeypatch)

    with pytest.raises(ProviderError, match=r"[Tt]hời lượng"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_provenance_nhan_dung_output_video_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo: ProjectRepository,
    config: Config,
    clock: FixedClock,
) -> None:
    """Chốt tới tận manifest: ``output_duration_sec`` phải là số đo của video."""
    from ai_video_agent.orchestrator.pipeline import Pipeline as _P

    provider = _armed_with_probe(tmp_path, monkeypatch, duration="14.080000")
    _stub_run_ghi_output(provider, monkeypatch)
    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    needed = provider.estimate_resources(_request(tmp_path))
    preflight = check_resources("musetalk", needed, ResourceBudget())
    record = _P._avatar_provenance_record(
        provider.info(), provider.capability(), result, result.path, preflight
    )
    del repo, config, clock
    assert record.output_duration_sec == 14.08


# --- Gate chặn TRƯỚC mọi side effect --------------------------------------


def test_gate_chan_truoc_mkdir_config_probe_va_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Không thư mục job, không file config, không probe, không subprocess."""
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    monkeypatch.setattr(
        f"{ADAPTER_MODULE}._ffprobe_entries",
        lambda *_a, **_k: pytest.fail("đã probe dù gate đóng"),
    )
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))
    cache = tmp_path / "cache"
    cache.mkdir()

    with pytest.raises(GateNotReachedError):
        provider.generate(_request(tmp_path), cache / "out.mp4")

    assert list(cache.iterdir()) == [], "gate đóng mà vẫn tạo thư mục/file là side effect"
    assert provider.last_job is None, "không được dựng job khi gate còn đóng"


# --- A2/HIGH-4: shot_id là dữ liệu vào, phải kiểm trước khi thành đường dẫn ---


@pytest.mark.parametrize(
    "xau",
    [
        "a/../../evil",          # thoát thư mục bằng dấu gạch chéo
        "..",                    # tham chiếu thư mục cha
        "a\\..\\..\\evil",       # dấu gạch chéo ngược của Windows
        "con:dau",               # ký tự Windows cấm
        "sao*sao",
        "hoi?cham",
        "A-VIET-HOA",            # pattern chỉ nhận chữ thường
        "",                      # rỗng
        "-bat-dau-bang-gach",    # ký tự đầu phải là chữ/số
        "x" * 64,                # vượt 63 ký tự
    ],
)
def test_shot_id_khong_hop_le_bi_chan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xau: str
) -> None:
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)

    with pytest.raises(ProviderError, match="không hợp lệ"):
        provider.generate(_request(tmp_path, shot_id=xau), tmp_path / "out.mp4")


def test_shot_id_xau_khong_de_lai_dau_vet_tren_dia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chặn phải xảy ra TRƯỚC mkdir — nếu không thì cây thư mục đã kịp thoát ra ngoài."""
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    cache = tmp_path / "cache"
    cache.mkdir()

    with pytest.raises(ProviderError):
        provider.generate(_request(tmp_path, shot_id="a/../../evil"), cache / "out.mp4")

    assert list(cache.iterdir()) == []
    assert not (tmp_path / "evil").exists()
    assert provider.last_job is None


def test_shot_id_hop_le_van_di_qua(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hàng rào không được chặn nhầm id hợp lệ theo đúng pattern của Shot.id."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    result = provider.generate(_request(tmp_path, shot_id="shot-01.a_b"), tmp_path / "out.mp4")
    assert result.path.is_file()


# --- A2/MEDIUM-7: mkdir hỏng phải thành ProviderError ---------------------


def test_mkdir_loi_he_thong_thanh_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError thô lọt ra ngoài buộc người đọc log tự đoán nó đến từ đâu."""
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    #: Dựng request TRƯỚC khi gài bẫy — `_request()` cũng tạo thư mục, và bẫy
    #: đặt sớm sẽ làm test tự vấp chính nó thay vì kiểm thứ cần kiểm.
    request = _request(tmp_path)

    def _mkdir_hong(*_a: object, **_k: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "mkdir", _mkdir_hong)

    with pytest.raises(ProviderError, match="Không tạo được thư mục job"):
        provider.generate(request, tmp_path / "out.mp4")


# --- A2/HIGH-5: ffprobe thiếu hoặc hỏng phải fail-closed ------------------


def test_thieu_ffprobe_hong_truoc_khi_chay_gpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thiếu ffprobe mà chỉ lộ ra lúc đo là mất trắng ~4 phút GPU không được thử lại."""
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    monkeypatch.setattr(
        f"{ADAPTER_MODULE}.shutil.which",
        lambda name: None if "ffprobe" in name else "/usr/bin/wsl.exe",
    )
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))

    with pytest.raises(ProviderError, match="ffprobe"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_ffprobe_nem_oserror_thanh_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``qc.broll._run`` không bắt OSError — adapter phải tự bọc lại."""
    provider = _armed(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    def _khong_co_binary(*_a: object, **_k: object) -> str:
        raise FileNotFoundError(2, "No such file or directory: 'ffprobe'")

    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", _khong_co_binary)

    with pytest.raises(ProviderError, match="Không chạy được"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


# --- BLOCKER-1: đường ffmpeg trong WSL cấu hình được và kiểm trước GPU ----


def test_mac_dinh_ffmpeg_dir_van_la_usr_bin(tmp_path: Path) -> None:
    """Đổi mặc định là đổi hành vi của mọi máy khác — giữ nguyên ``/usr/bin``."""
    assert Config(runtime_dir=tmp_path).musetalk_ffmpeg_dir == "/usr/bin"
    assert Config.from_env().musetalk_ffmpeg_dir == "/usr/bin"


def test_env_ghi_de_duoc_ffmpeg_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Máy cài ffmpeg bằng pip --user để nó ở ~/.local/bin, không phải /usr/bin."""
    monkeypatch.setenv("AIVA_MUSETALK_FFMPEG_DIR", "/opt/ffmpeg/bin")
    assert Config.from_env().musetalk_ffmpeg_dir == "/opt/ffmpeg/bin"


def test_registry_truyen_ffmpeg_dir_xuong_adapter(tmp_path: Path) -> None:
    """Cấu hình phải tới được adapter, không dừng ở Config."""
    config = Config(runtime_dir=tmp_path, musetalk_ffmpeg_dir="/opt/ffmpeg/bin")
    provider = build_provider_set(
        ProviderSelection(avatar="musetalk"), mode=ProviderMode.REAL, config=config
    ).avatar
    repo = _fake_install(tmp_path)
    cmd = provider.build_command(repo / "c.yaml", tmp_path)  # type: ignore[attr-defined]
    argv = _argv_python(_script_of(cmd))

    assert argv[argv.index("--ffmpeg_path") + 1] == "/opt/ffmpeg/bin"


def test_thieu_ffmpeg_trong_wsl_hong_truoc_khi_chay_gpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg chỉ dùng ở bước mux CUỐI — sai đường dẫn sẽ hỏng sau khi tốn GPU."""
    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.shutil.which", lambda _n: "/usr/bin/wsl.exe")
    monkeypatch.setattr(f"{ADAPTER_MODULE}._wsl_file_is_executable", lambda *_a: False)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    provider = MuseTalkAvatarProvider(install_dir=_fake_install(tmp_path))

    with pytest.raises(ProviderError, match="AIVA_MUSETALK_FFMPEG_DIR"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_kiem_dung_duong_dan_ffmpeg_da_cau_hinh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phải hỏi đúng ``<ffmpeg_dir>/ffmpeg``, không hỏi một đường bịa."""
    da_hoi: list[str] = []

    def _spy(_bin: str, _distro: str, path: str) -> bool:
        da_hoi.append(path)
        return True

    monkeypatch.setattr(f"{ADAPTER_MODULE}.gate_is_open", lambda _g: True)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.shutil.which", lambda _n: "/usr/bin/wsl.exe")
    monkeypatch.setattr(f"{ADAPTER_MODULE}._wsl_file_is_executable", _spy)
    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", lambda *_a, **_k: "14.0")
    provider = MuseTalkAvatarProvider(
        install_dir=_fake_install(tmp_path), ffmpeg_dir_wsl="/opt/ffmpeg/bin/"
    )
    _stub_run_ghi_output(provider, monkeypatch)

    provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    #: Dấu gạch chéo thừa ở cuối phải được cắt, không thành "//ffmpeg".
    assert da_hoi == ["/opt/ffmpeg/bin/ffmpeg"]


def test_kiem_ffmpeg_khong_chay_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hàng rào chỉ được ``test -x``, tuyệt đối không thực thi ffmpeg."""
    ghi_lai: list[list[str]] = []

    def _bat_argv(argv: list[str], **_k: object) -> _Completed:
        ghi_lai.append(argv)
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bat_argv)
    from ai_video_agent.providers.musetalk.adapter import _wsl_file_is_executable

    assert _wsl_file_is_executable("wsl.exe", "Ubuntu", "/opt/bin/ffmpeg") is True
    assert ghi_lai == [["wsl.exe", "-d", "Ubuntu", "--", "test", "-x", "/opt/bin/ffmpeg"]]


def test_kiem_ffmpeg_that_bai_thi_tra_false_chu_khong_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Không gọi được WSL cũng là lý do chính đáng để dừng — trả False, không ném."""
    from ai_video_agent.providers.musetalk.adapter import _wsl_file_is_executable

    def _khong_goi_duoc(*_a: object, **_k: object) -> _Completed:
        raise OSError(2, "wsl.exe khong ton tai")

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _khong_goi_duoc)
    assert _wsl_file_is_executable("wsl.exe", "Ubuntu", "/opt/bin/ffmpeg") is False


# --- A2/MEDIUM-5: ưu tiên stream v:0, không lấy container làm chính -------


def test_uu_tien_thoi_luong_stream_v0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Container duration có thể chính là thời lượng AUDIO — che mất độ lệch A/V."""
    provider = _armed(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)
    da_hoi: list[tuple[str, str | None]] = []

    def _probe(_bin: str, _clip: Path, entries: str, stream: str | None = "v:0") -> str:
        da_hoi.append((entries, stream))
        return "13.960000" if entries == "stream=duration" else "14.080000"

    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", _probe)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert da_hoi[0] == ("stream=duration", "v:0"), "phải hỏi stream video TRƯỚC"
    assert result.duration_sec == 13.96, "phải lấy số của stream, không lấy container"
    assert result.provenance is not None
    assert result.provenance.params["output_duration_source"] == "video-stream:v:0"


def test_lui_ve_container_khi_stream_khong_co_va_ghi_ro_nguon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Một số MP4 không ghi duration ở cấp stream — được lùi, nhưng phải nói ra."""
    provider = _armed(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    def _probe(_bin: str, _clip: Path, entries: str, stream: str | None = "v:0") -> str:
        return "N/A" if entries == "stream=duration" else "14.080000"

    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", _probe)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert result.duration_sec == 14.08
    assert result.provenance is not None
    assert result.provenance.params["output_duration_source"] == "container-format"


def test_ca_hai_nguon_deu_hong_thi_khong_lui_ve_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", lambda *_a, **_k: "N/A")

    with pytest.raises(ProviderError, match="Không đọc được thời lượng"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


# --- A2/MEDIUM-6: symlink và output ngoài job dir -------------------------


def _thu_tao_symlink(link: Path, target: Path) -> None:
    """Windows đòi quyền riêng để tạo symlink — thiếu quyền thì bỏ qua test."""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - phụ thuộc máy
        pytest.skip(f"máy không cho tạo symlink: {exc}")


def test_symlink_trong_job_dir_bi_tu_choi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``stat()`` đi theo symlink, nên nó mượn được size/mtime của đích bên ngoài."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    ngoai = tmp_path / "ngoai-vung.mp4"
    ngoai.write_bytes(b"video that nhung o ngoai job")

    def _tao_symlink(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        _thu_tao_symlink(provider.last_job.result_dir / "ket-qua.mp4", ngoai)
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _tao_symlink)

    with pytest.raises(ProviderError, match="symlink"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_file_trong_thu_muc_symlink_cung_bi_tu_choi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chặn cả đường vòng: file thật, nhưng nằm trong một thư mục symlink."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    kho_ngoai = tmp_path / "kho-ngoai"
    kho_ngoai.mkdir()
    (kho_ngoai / "ket-qua.mp4").write_bytes(b"video that o ngoai")

    def _tao_symlink_thu_muc(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        _thu_tao_symlink(provider.last_job.result_dir / "sub", kho_ngoai)
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _tao_symlink_thu_muc)

    with pytest.raises(ProviderError, match=r"symlink|ngoài thư mục job"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_nhanh_chan_symlink_luon_duoc_kiem_du_may_khong_cho_tao_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hai test symlink ở trên bị bỏ qua trên máy không có quyền tạo symlink.

    Test này ép ``is_symlink()`` trả True để **luôn** kiểm được nhánh chặn, nên
    hàng rào không bao giờ rơi vào tình trạng chưa từng được chạy.
    """
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)
    monkeypatch.setattr(Path, "is_symlink", lambda _self: True)

    with pytest.raises(ProviderError, match="symlink"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_nhanh_chan_ngoai_job_luon_duoc_kiem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ép ``resolve()`` trỏ ra ngoài để kiểm nhánh containment mà không cần symlink."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)
    ngoai = tmp_path / "hoan-toan-ngoai" / "ket-qua.mp4"
    that = Path.resolve

    def _resolve_lech(self: Path, strict: bool = False) -> Path:
        del strict
        return ngoai if self.suffix == ".mp4" else that(self)

    monkeypatch.setattr(Path, "resolve", _resolve_lech)

    with pytest.raises(ProviderError, match="ngoài thư mục job"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_file_that_trong_job_dir_van_duoc_nhan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hàng rào containment không được chặn nhầm output hợp lệ."""
    provider = _armed_with_probe(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert provider.last_job is not None
    assert result.path.resolve().is_relative_to(provider.last_job.result_dir.resolve())


# --- B1/LOW-1: đo peak VRAM trong lúc render ------------------------------


def _armed_with_vram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    free_mau: list[int | None] | None = None,
    total: int | None = 12_282,
    sampler_no: bool = False,
) -> MuseTalkAvatarProvider:
    """Adapter đã qua hàng rào, với bộ lấy mẫu VRAM **giả** hoàn toàn.

    Không test nào ở đây được chạm ``nvidia-smi``: cả sampler lẫn total probe
    đều tiêm từ ngoài, và khoảng lấy mẫu hạ xuống mức gần như tức thời để test
    không phải chờ.
    """
    _mo_hang_rao_moi_truong(monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", lambda *_a, **_k: "14.080000")

    con_lai = list(free_mau or [])

    def _sampler() -> int | None:
        if sampler_no:
            raise RuntimeError("nvidia-smi dang ban")
        return con_lai.pop(0) if con_lai else (free_mau[-1] if free_mau else None)

    return MuseTalkAvatarProvider(
        install_dir=_fake_install(tmp_path),
        vram_sampler=_sampler,
        vram_total_probe=lambda: total,
        vram_sample_interval_sec=0.001,
    )


def _cho_lay_mau(provider: MuseTalkAvatarProvider, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub subprocess: ghi output và nán lại đủ để luồng lấy mẫu chạy vài vòng."""

    def _ghi(*_a: object, **_k: object) -> _Completed:
        assert provider.last_job is not None
        time.sleep(0.05)
        (provider.last_job.result_dir / "ket-qua.mp4").write_bytes(b"video gia")
        return _Completed(0)

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _ghi)


def test_peak_vram_tinh_tu_total_tru_free_thap_nhat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đỉnh ĐÃ DÙNG = tổng trừ lượng trống thấp nhất, so được với 9.798 MiB đã đo."""
    provider = _armed_with_vram(tmp_path, monkeypatch, free_mau=[9_000, 2_484, 5_000])
    _cho_lay_mau(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert provider.last_job is not None
    assert provider.last_job.peak_vram_mib == 12_282 - 2_484
    assert result.provenance is not None
    assert result.provenance.peak_vram_mib == 9_798


def test_sampler_tra_none_thi_peak_van_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Không đo được phải giữ nghĩa "chưa đo", không được biến thành 0."""
    provider = _armed_with_vram(tmp_path, monkeypatch, free_mau=[None])
    _cho_lay_mau(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert provider.last_job is not None
    assert provider.last_job.peak_vram_mib is None
    assert result.provenance is not None
    assert result.provenance.peak_vram_mib is None


def test_khong_biet_total_thi_khong_doan_peak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed_with_vram(tmp_path, monkeypatch, free_mau=[2_000], total=None)
    _cho_lay_mau(provider, monkeypatch)

    provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert provider.last_job is not None
    assert provider.last_job.peak_vram_mib is None


def test_sampler_nem_loi_thi_render_van_thanh_cong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cổng G3 chỉ GHI NHẬN. Một lượt render 4 phút không được hỏng vì nvidia-smi bận.

    Lưu ý về sức mạnh của test này: luồng nền vốn đã cô lập ngoại lệ, nên nó xanh
    kể cả khi bỏ ``try/except`` trong vòng lấy mẫu. Nó ghi nhận hợp đồng chứ
    **không** khoá được nó — test khoá là
    :func:`test_sampler_loi_tam_thoi_van_tiep_tuc_lay_mau` ngay dưới.
    """
    provider = _armed_with_vram(tmp_path, monkeypatch, sampler_no=True)
    _cho_lay_mau(provider, monkeypatch)

    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert result.path.is_file()
    assert provider.last_job is not None
    assert provider.last_job.peak_vram_mib is None


def test_sampler_loi_tam_thoi_van_tiep_tuc_lay_mau(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đây mới là thứ ``try/except`` trong vòng lặp thật sự mua được.

    Không có nó, **một** lỗi tạm thời giết luôn luồng lấy mẫu và mọi mẫu sau đó
    biến mất — lượt render vẫn xong, nhưng đỉnh VRAM thì mất trắng mà không ai
    biết. Bỏ ``except`` ⇒ test này đỏ.
    """
    _mo_hang_rao_moi_truong(monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", lambda *_a, **_k: "14.0")
    lan = {"n": 0}

    def _hong_lan_dau() -> int | None:
        lan["n"] += 1
        if lan["n"] == 1:
            raise RuntimeError("nvidia-smi ban mot nhip")
        return 2_484

    provider = MuseTalkAvatarProvider(
        install_dir=_fake_install(tmp_path),
        vram_sampler=_hong_lan_dau,
        vram_total_probe=lambda: 12_282,
        vram_sample_interval_sec=0.001,
    )
    _cho_lay_mau(provider, monkeypatch)

    provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert lan["n"] > 1, "vòng lấy mẫu phải sống sót qua lỗi đầu tiên"
    assert provider.last_job is not None
    assert provider.last_job.peak_vram_mib == 12_282 - 2_484


def test_peak_van_duoc_ghi_khi_job_hong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hỏng vì OOM thì đỉnh VRAM chính là bằng chứng cần nhất — không được mất."""
    provider = _armed_with_vram(tmp_path, monkeypatch, free_mau=[1_000])

    def _hong(*_a: object, **_k: object) -> _Completed:
        time.sleep(0.05)
        return _Completed(1, stderr="CUDA out of memory")

    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _hong)

    with pytest.raises(ProviderError, match="THẤT BẠI"):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    assert provider.last_job is not None
    assert provider.last_job.peak_vram_mib == 12_282 - 1_000


def test_peak_vram_chay_toi_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_video_agent.orchestrator.pipeline import Pipeline as _P

    provider = _armed_with_vram(tmp_path, monkeypatch, free_mau=[2_484])
    _cho_lay_mau(provider, monkeypatch)
    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    needed = provider.estimate_resources(_request(tmp_path))
    preflight = check_resources("musetalk", needed, ResourceBudget())
    record = _P._avatar_provenance_record(
        provider.info(), provider.capability(), result, result.path, preflight
    )

    assert record.resources is not None
    assert record.resources.peak_vram_mib == 9_798


def test_mac_dinh_khong_tu_goi_nvidia_smi_trong_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """conftest chặn ``probe_free_vram_mib`` ở CẤP MODULE — adapter phải gọi qua đó.

    Bind thẳng tên hàm lúc import sẽ vô hiệu hoá lớp chặn, và test sẽ âm thầm
    chạy nvidia-smi thật. Test này canh đúng điều đó.
    """
    _mo_hang_rao_moi_truong(monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", lambda *_a, **_k: "14.0")
    provider = MuseTalkAvatarProvider(
        install_dir=_fake_install(tmp_path), vram_sample_interval_sec=0.001
    )
    _cho_lay_mau(provider, monkeypatch)

    provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    #: conftest cho probe trả None ⇒ không có mẫu ⇒ không hỏi tới total probe.
    assert provider.last_job is not None
    assert provider.last_job.peak_vram_mib is None


# --- B1/LOW-4: ghi config hỏng phải thành ProviderError -------------------


def test_ghi_config_loi_he_thong_thanh_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", _bom)
    request = _request(tmp_path)

    def _write_hong(*_a: object, **_k: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", _write_hong)

    with pytest.raises(ProviderError, match="Không ghi được file cấu hình"):
        provider.generate(request, tmp_path / "out.mp4")


# --- B1/LOW-6: output_duration_source tới được manifest -------------------


def test_output_duration_source_di_toi_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ghi ở AvatarProvenance chưa đủ — phải chứng minh nó qua được tầng manifest."""
    from ai_video_agent.orchestrator.pipeline import Pipeline as _P

    provider = _armed(tmp_path, monkeypatch)
    _stub_run_ghi_output(provider, monkeypatch)

    def _probe(_bin: str, _clip: Path, entries: str, stream: str | None = "v:0") -> str:
        return "N/A" if entries == "stream=duration" else "14.080000"

    monkeypatch.setattr(f"{ADAPTER_MODULE}._ffprobe_entries", _probe)
    result = provider.generate(_request(tmp_path), tmp_path / "out.mp4")

    needed = provider.estimate_resources(_request(tmp_path))
    preflight = check_resources("musetalk", needed, ResourceBudget())
    record = _P._avatar_provenance_record(
        provider.info(), provider.capability(), result, result.path, preflight
    )

    assert record.params["output_duration_source"] == "container-format"
    assert record.output_duration_sec == 14.08


# --- 6. Không fallback sang Duix ------------------------------------------


def test_chon_musetalk_khong_bao_gio_ra_duix(tmp_path: Path) -> None:
    config = Config(runtime_dir=tmp_path)
    for mode in (ProviderMode.MOCK, ProviderMode.REAL):
        chosen = build_provider_set(
            ProviderSelection(avatar="musetalk"), mode=mode, config=config
        ).avatar
        assert not isinstance(chosen, DuixAvatarProvider | MockDuixAvatarProvider)
        assert chosen.info().name == "musetalk"


def test_musetalk_hong_thi_hong_han_khong_am_tham_doi_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallback âm thầm sẽ khiến bake-off chấm nhầm Duix rồi ghi là MuseTalk."""
    provider = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr(f"{ADAPTER_MODULE}.subprocess.run", lambda *_a, **_k: _Completed(1))

    with pytest.raises(ProviderError):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")
    assert provider.last_job is not None
    assert provider.last_job.produced is None


# --- 7. Duix không bị hồi quy ----------------------------------------------


def test_duix_van_la_mac_dinh() -> None:
    assert ProviderSelection().avatar == "duix"


def test_duix_giu_nguyen_danh_tinh_va_gate() -> None:
    info = DuixAvatarProvider().info()
    assert info.name == "duix"
    assert info.gate == "D03"
    assert info.billable is False


def test_registry_mac_dinh_van_dung_duix(tmp_path: Path) -> None:
    providers = build_provider_set(
        ProviderSelection(), mode=ProviderMode.MOCK, config=Config(runtime_dir=tmp_path)
    )
    assert isinstance(providers.avatar, MockDuixAvatarProvider)


# --- 8. Không còn định danh cũ --------------------------------------------


#: Ghép từ mảnh để chính file test này không chứa chuỗi cấm — nếu viết thẳng,
#: test sẽ tự soi thấy mình và đỏ vì lý do vô nghĩa.
_D05 = "D05"
FORBIDDEN_LABELS = (f"{_D05}-MT", f"{_D05}MT", f"{_D05}_MT")


def test_khong_con_dinh_danh_cu_trong_source_va_test() -> None:
    """D04-G thay thế hoàn toàn nhãn cũ; hai nhãn song song sẽ gây lẫn."""
    goc = Path(__file__).resolve().parents[1]
    files = [
        *(goc / "src" / "ai_video_agent" / "providers" / "musetalk").glob("*.py"),
        Path(__file__),
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for cam in FORBIDDEN_LABELS:
            assert cam not in text, f"{path.name} còn định danh cũ {cam!r}"


def test_source_khong_ghi_cung_duong_dan_runtime_that() -> None:
    """Đường dẫn dữ liệu thật không được nằm trong repo (ADR-0002).

    Kiểm đúng thứ phải cấm: **thư mục runtime thật**. Ví dụ về *định dạng* đường
    dẫn trong docstring là tài liệu, không phải đường dẫn bị ghim.
    """
    goc = Path(__file__).resolve().parents[1]
    runtime_root = "AI-VIDEO-AGENT-RUNTIME"
    for path in (goc / "src" / "ai_video_agent" / "providers" / "musetalk").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert runtime_root not in text, f"{path.name} ghim cứng thư mục runtime thật"
        assert "bakeoff-envs" not in text or "venv_python" in text, (
            "đường venv chỉ được xuất hiện như tham số mặc định, không rải khắp file"
        )
