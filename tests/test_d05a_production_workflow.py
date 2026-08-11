"""D05-A — đường chạy production mặc định.

Ba câu nhóm test này trả lời:

1. Người dùng không khai gì thì có ra Duix không?
2. MuseTalk có lọt vào production được không?
3. Một lệnh có ra được video, và output có nằm đúng chỗ không?
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_video_agent import CURRENT_GATE, gate_is_open
from ai_video_agent.cli.main import app
from ai_video_agent.config import Config
from ai_video_agent.domain.enums import ProviderMode
from ai_video_agent.domain.project import ProviderSelection
from ai_video_agent.errors import ConfigError
from ai_video_agent.providers.duix import DuixAvatarProvider, MockDuixAvatarProvider
from ai_video_agent.providers.registry import build_provider_set

runner = CliRunner()

BRIEF = (
    "Bán lô đất thổ cư tại TP. Biên Hoà, sổ hồng riêng. "
    "Giá 1,2 tỷ, công chứng ngay. Liên hệ 0909123456."
)
PROJECT = "demo-d05a"


# --- 1. Duix là mặc định production ---------------------------------------


def test_duix_la_avatar_mac_dinh() -> None:
    assert ProviderSelection().avatar == "duix"


def test_khong_khai_gi_thi_ra_duix(tmp_path: Path) -> None:
    """Người dùng không phải nhớ tên backend nào cả."""
    config = Config(runtime_dir=tmp_path)
    mock = build_provider_set(ProviderSelection(), mode=ProviderMode.MOCK, config=config)
    real = build_provider_set(ProviderSelection(), mode=ProviderMode.REAL, config=config)

    assert isinstance(mock.avatar, MockDuixAvatarProvider)
    assert isinstance(real.avatar, DuixAvatarProvider)


def test_duix_khong_tinh_tien(tmp_path: Path) -> None:
    """Chạy local ⇒ billable=false. Đây là điều kiện của D05-A."""
    providers = build_provider_set(
        ProviderSelection(), mode=ProviderMode.REAL, config=Config(runtime_dir=tmp_path)
    )
    assert providers.avatar.info().billable is False
    assert providers.any_billable is False


# --- 2. MuseTalk không lọt vào production ---------------------------------


def test_musetalk_khong_chon_duoc_o_production(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="research candidate"):
        build_provider_set(
            ProviderSelection(avatar="musetalk"),
            mode=ProviderMode.REAL,
            config=Config(runtime_dir=tmp_path),
        )


def test_gate_musetalk_van_dong_o_trang_thai_mac_dinh() -> None:
    """Nếu gate mở, hàng rào trên vô hiệu — nên phải canh cả trạng thái gate."""
    assert CURRENT_GATE == "D04"
    assert gate_is_open("D04G") is False


def test_make_tu_choi_project_khai_backend_khac(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make`` là đường production; project chốt backend khác thì nó dừng."""
    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))
    runner.invoke(app, ["plan", "--brief", BRIEF, "--id", PROJECT, "--duration", "30"])

    duong = tmp_path / "projects" / PROJECT / "project.json"
    data = json.loads(duong.read_text(encoding="utf-8"))
    data["providers"]["avatar"] = "musetalk"
    duong.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    ket_qua = runner.invoke(app, ["make", "--id", PROJECT, "--brief", BRIEF])

    assert ket_qua.exit_code == 1
    assert "chỉ chạy Duix" in ket_qua.output


# --- 3. Một lệnh, và nó chỉ đường khi thiếu -------------------------------


