"""D05-C — ba thứ làm đường production dễ kiểm chứng hơn.

1. Duix ghi được ``peak_vram_mib`` — không có nó thì mọi tranh luận về ngưỡng
   VRAM đều dựa vào đo tay ngoài tiến trình.
2. Lệnh FFmpeg in ra phải chép-dán được.
3. Hỏng vì môi trường phải lộ ra **trước** khi tốn thời gian, không phải giữa chừng.
"""

from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ai_video_agent.cli import preflight
from ai_video_agent.cli.doctor import Status
from ai_video_agent.cli.main import app
from ai_video_agent.cli.preflight import blocking, check_duix_ready
from ai_video_agent.config import Config
from ai_video_agent.providers.base import AvatarRequest
from ai_video_agent.providers.duix import DuixAvatarProvider
from ai_video_agent.providers.duix.adapter import DuixJob
from ai_video_agent.providers.duix.capability import DUIX_RESOURCES

if TYPE_CHECKING:
    from ai_video_agent.providers.base import AvatarResult

runner = CliRunner()

PROBE_MODULE = "ai_video_agent.providers.media_probe"
PREFLIGHT_MODULE = "ai_video_agent.cli.preflight"

BRIEF = "Nhà phố hai tầng tại Biên Hoà, sổ hồng riêng. Liên hệ 0909123456."


def _wav(path: Path) -> Path:
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48_000)
        w.writeframes(b"\x11\x00" * 48_000)
    return path


def _request(tmp_path: Path) -> AvatarRequest:
    source = tmp_path / "avatar.mp4"
    source.write_bytes(b"nguon avatar")
    return AvatarRequest(
        shot_id="shot-01",
        audio_path=_wav(tmp_path / "audio.wav"),
        avatar_source=source,
        width=1080,
        height=1920,
        fps=25,
        duration_sec=1.0,
    )


# --- 1. peak_vram_mib cho Duix --------------------------------------------


def _duix_co_lay_mau(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    free_mau: list[int | None],
    total: int | None = 12_282,
    wait_hong: bool = False,
) -> DuixAvatarProvider:
    """Duix thật với HTTP giả lập nhưng **vòng lấy mẫu VRAM chạy thật**.

    ``wait`` nán lại 50 ms để luồng nền kịp chạy vài chục vòng ở nhịp 1 ms —
    cùng kỹ thuật mà test sampler của MuseTalk đang dùng.
    """
    produced = tmp_path / "ket-qua.mp4"
    produced.write_bytes(b"ket qua duix")
    monkeypatch.setattr(f"{PROBE_MODULE}._ffprobe_entries", lambda *_a, **_k: "25/1")

    con_lai = list(free_mau)

    def _lay_mau() -> int | None:
        return con_lai.pop(0) if con_lai else free_mau[-1]

    provider = DuixAvatarProvider(
        path_map=((str(tmp_path), "/inputs"),),
        vram_sampler=_lay_mau,
        vram_total_probe=lambda: total,
        vram_sample_interval_sec=0.001,
    )
    job = DuixJob(code="aiva-test", submitted_at=0.0, payload={}, video_duration=1000)
    monkeypatch.setattr(provider, "submit", lambda **_k: job)
    monkeypatch.setattr(provider, "_resolve_result", lambda _job: produced)

    def _wait(_job: DuixJob) -> None:
        time.sleep(0.05)
        if wait_hong:
            msg = "Duix bao job that bai"
            raise RuntimeError(msg)

    monkeypatch.setattr(provider, "wait", _wait)
    return provider


def _sinh(provider: DuixAvatarProvider, tmp_path: Path) -> AvatarResult:
    return provider.generate(_request(tmp_path), tmp_path / "out.mp4")


def test_duix_ghi_peak_vram_vao_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đỉnh ĐÃ DÙNG = tổng trừ lượng trống thấp nhất quan sát được.

    Trước D05-C trường này luôn ``None`` cho Duix, nên D05-B phải đo tay bằng
    ``nvidia-smi`` chạy song song — con số ấy không vào được manifest, tức là
    không truy vết được về sau.
    """
    provider = _duix_co_lay_mau(tmp_path, monkeypatch, free_mau=[9_000, 4_251, 5_000])

    result = _sinh(provider, tmp_path)

    assert result.provenance is not None
    assert result.provenance.peak_vram_mib == 12_282 - 4_251


def test_duix_khong_do_duoc_thi_peak_van_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Máy không có ``nvidia-smi`` phải giữ nghĩa "chưa đo", không thành 0."""
    provider = _duix_co_lay_mau(tmp_path, monkeypatch, free_mau=[None])

    result = _sinh(provider, tmp_path)

    assert result.provenance is not None
    assert result.provenance.peak_vram_mib is None


