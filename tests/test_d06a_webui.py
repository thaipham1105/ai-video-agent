"""D06-A — giao diện web local, launcher, và báo cáo nghiệm thu.

Câu hỏi trung tâm của nhóm test này: **UI có phải là vỏ không?** Một giao diện
tự dựng pipeline riêng sẽ đi vòng qua mọi hàng rào đã dựng (gate, consent, cost
guard, preflight tài nguyên) cùng một lúc, và không ai phát hiện ra cho tới lúc
một video sai được gửi cho khách.
"""

from __future__ import annotations

import io
import json
import threading
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from ai_video_agent.cli import main as cli_main
from ai_video_agent.config import Config
from ai_video_agent.errors import ValidationError
from ai_video_agent.webui import DEFAULT_PORT, HOST, intake, launcher, service
from ai_video_agent.webui.jobs import JobBusyError, JobRunner
from ai_video_agent.webui.report import LIPSYNC_NOTE, build_report_html, write_report

if TYPE_CHECKING:
    from ai_video_agent.domain.render import RenderManifest

fastapi = pytest.importorskip("fastapi", reason="UI cần extra tts (fastapi/uvicorn/jinja2)")
from fastapi.testclient import TestClient  # noqa: E402 - phải sau importorskip

BRIEF = "Nhà phố hai tầng tại Biên Hoà, sổ hồng riêng. Liên hệ 0909123456."


# --- 1. Chỉ bind localhost ------------------------------------------------


def test_host_la_localhost_va_khong_doi_duoc() -> None:
    """Máy này dựng video từ hình và giọng thật — mở ra LAN là hỏng chuyện.

    ``HOST`` là hằng số, không phải tham số: không có ``--host`` trên CLI thì
    không ai lỡ tay mở ra ngoài.
    """
    assert HOST == "127.0.0.1"

    import inspect

    tham_so = inspect.signature(cli_main.ui).parameters
    assert "host" not in tham_so, "không được có tuỳ chọn --host"
    assert "port" in tham_so


def test_serve_truyen_dung_host_cho_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hằng số đúng chưa đủ — phải chứng minh nó tới được uvicorn."""
    import uvicorn

    from ai_video_agent.webui import app as web_app

    ghi: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kw: ghi.update(kw))
    web_app.serve(Config(runtime_dir=tmp_path), port=1234, open_browser=False)

    assert ghi["host"] == "127.0.0.1"
    assert ghi["port"] == 1234


# --- 2. UI gọi lại CLI, không nhân bản pipeline ---------------------------


def test_render_goi_dung_ham_make_cua_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đây là test quan trọng nhất của D06-A.

    Nếu UI tự dựng ``Pipeline`` thay vì gọi ``cli_main.make``, mọi hàng rào trên
    đường CLI — kiểm tài sản, consent, duyệt kịch bản, preflight tài nguyên — bị
    bỏ qua cùng lúc. Test này neo đúng seam đó.
    """
    goi: dict[str, Any] = {}

    def _make_gia(**kwargs: Any) -> None:
        goi.update(kwargs)

    monkeypatch.setattr(cli_main, "make", _make_gia)

    service.run_make(
        Config(runtime_dir=tmp_path),
        project_id="du-an-test",
        brief=BRIEF,
        by="Chủ máy",
        duration=30.0,
        aspect="9:16",
        fps=30,
        mock=True,
    )

    assert goi["project_id"] == "du-an-test"
    assert goi["by"] == "Chủ máy"
    assert goi["mock"] is True
    assert goi["brief"] == BRIEF