def test_make_dung_lai_va_chi_ro_tai_san_con_thieu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thiếu tài sản thì in đúng lệnh cần chạy, không hỏng giữa chừng."""
    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))

    ket_qua = runner.invoke(app, ["make", "--id", PROJECT, "--brief", BRIEF, "--duration", "30"])

    assert ket_qua.exit_code == 0, ket_qua.output
    assert "avatar-add" in ket_qua.output
    assert "voice-add" in ket_qua.output
    assert PROJECT in ket_qua.output


def test_make_lap_lai_kich_ban_khi_noi_dung_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tao_du_tai_san: None
) -> None:
    """Sửa nội dung rồi chạy lại cùng ID phải ra kịch bản MỚI.

    D06-B bắt được: ``make`` dùng lại kịch bản cũ cho project đã tồn tại, nên
    brief đổi hẳn mà video ra vẫn mang nội dung cũ — và vẫn báo thành công. Một
    công cụ dựng video mà âm thầm bỏ qua nội dung bạn vừa sửa là công cụ hỏng.
    """
    del tao_du_tai_san
    moi = (
        "Căn hộ hai phòng ngủ tại quận Bình Thạnh. Ban công hướng đông nam. "
        "Giá hai tỷ tám, có thương lượng. Liên hệ 0912345678 để xem nhà."
    )

    ket_qua = runner.invoke(app, ["make", "--id", PROJECT, "--brief", moi, "--duration", "30"])

    assert ket_qua.exit_code == 0, ket_qua.output
    assert "lập lại kịch bản" in ket_qua.output
    duong = tmp_path / "projects" / PROJECT
    assert "Bình Thạnh" in json.loads(duong.joinpath("project.json").read_text("utf-8"))["brief_vi"]
    assert "Bình Thạnh" in duong.joinpath("storyboard.json").read_text("utf-8")


def test_make_giu_kich_ban_khi_noi_dung_khong_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tao_du_tai_san: None
) -> None:
    """Chạy lại đúng lệnh cũ thì **không** được lập lại — đó là đường resume.

    Lập lại mỗi lần sẽ đổi hash storyboard, làm phê duyệt cũ hết hiệu lực và
    huỷ cache của mọi shot, biến "bổ sung tài sản rồi chạy tiếp" thành "dựng
    lại từ đầu".
    """
    del tao_du_tai_san
    truoc = (tmp_path / "projects" / PROJECT / "storyboard.json").read_text("utf-8")

    ket_qua = runner.invoke(app, ["make", "--id", PROJECT, "--brief", BRIEF, "--duration", "30"])

    assert "dùng lại kịch bản hiện tại" in ket_qua.output
    assert (tmp_path / "projects" / PROJECT / "storyboard.json").read_text("utf-8") == truoc


def test_make_khong_tu_duyet_kich_ban(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tao_du_tai_san: None
) -> None:
    """Không có ``--by`` thì dừng sau lập kế hoạch.

    Duyệt kịch bản là việc của người. Một lệnh gộp mà tự duyệt thay sẽ vô hiệu
    hoá đúng cái cổng mà brief §9 dựng lên.
    """
    del tao_du_tai_san
    ket_qua = runner.invoke(app, ["make", "--id", PROJECT, "--brief", BRIEF, "--duration", "30"])

    assert ket_qua.exit_code == 0, ket_qua.output
    assert "Dừng ở bước lập kế hoạch" in ket_qua.output
    assert "--by" in ket_qua.output
    project = json.loads((tmp_path / "projects" / PROJECT / "project.json").read_text("utf-8"))
    assert project["approval"] is None, "không được tự duyệt"


@pytest.fixture
def tao_du_tai_san(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dựng project với avatar + voice đã đăng ký, dùng đúng CLI thật."""
    import wave

    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))
    runner.invoke(app, ["plan", "--brief", BRIEF, "--id", PROJECT, "--duration", "30"])

    wav = tmp_path / "giong.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48_000)
        w.writeframes(b"\x11\x00" * 48_000 * 6)
    r = runner.invoke(
        app, ["voice-add", str(wav), "--project", PROJECT, "--owner", "Chủ máy"]
    )
    assert r.exit_code == 0, r.output

    #: Đăng ký avatar thẳng vào manifest: `avatar-add` cần ffprobe thật, mà test
    #: không được phụ thuộc vào công cụ ngoài.
    from ai_video_agent.domain.assets import AssetEntry, Consent
    from ai_video_agent.domain.enums import AssetKind, ConsentStatus
    from ai_video_agent.orchestrator.repository import ProjectRepository

    repo = ProjectRepository(tmp_path)
    nguon = repo.paths(PROJECT).assets_dir / "avatar/avatar-chinh.mp4"
    nguon.parent.mkdir(parents=True, exist_ok=True)
    nguon.write_bytes(b"video gia cho test")
    manifest = repo.load_assets(PROJECT)
    manifest.assets.append(
        AssetEntry(
            id="avatar-chinh", path="avatar/avatar-chinh.mp4",
            sha256="a" * 64, kind=AssetKind.AVATAR_SOURCE, bytes=nguon.stat().st_size,
            consent=Consent(status=ConsentStatus.GRANTED, owner="Chủ máy"),
        )
    )
    repo.save_assets(manifest)