def test_duix_khong_biet_total_thi_khong_doan_peak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Biết phần trống mà không biết tổng thì **không suy ra** phần đã dùng."""
    provider = _duix_co_lay_mau(tmp_path, monkeypatch, free_mau=[4_251], total=None)

    result = _sinh(provider, tmp_path)

    assert result.provenance is not None
    assert result.provenance.peak_vram_mib is None


def test_duix_peak_van_do_duoc_khi_job_hong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Job hỏng vẫn phải giữ được đỉnh — với một lỗi OOM đó là bằng chứng cần nhất.

    Đây là thứ khối ``finally`` mua được. Bỏ nó ⇒ test này đỏ.
    """
    provider = _duix_co_lay_mau(tmp_path, monkeypatch, free_mau=[1_000], wait_hong=True)

    with pytest.raises(RuntimeError, match="that bai"):
        _sinh(provider, tmp_path)

    # Đọc thẳng thuộc tính riêng: job đã hỏng nên không có AvatarResult để hỏi,
    # mà đúng cái cần khẳng định là "đỉnh vẫn được ghi lại" chứ không phải nó
    # đi tới đâu.
    assert provider._peak_vram_mib == 12_282 - 1_000


def test_peak_vram_duix_di_toi_record_cua_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đo được là một chuyện; **vào tới manifest** mới là thứ dùng được về sau.

    Xác minh tới tầng ``ResourceUsage`` vì đó là hình dạng ghi ra đĩa. Chưa xác
    minh được trên phần cứng thật: cổng VRAM chặn mọi lượt render thật kể từ khi
    ngưỡng lên 8.500 MiB — xem báo cáo D05-C.
    """
    from ai_video_agent.orchestrator.pipeline import Pipeline
    from ai_video_agent.providers.resource_budget import ResourceBudget, check_resources

    provider = _duix_co_lay_mau(tmp_path, monkeypatch, free_mau=[4_251])
    result = _sinh(provider, tmp_path)

    can = provider.estimate_resources(_request(tmp_path))
    record = Pipeline._avatar_provenance_record(
        provider.info(),
        provider.capability(),
        result,
        result.path,
        check_resources("duix", can, ResourceBudget()),
    )

    assert record.resources is not None
    assert record.resources.peak_vram_mib == 12_282 - 4_251


def test_duix_va_musetalk_dung_chung_mot_sampler() -> None:
    """Một bản cho cả hai adapter. Hai bản là hai chỗ để lệch nhau."""
    from ai_video_agent.providers.duix import adapter as duix_adapter
    from ai_video_agent.providers.musetalk import adapter as musetalk_adapter

    assert duix_adapter.VramSampler is musetalk_adapter.VramSampler


# --- 2. Rich không được nuốt [vout] ---------------------------------------


def test_lenh_ffmpeg_in_ra_giu_nguyen_vout(capsys: pytest.CaptureFixture[str]) -> None:
    """``[vout]`` phải còn nguyên trong lệnh in ra.

    Rich đọc ``[...]`` là thẻ định dạng nên nuốt mất ``[vout]``; ai chép lệnh in
    ra sẽ được ``-map  -map 0:a?`` — một lệnh hỏng. Lệnh trong manifest vẫn luôn
    đúng, hỏng chỉ ở khâu hiển thị. Bỏ ``escape`` ⇒ test này đỏ.
    """
    from ai_video_agent.cli.main import _print_warnings

    _print_warnings(["Lệnh FFmpeg: ffmpeg -filter_complex [0:v]scale=2[vout] -map [vout] ra.mp4"])

    out = capsys.readouterr().out
    assert "[vout]" in out, "Rich đã nuốt mất nhãn output của filter_complex"
    assert "[0:v]" in out
    assert "-map [vout]" in out


def test_escape_khong_giet_markup_cua_chinh_ta(capsys: pytest.CaptureFixture[str]) -> None:
    """Chỉ nội dung cảnh báo bị escape; markup bao ngoài vẫn phải sống.

    Nếu escape cả dòng thì người dùng sẽ thấy chữ ``[dim]`` hiện ra.
    """
    from ai_video_agent.cli.main import _print_warnings

    _print_warnings(["ghi chú thường"])

    out = capsys.readouterr().out
    assert "[dim]" not in out
    assert "ghi chú thường" in out


# --- 3. Kiểm tra vận hành trước render thật -------------------------------


def _khong_co_binary(*_a: object, **_k: object) -> None:
    return None


def _endpoint_song(monkeypatch: pytest.MonkeyPatch, *, ma: int = 404) -> None:
    """Duix trả 404 ở ``/`` — không phải route của nó, nhưng server đang nghe."""

    def _mo(*_a: object, **_k: object) -> object:
        raise urllib.error.HTTPError("http://x", ma, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.urllib.request.urlopen", _mo)


def _endpoint_chet(monkeypatch: pytest.MonkeyPatch) -> None:
    def _mo(*_a: object, **_k: object) -> object:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.urllib.request.urlopen", _mo)


def _docker_song(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Xong:
        returncode = 0
        stdout = "29.6.1\n"
        stderr = ""

    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.subprocess.run", lambda *_a, **_k: _Xong())


def _ket_qua(results: list[preflight.CheckResult], name: str) -> preflight.CheckResult:
    return next(r for r in results if r.name == name)


def test_thieu_ffprobe_thi_chan_va_noi_ro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter Duix đo fps trước khi gửi job, nên thiếu ffprobe là hỏng chắc chắn."""
    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.shutil.which", _khong_co_binary)
    _endpoint_chet(monkeypatch)

    ket_qua = check_duix_ready(Config(runtime_dir=tmp_path))
    ffprobe = _ket_qua(ket_qua, "ffprobe")

    assert ffprobe.status is Status.FAIL
    assert "ffprobe" in ffprobe.detail
    assert ffprobe in blocking(ket_qua)