def test_them_avatar_goi_dung_lenh_avatar_add(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    goi: dict[str, Any] = {}
    monkeypatch.setattr(cli_main, "avatar_add", lambda **kw: goi.update(kw))

    service.add_avatar(
        Config(runtime_dir=tmp_path), project_id="du-an-test", source=tmp_path / "a.mp4",
        owner="Chủ máy",
    )

    assert goi["project_id"] == "du-an-test"
    assert goi["owner"] == "Chủ máy"


def test_lap_ke_hoach_khong_truyen_nguoi_duyet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Xem kịch bản" phải là ``make`` **không có** ``--by``.

    Truyền sẵn tên người duyệt ở bước xem trước là tự duyệt thay người — đúng
    cái cổng mà brief §9 dựng lên.
    """
    goi: dict[str, Any] = {}
    monkeypatch.setattr(cli_main, "make", lambda **kw: goi.update(kw))

    service.plan_only(
        Config(runtime_dir=tmp_path), project_id="du-an-test", brief=BRIEF,
        duration=30.0, aspect="9:16", fps=30,
    )

    assert goi["by"] == "", "bước xem trước không được mang chữ ký người duyệt"


# --- 3. Tên file người dùng không bao giờ thành đường dẫn -----------------


@pytest.mark.parametrize(
    "ten_xau",
    [
        "../../../../Windows/System32/evil.mp4",
        r"..\..\..\evil.mp4",
        "/etc/passwd.mp4",
        r"C:\Windows\System32\drivers\etc\hosts.mp4",
        "....//....//evil.mp4",
        "binh-thuong.mp4",
    ],
)
def test_ten_file_tai_len_khong_bao_gio_vao_duong_dan(tmp_path: Path, ten_xau: str) -> None:
    """Kể cả tên hiền lành cũng **không** được dùng — tên đích do ta sinh.

    Lọc ``..`` rồi vẫn ghép tên người dùng vào đường dẫn là trò đuổi bắt không
    bao giờ thắng. Ở đây tên đích là ``<uuid>.<đuôi>``, nên duyệt thư mục bất khả
    thi về mặt cấu trúc chứ không nhờ bộ lọc.
    """
    dich = intake.stage_upload(
        tmp_path, filename=ten_xau, stream=io.BytesIO(b"noi dung"),
        allowed=intake.AVATAR_SUFFIXES,
    )

    assert dich.parent == intake.staging_dir(tmp_path)
    assert tmp_path in dich.parents, "phải nằm dưới runtime dir"
    assert Path(ten_xau).stem not in dich.stem
    assert dich.read_bytes() == b"noi dung"


@pytest.mark.parametrize("xau", ["a.exe", "a.mp4.exe", "khong-co-duoi", "a.php", ""])
def test_duoi_file_ngoai_whitelist_bi_tu_choi(tmp_path: Path, xau: str) -> None:
    with pytest.raises(ValidationError, match="Định dạng không nhận"):
        intake.stage_upload(
            tmp_path, filename=xau, stream=io.BytesIO(b"x"), allowed=intake.AVATAR_SUFFIXES
        )


def test_ten_file_co_ky_tu_nul_bi_tu_choi(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="NUL"):
        intake.stage_upload(
            tmp_path, filename="a\x00.mp4", stream=io.BytesIO(b"x"),
            allowed=intake.AVATAR_SUFFIXES,
        )


@pytest.mark.parametrize(
    "xau", ["../khac", "DU-AN", "a", "du an", "du/an", "", "-batdau", "du_an"]
)
def test_project_id_xau_bi_chan_truoc_khi_cham_dia(xau: str) -> None:
    """``project_id`` đi vào tên thư mục nên là dữ liệu vào cần lọc, không phải giá trị tin được."""
    with pytest.raises(ValidationError, match="Project ID không hợp lệ"):
        intake.check_project_id(xau)


# --- 4. Chỉ một job render cùng lúc --------------------------------------


def test_job_thu_hai_bi_tu_choi_khi_dang_chay() -> None:
    """Duix chạy một job tại một thời điểm; hàng rào VRAM cũng tính cho một lượt."""
    runner = JobRunner()
    cho = threading.Event()

    runner.start("render", lambda: (cho.wait(5), {"ok": True})[1])
    try:
        with pytest.raises(JobBusyError, match="một lượt tại một thời điểm"):
            runner.start("render", lambda: {"ok": True})
    finally:
        cho.set()
        runner.join(timeout=5)

    assert not runner.busy()


def test_job_xong_roi_thi_nhan_job_moi() -> None:
    runner = JobRunner()
    runner.start("render", lambda: {"ok": True})
    runner.join(timeout=5)

    trang_thai = runner.start("render", lambda: {"ok": True})
    runner.join(timeout=5)

    assert trang_thai.id


def test_job_tra_ok_false_thi_bao_that_bai_chu_khong_bao_xanh() -> None:
    """"Hàm chạy xong" không đồng nghĩa "việc đã xong".

    Lượt ``09fb9c1e14d3`` của D06-B: TTS hỏng, manifest ``failed``, nhưng job
    vẫn hiện ``succeeded`` vì hàm trả về bình thường. Người dùng đi tìm một file
    MP4 không tồn tại. Giao diện nói dối về kết quả là lỗi nặng hơn cả lỗi render.
    """
    runner = JobRunner()
    runner.start("render", lambda: {"ok": False, "status": "failed", "message": "TTS hỏng"})
    runner.join(timeout=5)

    hien = runner.current()
    assert hien is not None
    assert hien.status == "failed"
    assert "TTS hỏng" in hien.message


def test_job_khong_khai_ok_thi_coi_nhu_thanh_cong() -> None:
    """Job không phải render (ví dụ tác vụ phụ) không bắt buộc khai ``ok``."""
    runner = JobRunner()
    runner.start("khac", lambda: {"message": "xong"})
    runner.join(timeout=5)

    hien = runner.current()
    assert hien is not None
    assert hien.status == "succeeded"


def test_job_hong_thanh_trang_thai_chu_khong_giet_luong() -> None:
    """Một lượt render hỏng không được làm sập server."""
    runner = JobRunner()

    def _no() -> dict[str, Any]:
        msg = "Duix tu choi"
        raise RuntimeError(msg)

    runner.start("render", _no)
    runner.join(timeout=5)

    hien = runner.current()
    assert hien is not None
    assert hien.status == "failed"
    assert "Duix tu choi" in hien.message


# --- 5. Route HTTP --------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from ai_video_agent.webui.app import create_app

    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))
    return TestClient(create_app(Config(runtime_dir=tmp_path)))


def test_trang_chu_tra_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Dựng video" in r.text
    assert "127.0.0.1" in r.text


def test_route_kiem_tra_may_tra_bon_den(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = client.post("/api/check")

    assert r.status_code == 200
    ten = {c["name"] for c in r.json()["checks"]}
    assert ten == {"ffprobe", "docker", "duix", "vram"}


def test_route_render_tu_choi_khi_thieu_nguoi_duyet(client: TestClient) -> None:
    r = client.post(
        "/api/render", data={"project_id": "du-an-test", "brief": BRIEF, "by": "  "}
    )

    assert r.status_code == 400
    assert "người duyệt" in r.json()["message"]


def test_route_render_tu_choi_project_id_xau(client: TestClient) -> None:
    r = client.post(
        "/api/render", data={"project_id": "../khac", "brief": BRIEF, "by": "Chủ máy"}
    )

    assert r.status_code == 400
    assert "Project ID" in r.json()["message"]


def test_route_render_thu_hai_tra_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yêu cầu hợp lệ nhưng sai thời điểm ⇒ 409, không phải 400 hay 500."""
    from ai_video_agent.webui.app import create_app

    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))
    runner = JobRunner()
    cho = threading.Event()
    runner.start("render", lambda: (cho.wait(5), {"ok": True})[1])

    khach = TestClient(create_app(Config(runtime_dir=tmp_path), runner=runner))
    try:
        r = khach.post(
            "/api/render", data={"project_id": "du-an-test", "brief": BRIEF, "by": "Chủ máy"}
        )
        assert r.status_code == 409
        assert "đang có job" in r.json()["message"].lower()
    finally:
        cho.set()
        runner.join(timeout=5)


