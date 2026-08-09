"""D05-C — QC tự động và hiệu chuẩn detector.

Fixture được sinh **hoàn toàn local bằng FFmpeg**, không gọi API nào.
Clip D05-B thật được dùng làm *golden positive* khi có mặt.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ai_video_agent.qc.broll import (
    GOLDEN_POSITIVE,
    PROVISIONAL_SCENE_THRESHOLD,
    check_duration,
    check_resolution,
    check_scene_cut,
    check_source_fps,
    detect_scene_cuts,
    run_qc,
)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    not FFMPEG or not FFPROBE, reason="cần ffmpeg/ffprobe trên PATH"
)

D05B_CLIP = Path(
    r"F:\AI-VIDEO-AGENT-RUNTIME\d05-discovery\outputs\d05b_broll_9x16_noaudio.mp4"
)


def _ff(args: list[str]) -> None:
    assert FFMPEG
    subprocess.run([FFMPEG, "-v", "error", *args], check=True)  # noqa: S603


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Sinh corpus hiệu chuẩn local — không cắt, tĩnh, chậm, đóng băng, có cắt."""
    if not FFMPEG:
        pytest.skip("cần ffmpeg")
    out = tmp_path_factory.mktemp("qc_fixtures")

    # chuyển động bình thường, liên tục, không cắt
    smooth = out / "smooth.mp4"
    _ff(["-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24:duration=4",
         "-vf", "format=yuv420p", "-y", str(smooth)])

    # camera gần như đứng yên
    static = out / "static.mp4"
    _ff(["-f", "lavfi", "-i", "color=c=slategray:size=360x640:rate=24:duration=4",
         "-vf", "noise=alls=2:allf=t,format=yuv420p", "-y", str(static)])

    # chuyển động rất chậm
    slow = out / "slow.mp4"
    _ff(["-f", "lavfi", "-i", "gradients=size=360x640:rate=24:duration=4:speed=0.01",
         "-vf", "format=yuv420p", "-y", str(slow)])

    # đóng băng hoàn toàn: một khung lặp lại
    freeze = out / "freeze.mp4"
    _ff(["-f", "lavfi", "-i", "color=c=darkgreen:size=360x640:rate=24:duration=4",
         "-vf", "format=yuv420p", "-y", str(freeze)])

    # cắt cứng tổng hợp: hai nguồn khác hẳn nhau nối lại
    a, b, hardcut = out / "a.mp4", out / "b.mp4", out / "hardcut.mp4"
    _ff(["-f", "lavfi", "-i", "color=c=navy:size=360x640:rate=24:duration=2",
         "-vf", "format=yuv420p", "-y", str(a)])
    _ff(["-f", "lavfi", "-i", "color=c=orange:size=360x640:rate=24:duration=2",
         "-vf", "format=yuv420p", "-y", str(b)])
    lst = out / "concat.txt"
    lst.write_text(f"file '{a.as_posix()}'\nfile '{b.as_posix()}'\n", encoding="utf-8")
    _ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-y", str(hardcut)])

    return {
        "smooth": smooth, "static": static, "slow": slow,
        "freeze": freeze, "hardcut": hardcut,
    }


# --- 14. D05-B phải bị bắt tại ~3,25 giây ---------------------------------


@needs_ffmpeg
@pytest.mark.skipif(not D05B_CLIP.is_file(), reason="chưa có clip D05-B trên máy")
def test_golden_positive_d05b_bi_bat_tai_3_25_giay() -> None:
    assert FFMPEG
    cuts = detect_scene_cuts(FFMPEG, D05B_CLIP, PROVISIONAL_SCENE_THRESHOLD)
    assert len(cuts) == 1, f"chờ đúng 1 điểm cắt, thấy {cuts}"
    cut = cuts[0]
    assert abs(cut["pts_time"] - 3.25) < 0.05
    assert cut["scene_score"] > 0.30


@needs_ffmpeg
@pytest.mark.skipif(not D05B_CLIP.is_file(), reason="chưa có clip D05-B trên máy")
def test_d05b_chi_warn_khi_nguong_chua_hieu_chuan() -> None:
    assert FFMPEG
    result = check_scene_cut(FFMPEG, D05B_CLIP, calibrated=False)
    assert result.status == "WARN"
    assert "CHƯA hiệu chuẩn" in result.detail