def test_docker_chua_chay_thi_chan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Hong:
        returncode = 1
        stdout = ""
        stderr = "error during connect: Docker Desktop chua khoi dong"

    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.subprocess.run", lambda *_a, **_k: _Hong())
    _endpoint_chet(monkeypatch)

    docker = _ket_qua(check_duix_ready(Config(runtime_dir=tmp_path)), "docker")

    assert docker.status is Status.FAIL
    assert "Docker Desktop" in docker.detail


def test_container_chua_bat_thi_chi_ro_lenh_bat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lỗi phải kèm đúng lệnh cần gõ, không bắt người dùng tự tra tài liệu."""
    _docker_song(monkeypatch)
    _endpoint_chet(monkeypatch)

    duix = _ket_qua(check_duix_ready(Config(runtime_dir=tmp_path)), "duix")

    assert duix.status is Status.FAIL
    assert preflight.COMPOSE_UP in duix.detail


def test_endpoint_tra_404_van_tinh_la_san_sang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/`` không phải route của Duix. 404 nghĩa là server đã lên và đang nghe.

    Coi 404 là hỏng sẽ chặn nhầm một container hoàn toàn khoẻ mạnh.
    """
    _docker_song(monkeypatch)
    _endpoint_song(monkeypatch)

    duix = _ket_qua(check_duix_ready(Config(runtime_dir=tmp_path)), "duix")

    assert duix.status is Status.PASS