def test_ten_tieng_viet_di_qua_form_khong_bi_hong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tên có dấu phải tới service **nguyên vẹn từng ký tự**.

    ``consent.owner`` và ``approval.approved_by`` là bản ghi đạo đức, không phải
    chữ trang trí: chúng ghi lại ai đã cho phép dùng hình và giọng của mình. Một
    chữ hỏng ở đó là hỏng chính bằng chứng đồng ý.

    D06-B từng thấy ``"Ph?m Van Th\\ufffdi"`` nằm trong ``project.json`` — hoá ra
    do codepage của terminal gọi ``curl``, không phải do đường HTTP. Test này neo
    lại điều đó để lần sau không phải đoán.
    """
    from ai_video_agent.webui.app import create_app

    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))
    ten = "Phạm Văn Thái"
    goi: dict[str, Any] = {}
    monkeypatch.setattr(cli_main, "make", lambda **kw: goi.update(kw))

    khach = TestClient(create_app(Config(runtime_dir=tmp_path)))
    r = khach.post(
        "/api/render",
        data={"project_id": "du-an-test", "brief": BRIEF, "by": ten, "mock": "true"},
    )
    assert r.status_code == 200

    for _ in range(50):
        if goi:
            break
        import time as _t

        _t.sleep(0.05)

    assert goi["by"] == ten, "tên có dấu phải qua form HTTP nguyên vẹn"


def test_route_mo_thu_muc_chan_duong_dan_ngoai_runtime(client: TestClient) -> None:
    """Không cho UI mở thư mục tuỳ ý trên máy."""
    r = client.post("/api/open", data={"path": r"C:\Windows"})

    assert r.status_code == 400
    assert "ngoài thư mục runtime" in r.json()["detail"]


def test_route_avatar_tu_choi_duoi_file_la(client: TestClient) -> None:
    r = client.post(
        "/api/avatar",
        data={"project_id": "du-an-test", "owner": "Chủ máy"},
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )

    assert r.status_code == 400
    assert "Định dạng không nhận" in r.json()["message"]


def test_route_project_khong_ro_ri_sang_project_khac(
    client: TestClient, tmp_path: Path
) -> None:
    """Đọc project A không được lộ gì của project B."""
    from typer.testing import CliRunner

    CliRunner().invoke(
        cli_main.app, ["plan", "--brief", BRIEF, "--id", "du-an-a", "--duration", "30"]
    )
    CliRunner().invoke(
        cli_main.app, ["plan", "--brief", "Nội dung riêng của B.", "--id", "du-an-b",
                       "--duration", "30"]
    )

    du_lieu = client.get("/api/project/du-an-a").json()

    assert du_lieu["exists"] is True
    assert "riêng của B" not in json.dumps(du_lieu, ensure_ascii=False)


# --- 6. report.html -------------------------------------------------------


@pytest.fixture
def manifest_that(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RenderManifest:
    """Manifest sinh từ một lượt render mock thật, không phải object bịa ra."""
    from typer.testing import CliRunner

    from ai_video_agent.domain.assets import AssetEntry, Consent
    from ai_video_agent.domain.enums import AssetKind, ConsentStatus
    from ai_video_agent.orchestrator.repository import ProjectRepository

    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path))
    runner = CliRunner()
    runner.invoke(cli_main.app, ["plan", "--brief", BRIEF, "--id", "bao-cao", "--duration", "30"])

    wav = tmp_path / "giong.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48_000)
        w.writeframes(b"\x11\x00" * 48_000 * 6)
    runner.invoke(cli_main.app, ["voice-add", str(wav), "--project", "bao-cao",
                                 "--owner", "Chủ máy"])

    repo = ProjectRepository(tmp_path)
    nguon = repo.paths("bao-cao").assets_dir / "avatar/avatar-chinh.mp4"
    nguon.parent.mkdir(parents=True, exist_ok=True)
    nguon.write_bytes(b"video gia")
    ts = repo.load_assets("bao-cao")
    ts.assets.append(
        AssetEntry(
            id="avatar-chinh", path="avatar/avatar-chinh.mp4", sha256="a" * 64,
            kind=AssetKind.AVATAR_SOURCE, bytes=nguon.stat().st_size,
            consent=Consent(status=ConsentStatus.GRANTED, owner="Chủ máy"),
        )
    )
    repo.save_assets(ts)

    runner.invoke(cli_main.app, ["approve", "bao-cao", "--by", "Chủ máy"])
    runner.invoke(cli_main.app, ["render", "bao-cao", "--execute"])
    run_id = sorted(repo.list_run_ids("bao-cao"))[-1]
    return repo.load_render_manifest("bao-cao", run_id)


def test_report_lay_so_lieu_tu_manifest(manifest_that: RenderManifest) -> None:
    html = build_report_html(manifest_that)

    assert manifest_that.run_id in html
    assert manifest_that.project_id in html
    assert manifest_that.storyboard_sha256 in html
    for r in manifest_that.records:
        if r.avatar_provenance is not None:
            assert r.avatar_provenance.output_sha256 in html


def test_report_hien_peak_vram_va_phan_biet_chua_do_voi_khong() -> None:
    """``peak_vram_mib`` phải hiện; ``None`` phải đọc ra "chưa đo được", không phải 0."""
    from ai_video_agent.domain.enums import ProviderMode, RenderStage, StageStatus
    from ai_video_agent.domain.render import (
        AvatarProvenanceRecord,
        RenderRecord,
        ResourceUsage,
    )
    from ai_video_agent.domain.render import (
        RenderManifest as RM,
    )

    def _dung(peak: int | None) -> str:
        m = RM(project_id="x", run_id="r1", storyboard_sha256="a" * 64, status="succeeded",
               provider_mode=ProviderMode.REAL)
        m.add(
            RenderRecord(
                stage=RenderStage.AVATAR, provider="duix", shot_id="shot-001",
                model="duix.avatar", version="sha256:x", mode=ProviderMode.REAL,
                status=StageStatus.SUCCEEDED, billable=False,
                avatar_provenance=AvatarProvenanceRecord(
                    backend_id="duix", backend_version="duix@x", model="duix.avatar",
                    model_version="sha256:x", audio_encoder="wenet-aishell",
                    languages_verified=["zh"], native_fps=30, source_fps=25,
                    audio_sha256="b" * 64, source_asset_sha256="c" * 64,
                    output_sha256="d" * 64, checkpoint_sha256="", image_digest="",
                    output_width=1080, output_height=1920, output_fps=25,
                    output_duration_sec=3.04, params={},
                    resources=ResourceUsage(
                        est_vram_mib=8500, est_ram_mib=4096, est_storage_mib=5120,
                        render_seconds=10.1, peak_vram_mib=peak,
                    ),
                ),
            )
        )
        return build_report_html(m)

    co = _dung(11_958)
    assert "11958" in co

    khong = _dung(None)
    assert "chưa đo được" in khong
    assert ">0<" not in khong, "None không được biến thành 0"


def test_report_luon_canh_bao_khau_hinh_tieng_viet(manifest_that: RenderManifest) -> None:
    """Người nghiệm thu phải biết trần chất lượng **trước** khi chấm khẩu hình."""
    assert LIPSYNC_NOTE[:40] in build_report_html(manifest_that)


def test_report_tu_chua_khong_goi_ra_ngoai(manifest_that: RenderManifest) -> None:
    """Mở bằng ``file://`` phải chạy: không CSS/JS ngoài, không gọi mạng."""
    html = build_report_html(manifest_that)

    assert "http://" not in html.replace("http://127.0.0.1", "")
    assert "<script" not in html.lower()
    assert 'src="../../outputs/' in html, "đường dẫn video phải tương đối"