def test_make_chay_tron_ra_video_bang_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tao_du_tai_san: None
) -> None:
    """Đường trọn vẹn: có ``--by`` ⇒ duyệt + dựng, ra file mp4.

    Dùng ``--mock`` để test không cần Docker/GPU — nhưng đi qua **đúng** các bước
    mà đường production đi: lập kế hoạch, kiểm tài sản, duyệt, dựng.
    """
    del tao_du_tai_san, monkeypatch

    ket_qua = runner.invoke(
        app,
        ["make", "--id", PROJECT, "--brief", BRIEF, "--duration", "30",
         "--by", "Chủ máy", "--mock"],
    )

    assert ket_qua.exit_code == 0, ket_qua.output
    assert "1/4" in ket_qua.output or "đã có" in ket_qua.output
    assert "ĐÃ CHẠY" in ket_qua.output
    assert "chạy thử bằng file giả" in ket_qua.output, "phải nói rõ đây là bản giả"
    assert list((tmp_path / "projects" / PROJECT / "outputs").glob("*.mp4"))


def test_output_nam_trong_runtime_khong_vao_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tao_du_tai_san: None
) -> None:
    """Media thật không bao giờ được ghi vào repo Git (ADR-0002)."""
    del tao_du_tai_san
    runner.invoke(app, ["approve", PROJECT, "--by", "Chủ máy"])
    runner.invoke(app, ["render", PROJECT, "--execute"])

    repo_goc = Path(__file__).resolve().parents[1]
    outputs = list((tmp_path / "projects" / PROJECT / "outputs").glob("*.mp4"))

    assert outputs, "phải có output"
    for f in outputs:
        assert tmp_path in f.parents, "output phải nằm dưới AIVA_RUNTIME_DIR"
        assert repo_goc not in f.parents, "KHÔNG được ghi media vào repo"


# --- 4. Manifest đủ trường ------------------------------------------------


def test_manifest_du_truong_de_truy_vet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tao_du_tai_san: None
) -> None:
    """Manifest là bản ghi kiểm chứng — thiếu trường là mất khả năng truy vết."""
    del tao_du_tai_san
    runner.invoke(app, ["approve", PROJECT, "--by", "Chủ máy"])
    runner.invoke(app, ["render", PROJECT, "--execute"])

    renders = sorted((tmp_path / "projects" / PROJECT / "renders").iterdir())
    assert renders, "phải có thư mục run"
    manifest = json.loads((renders[-1] / "render-manifest.json").read_text("utf-8"))

    for khoa in ("project_id", "run_id", "provider_mode", "storyboard_sha256",
                 "created_at", "status", "records", "estimated_cost_usd",
                 "actual_cost_usd", "ai_disclosure_applied", "tool_versions"):
        assert khoa in manifest, f"manifest thiếu {khoa!r}"

    avatar = [r for r in manifest["records"] if r["stage"] == "avatar"]
    assert avatar, "phải có bước avatar"
    for r in avatar:
        assert r["provider"] == "duix"
        assert r["billable"] is False
        assert r["actual_cost_usd"] == 0.0
        assert r["avatar_provenance"] is not None, "phải truy ngược được về model"


def test_chi_phi_bang_khong_khi_chay_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tao_du_tai_san: None
) -> None:
    del tao_du_tai_san
    runner.invoke(app, ["approve", PROJECT, "--by", "Chủ máy"])
    runner.invoke(app, ["render", PROJECT, "--execute"])

    renders = sorted((tmp_path / "projects" / PROJECT / "renders").iterdir())
    manifest = json.loads((renders[-1] / "render-manifest.json").read_text("utf-8"))

    assert manifest["actual_cost_usd"] == 0.0
    assert manifest["estimated_cost_usd"] == 0.0
    assert all(r["billable"] is False for r in manifest["records"])