def test_khong_biet_vram_thi_khong_chan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Không đo được VRAM là ``INFO``, không phải ``FAIL``.

    Máy không có ``nvidia-smi`` mà bị chặn thì không ai render được gì; đoán một
    mặc định còn tệ hơn.
    """
    _docker_song(monkeypatch)
    _endpoint_song(monkeypatch)

    ket_qua = check_duix_ready(Config(runtime_dir=tmp_path))
    vram = _ket_qua(ket_qua, "vram")

    assert vram.status is Status.INFO
    assert not blocking(ket_qua)


def _gpu(monkeypatch: pytest.MonkeyPatch, *, total: int | None, free: int | None) -> None:
    """Giả lập card: tổng và trống là hai phép đo riêng.

    Vá ở ``resource_budget`` chứ không ở nơi gọi — đó là seam mà ``conftest``
    đã dựng để không test nào chạm ``nvidia-smi`` thật.
    """
    from ai_video_agent.providers import resource_budget as rb

    monkeypatch.setattr(rb, "probe_total_vram_mib", lambda: total)
    monkeypatch.setattr(rb, "probe_free_vram_mib", lambda: free)


def test_card_du_cho_nhung_dang_bi_chiem_thi_canh_bao_chu_khong_chan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """total 12.282 / trống 7.651 / cần 8.500 ⇒ **qua**, kèm cảnh báo.

    Đây đúng trạng thái máy lúc chạy D05-B: lượt render thành công chạm đỉnh
    11.716 trên card 12.282. Chặn nó là chặn một máy đã chứng minh chạy được —
    vì 8.500 là đỉnh của *cả card*, đã bao gồm phần desktop và container đang
    giữ, mà phần đó lại bị trừ khỏi "trống" một lần nữa.
    """
    _docker_song(monkeypatch)
    _endpoint_song(monkeypatch)
    _gpu(monkeypatch, total=12_282, free=7_651)

    ket_qua = check_duix_ready(Config(runtime_dir=tmp_path))
    vram = _ket_qua(ket_qua, "vram")

    assert not blocking(ket_qua), "card đủ chỗ thì không được chặn"
    assert vram.status is Status.WARN
    assert "7651" in vram.detail
    assert "restart" in vram.detail, "phải chỉ cách trả VRAM khi container còn giữ model"


def test_card_khong_du_cho_thi_van_chan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """total 8.192 / trống 7.651 / cần 8.500 ⇒ **chặn**.

    Card nhỏ hơn đỉnh đã đo thì đóng bao nhiêu ứng dụng cũng không đủ. Đây là
    ranh giới giữa "đang bị chiếm" và "không đủ chỗ" — hàng rào phải phân biệt
    được hai thứ đó, nếu không thì nó vô dụng theo một trong hai hướng.
    """
    _docker_song(monkeypatch)
    _endpoint_song(monkeypatch)
    _gpu(monkeypatch, total=8_192, free=7_651)

    ket_qua = check_duix_ready(Config(runtime_dir=tmp_path))
    vram = _ket_qua(ket_qua, "vram")

    assert vram.status is Status.FAIL
    assert vram in blocking(ket_qua)
    assert "8192" in vram.detail
    assert str(DUIX_RESOURCES.vram_mib) in vram.detail


def test_card_thoai_mai_thi_pass_khong_canh_bao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _docker_song(monkeypatch)
    _endpoint_song(monkeypatch)
    _gpu(monkeypatch, total=24_576, free=20_000)

    vram = _ket_qua(check_duix_ready(Config(runtime_dir=tmp_path)), "vram")

    assert vram.status is Status.PASS


def test_budget_khai_tay_van_duoc_ton_trong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Khai ``AIVA_VRAM_BUDGET_MIB`` thì con số đó thắng cả máy dò.

    Người vận hành biết mình đang chia GPU với việc khác; khai thấp mà vẫn bị
    máy dò ghi đè thì lời khai vô nghĩa.
    """
    _docker_song(monkeypatch)
    _endpoint_song(monkeypatch)
    _gpu(monkeypatch, total=24_576, free=24_000)

    ket_qua = check_duix_ready(Config(runtime_dir=tmp_path, vram_budget_mib=2_048))
    vram = _ket_qua(ket_qua, "vram")

    assert vram.status is Status.FAIL, "khai 2048 thì phải chặn, dù card thật rất rộng"
    assert "2048" in vram.detail
    assert vram in blocking(ket_qua)


def test_du_dieu_kien_thi_khong_con_gi_chan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _docker_song(monkeypatch)
    _endpoint_song(monkeypatch)

    ket_qua = check_duix_ready(
        Config(runtime_dir=tmp_path, vram_budget_mib=DUIX_RESOURCES.vram_mib + 1)
    )

    assert not blocking(ket_qua)


# --- Cổng của pipeline cũng phải theo đơn vị đó ---------------------------