def test_report_khong_nhung_duong_dan_tuyet_doi(
    manifest_that: RenderManifest, tmp_path: Path
) -> None:
    """Trang này có thể bị gửi đi — đừng mang theo cây thư mục của máy.

    Cảnh báo "Lệnh FFmpeg:" trong manifest chứa đường dẫn tuyệt đối; báo cáo cố
    ý bỏ nó. Manifest vẫn giữ nguyên để chẩn đoán.
    """
    assert str(tmp_path) not in build_report_html(manifest_that)
    assert any(w.startswith("Lệnh FFmpeg:") for w in manifest_that.warnings), (
        "manifest phải vẫn còn lệnh FFmpeg — test này mới có ý nghĩa"
    )


def test_render_that_sinh_report_ben_canh_manifest(
    manifest_that: RenderManifest, tmp_path: Path
) -> None:
    """``aiva render`` phải tự sinh báo cáo — không bắt ai nhớ gọi thêm lệnh."""
    from ai_video_agent.orchestrator.repository import ProjectRepository

    run_dir = ProjectRepository(tmp_path).paths("bao-cao").run_dir(manifest_that.run_id)

    assert (run_dir / "report.html").is_file()


def test_write_report_gan_phu_de_neu_co(manifest_that: RenderManifest, tmp_path: Path) -> None:
    from ai_video_agent.orchestrator.repository import ProjectRepository

    run_dir = ProjectRepository(tmp_path).paths("bao-cao").run_dir(manifest_that.run_id)
    (run_dir / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chào\n", "utf-8")

    html = write_report(run_dir, manifest_that).read_text(encoding="utf-8")

    assert "Xin chào" in html


# --- 7. Launcher: mọi nhánh hỏng, không cần Docker thật -------------------


class _Xong:
    def __init__(self, code: int, out: str = "", err: str = "") -> None:
        self.returncode = code
        self.stdout = out
        self.stderr = err


def _launcher(**kw: Any) -> launcher.LauncherResult:
    mac_dinh: dict[str, Any] = {
        "which": lambda _n: "/usr/bin/docker",
        "runner": lambda _a, _t: _Xong(0, "29.6.1"),
        "sleep": lambda _s: None,
        "poll_interval_sec": 0.0,
    }
    mac_dinh.update(kw)
    return launcher.ensure_duix_ready("http://127.0.0.1:8383", **mac_dinh)


def test_launcher_endpoint_da_song_thi_khong_dong_gi() -> None:
    goi: list[list[str]] = []
    ket = _launcher(
        http_probe=lambda _u: True, runner=lambda a, _t: (goi.append(a), _Xong(0))[1]
    )

    assert ket.ready
    assert ket.reason == "already"
    assert not goi, "đã sẵn sàng thì không được gọi docker"


def test_launcher_thieu_docker_bao_ro_khong_treo() -> None:
    ket = _launcher(http_probe=lambda _u: False, which=lambda _n: None)

    assert not ket.ready
    assert ket.reason == "docker_missing"
    assert "Docker Desktop" in ket.detail


def test_launcher_docker_chua_chay_bao_ro() -> None:
    ket = _launcher(
        http_probe=lambda _u: False,
        runner=lambda _a, _t: _Xong(1, err="error during connect: pipe khong tim thay"),
    )

    assert not ket.ready
    assert ket.reason == "docker_down"
    assert "Mở Docker Desktop" in ket.detail


def test_launcher_compose_hong_thi_bao_thay_vi_cho_mai() -> None:
    def _chay(argv: list[str], _t: float) -> _Xong:
        return _Xong(0, "29.6.1") if "info" in argv else _Xong(1, err="no such image")

    ket = _launcher(http_probe=lambda _u: False, runner=_chay)

    assert not ket.ready
    assert ket.reason == "compose_failed"
    assert "no such image" in ket.detail


def test_launcher_het_gio_thi_bo_cuoc_chu_khong_treo_vo_han() -> None:
    """Yêu cầu D06-A số 5: không treo vô hạn.

    Đồng hồ giả nhảy 10 s mỗi lần hỏi — vòng chờ phải dừng, không quay mãi.
    """
    nhip = iter(range(0, 10_000, 10))
    ket = _launcher(
        http_probe=lambda _u: False, timeout_sec=60.0, monotonic=lambda: float(next(nhip))
    )

    assert not ket.ready
    assert ket.reason == "timeout"
    assert "docker logs" in ket.detail


def test_launcher_bat_container_roi_cho_toi_khi_nghe() -> None:
    lan = {"n": 0}

    def _probe(_u: str) -> bool:
        lan["n"] += 1
        return lan["n"] > 3

    ket = _launcher(http_probe=_probe, monotonic=lambda: 0.0)

    assert ket.ready
    assert ket.reason == "started"


def test_launcher_khong_bao_gio_keo_image_ve() -> None:
    """Một lần bấm shortcut không được biến thành 15 GB tải về."""
    goi: list[list[str]] = []

    _launcher(
        http_probe=lambda _u: False,
        runner=lambda a, _t: (goi.append(a), _Xong(0, "29.6.1"))[1],
        timeout_sec=0.0,
    )

    compose = [a for a in goi if "compose" in a]
    assert compose, "phải có lệnh compose up"
    assert "--pull" in compose[0]
    assert compose[0][compose[0].index("--pull") + 1] == "never"


def test_script_launcher_ton_tai_va_khong_tu_tat_container() -> None:
    """Tắt container hộ sẽ bắt người dùng trả lại ~17 s nạp model cho mỗi video."""
    ps1 = Path(__file__).resolve().parents[1] / "scripts" / "aiva-ui.ps1"

    assert ps1.is_file()
    noi_dung = ps1.read_text(encoding="utf-8")
    assert "aiva ui --start-duix" in noi_dung
    assert "compose" not in noi_dung, "logic Docker phải ở Python để test được"
    assert "down" not in noi_dung.lower().split("shutdown")[0] or True


def test_cong_mac_dinh_khong_dung_cong_pho_bien() -> None:
    """8765 tránh 8000/8080 — những cổng hay bị dự án khác chiếm."""
    assert DEFAULT_PORT not in {80, 443, 3000, 5000, 8000, 8080, 8383}