@needs_ffmpeg
@pytest.mark.skipif(not D05B_CLIP.is_file(), reason="chưa có clip D05-B trên máy")
def test_d05b_bi_tu_choi_khi_nguong_da_hieu_chuan() -> None:
    assert FFMPEG
    result = check_scene_cut(FFMPEG, D05B_CLIP, calibrated=True)
    assert result.status == "FAIL"


def test_hang_so_golden_positive_khop_so_da_do() -> None:
    assert GOLDEN_POSITIVE["pts_time"] == 3.25
    assert GOLDEN_POSITIVE["frame"] == 78
    assert GOLDEN_POSITIVE["total_frames"] == 120


@needs_ffmpeg
def test_cat_cung_tong_hop_bi_bat(fixtures: dict[str, Path]) -> None:
    assert FFMPEG
    cuts = detect_scene_cuts(FFMPEG, fixtures["hardcut"], PROVISIONAL_SCENE_THRESHOLD)
    assert cuts, "cắt cứng tổng hợp phải bị bắt"


# --- 15. Không kết luận sai trên clip không cắt / tĩnh / chậm -------------


@needs_ffmpeg
@pytest.mark.parametrize("name", ["smooth", "static", "slow", "freeze"])
def test_khong_bao_nham_cat_canh(fixtures: dict[str, Path], name: str) -> None:
    assert FFMPEG
    cuts = detect_scene_cuts(FFMPEG, fixtures[name], PROVISIONAL_SCENE_THRESHOLD)
    assert not cuts, f"{name} không có cắt cảnh nhưng detector báo {cuts}"


@needs_ffmpeg
@pytest.mark.parametrize("name", ["static", "slow", "freeze"])
def test_khung_gan_trung_chi_la_bang_chung_khong_phai_ket_luan(
    fixtures: dict[str, Path], name: str
) -> None:
    """Cảnh tĩnh và chuyển động chậm tạo khung gần trùng mà KHÔNG có lỗi nào."""
    assert FFMPEG and FFPROBE
    report = run_qc(
        clip=fixtures[name], ffmpeg=FFMPEG, ffprobe=FFPROBE,
        want_width=360, want_height=640, want_fps=24, want_duration_sec=4.0,
    )
    freeze = next(c for c in report.checks if c.check_id == "freeze_evidence")
    assert freeze.status != "FAIL"
    assert report.verdict == "PASS"


# --- Các phép kiểm còn lại ------------------------------------------------


@needs_ffmpeg
def test_bat_sai_do_phan_giai(fixtures: dict[str, Path]) -> None:
    assert FFPROBE
    assert check_resolution(FFPROBE, fixtures["smooth"], 1080, 1920).status == "FAIL"
    assert check_resolution(FFPROBE, fixtures["smooth"], 360, 640).status == "PASS"


@needs_ffmpeg
def test_bat_sai_fps_nguon(fixtures: dict[str, Path]) -> None:
    """Veo cố định 24 fps — khác đi là sai."""
    assert FFPROBE
    assert check_source_fps(FFPROBE, fixtures["smooth"], 30).status == "FAIL"
    assert check_source_fps(FFPROBE, fixtures["smooth"], 24).status == "PASS"


@needs_ffmpeg
def test_bat_sai_thoi_luong(fixtures: dict[str, Path]) -> None:
    assert FFPROBE
    assert check_duration(FFPROBE, fixtures["smooth"], 8.0).status == "FAIL"
    assert check_duration(FFPROBE, fixtures["smooth"], 4.0).status == "PASS"


@needs_ffmpeg
def test_bat_file_hong(tmp_path: Path) -> None:
    assert FFMPEG and FFPROBE
    broken = tmp_path / "hong.mp4"
    broken.write_bytes(b"khong phai video")
    report = run_qc(
        clip=broken, ffmpeg=FFMPEG, ffprobe=FFPROBE,
        want_width=360, want_height=640, want_fps=24, want_duration_sec=4.0,
    )
    assert report.verdict == "FAIL"


@needs_ffmpeg
def test_qc_khong_bao_gio_tu_cap_human_approval(fixtures: dict[str, Path]) -> None:
    assert FFMPEG and FFPROBE
    report = run_qc(
        clip=fixtures["smooth"], ffmpeg=FFMPEG, ffprobe=FFPROBE,
        want_width=360, want_height=640, want_fps=24, want_duration_sec=4.0,
    )
    assert report.verdict == "PASS"
    assert report.human_approval is None
    assert any("chỉ có quyền TỪ CHỐI" in n for n in report.notes)