def test_pipeline_khong_chan_khi_card_du_cho() -> None:
    """``check_resources`` là thứ đã chặn ``aiva render`` ở D05-C.

    Sửa mỗi ``cli/preflight`` là chưa đủ: ``make`` sẽ qua rồi chết ở tầng dưới.
    """
    from ai_video_agent.providers.resource_budget import ResourceBudget, check_resources

    report = check_resources(
        "duix",
        DUIX_RESOURCES,
        ResourceBudget(
            vram_mib=12_282, vram_free_mib=7_651, ram_mib=32_768, storage_mib=500_000
        ),
    )

    assert report.ok, "card 12.282 phải đủ cho đỉnh 8.500"
    assert report.advisories, "nhưng phải nói ra là đang trống ít"
    assert "7651" in report.warning()


def test_pipeline_van_chan_khi_card_nho_hon_dinh() -> None:
    from ai_video_agent.providers.resource_budget import ResourceBudget, check_resources

    report = check_resources(
        "duix",
        DUIX_RESOURCES,
        ResourceBudget(vram_mib=8_192, vram_free_mib=7_651, ram_mib=32_768, storage_mib=500_000),
    )

    assert not report.ok
    assert "8192" in report.message()


# --- 4. `make` dùng kiểm tra đó, và chỉ ở đường thật ----------------------


@pytest.fixture
def du_tai_san(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Project đã có avatar + voice, sẵn sàng để dựng."""
    import wave

    from ai_video_agent.domain.assets import AssetEntry, Consent
    from ai_video_agent.domain.enums import AssetKind, ConsentStatus
    from ai_video_agent.orchestrator.repository import ProjectRepository

    project_id = "smoke-d05c"
    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))
    runner.invoke(app, ["plan", "--brief", BRIEF, "--id", project_id, "--duration", "30"])

    wav = tmp_path / "giong.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48_000)
        w.writeframes(b"\x11\x00" * 48_000 * 6)
    runner.invoke(app, ["voice-add", str(wav), "--project", project_id, "--owner", "Chủ máy"])

    repo = ProjectRepository(tmp_path)
    nguon = repo.paths(project_id).assets_dir / "avatar/avatar-chinh.mp4"
    nguon.parent.mkdir(parents=True, exist_ok=True)
    nguon.write_bytes(b"video gia cho test")
    manifest = repo.load_assets(project_id)
    manifest.assets.append(
        AssetEntry(
            id="avatar-chinh",
            path="avatar/avatar-chinh.mp4",
            sha256="a" * 64,
            kind=AssetKind.AVATAR_SOURCE,
            bytes=nguon.stat().st_size,
            consent=Consent(status=ConsentStatus.GRANTED, owner="Chủ máy"),
        )
    )
    repo.save_assets(manifest)
    return project_id


def test_make_that_dung_lai_khi_may_chua_san_sang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, du_tai_san: str
) -> None:
    """Thiếu Docker thì dừng **trước** khi duyệt, và chưa đụng gì tới project.

    Duyệt xong mới phát hiện thiếu Docker sẽ để project ở APPROVED trong khi
    chưa dựng được gì — trạng thái nói dối về việc đã xảy ra.
    """
    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.shutil.which", _khong_co_binary)
    _endpoint_chet(monkeypatch)

    ket_qua = runner.invoke(app, ["make", "--id", du_tai_san, "--brief", BRIEF, "--by", "Chủ máy"])

    assert "Dừng lại" in ket_qua.output
    assert "ĐÃ CHẠY" not in ket_qua.output
    project = json.loads((tmp_path / "projects" / du_tai_san / "project.json").read_text("utf-8"))
    assert project["approval"] is None, "không được duyệt khi biết chắc chưa dựng được"


def test_make_mock_khong_doi_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, du_tai_san: str
) -> None:
    """``--mock`` là để chạy thử trên máy không có GPU — đừng bắt nó có Docker."""

    def _no_khi_goi(*_a: object, **_k: object) -> None:
        msg = "make --mock không được đụng tới kiểm tra Docker"
        raise AssertionError(msg)

    monkeypatch.setattr(f"{PREFLIGHT_MODULE}.subprocess.run", _no_khi_goi)

    ket_qua = runner.invoke(
        app, ["make", "--id", du_tai_san, "--brief", BRIEF, "--by", "Chủ máy", "--mock"]
    )

    assert ket_qua.exit_code == 0, ket_qua.output
    assert "ĐÃ CHẠY" in ket_qua.output
