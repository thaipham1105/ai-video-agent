"""Composer: phụ đề SRT và trình dựng lệnh FFmpeg."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from ai_video_agent.composer.ffmpeg import (
    ComposeSpec,
    DrawTextSpec,
    build_compose_command,
    build_concat_file,
    escape_filter_path,
    escape_filter_value,
)
from ai_video_agent.composer.runner import FfmpegComposer, MockComposer
from ai_video_agent.composer.subtitles import (
    build_cues,
    format_timestamp,
    render_srt,
    split_for_cues,
    wrap_text,
    write_srt,
)
from ai_video_agent.errors import GateNotReachedError

# --- phụ đề -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (61.25, "00:01:01,250"),
        (3661.007, "01:01:01,007"),
        (-5.0, "00:00:00,000"),
    ],
)
def test_dinh_dang_moc_thoi_gian_srt(seconds: float, expected: str) -> None:
    assert format_timestamp(seconds) == expected


def test_ngat_dong_khong_cat_giua_tu() -> None:
    wrapped = wrap_text("Đất thổ cư mặt tiền đường nhựa tại thành phố Biên Hoà tỉnh Đồng Nai")
    for line in wrapped.split("\n"):
        assert len(line) <= 42
    assert "\n" in wrapped
    for word in wrapped.split():
        assert word in "Đất thổ cư mặt tiền đường nhựa tại thành phố Biên Hoà tỉnh Đồng Nai"


def test_thoai_dai_duoc_chia_thanh_nhieu_cue() -> None:
    dai = " ".join(["Một câu rất dài cần chia nhỏ để đọc kịp"] * 6)
    assert len(split_for_cues(dai)) > 1


def test_moc_thoi_gian_cue_tang_dan_va_khong_chong_nhau() -> None:
    cues = build_cues([("Câu một ngắn.", 3.0), ("Câu hai dài hơn một chút.", 4.0)])

    assert cues
    for cue in cues:
        assert cue.end_sec > cue.start_sec
    for truoc, sau in pairwise(cues):
        assert truoc.end_sec <= sau.start_sec


def test_cue_bam_theo_thoi_luong_audio_that() -> None:
    """Phụ đề dùng thời lượng WAV thật, không dùng con số dự kiến."""
    cues = build_cues([("Xin chào.", 2.0), ("Tạm biệt.", 3.0)])
    assert cues[-1].end_sec <= 5.0


def test_srt_dung_utf8_va_giu_dau_tieng_viet(tmp_path: Path) -> None:
    cues = build_cues([("Sổ hồng riêng, giá 1,2 tỷ.", 4.0)])
    path = write_srt(tmp_path / "subtitles.srt", cues)

    content = path.read_text(encoding="utf-8")
    assert "Sổ hồng riêng" in content
    assert "-->" in content
    assert content.startswith("1\n")


def test_srt_rong_khi_khong_co_cue() -> None:
    assert render_srt([]) == ""


# --- escape -------------------------------------------------------------------


def test_escape_gia_tri_filter() -> None:
    assert escape_filter_value("Giá: 1,2 tỷ") == r"Giá\: 1\,2 tỷ"
    assert escape_filter_value("O'Brien") == r"O\'Brien"


def test_escape_duong_dan_windows() -> None:
    """``F:\\a\\b.srt`` phải thành ``F\\:/a/b.srt`` mới không vỡ filtergraph."""
    assert escape_filter_path(r"F:\du-lieu\subtitles.srt") == r"F\:/du-lieu/subtitles.srt"


# --- lệnh FFmpeg --------------------------------------------------------------


def _spec(tmp_path: Path, **kwargs) -> ComposeSpec:
    defaults = {
        "concat_file": tmp_path / "concat.txt",
        "output": tmp_path / "out.mp4",
        "width": 1080,
        "height": 1920,
        "fps": 30,
    }
    return ComposeSpec(**{**defaults, **kwargs})


def test_concat_file_dung_dau_gach_xuoi(tmp_path: Path) -> None:
    content = build_concat_file([Path(r"F:\a\shot1.mp4"), Path(r"F:\a\shot2.mp4")])
    assert "\\" not in content
    assert content.count("file '") == 2


def test_lenh_xuat_ban_tuong_thich_mang_xa_hoi(tmp_path: Path) -> None:
    """Brief §D04.4: H.264/AAC, yuv420p, faststart cho Facebook/TikTok/Zalo."""
    argv = build_compose_command(_spec(tmp_path))

    assert argv[0] == "ffmpeg"
    for flag in ("libx264", "yuv420p", "aac", "+faststart"):
        assert flag in argv
    assert argv[-1] == str(tmp_path / "out.mp4")


def test_khung_hinh_doc_1080x1920(tmp_path: Path) -> None:
    argv = build_compose_command(_spec(tmp_path))
    graph = argv[argv.index("-filter_complex") + 1]
    assert "scale=1080:1920" in graph
    assert "pad=1080:1920" in graph


def test_phu_de_duoc_nap_vao_filtergraph(tmp_path: Path) -> None:
    argv = build_compose_command(_spec(tmp_path, subtitles=tmp_path / "s.srt"))
    graph = argv[argv.index("-filter_complex") + 1]
    assert "subtitles=" in graph
    assert "force_style=" in graph


def test_logo_duoc_overlay_thanh_input_rieng(tmp_path: Path) -> None:
    argv = build_compose_command(_spec(tmp_path, logo=tmp_path / "logo.png"))
    graph = argv[argv.index("-filter_complex") + 1]
    assert "overlay=" in graph
    assert argv.count("-i") == 2


def test_chu_chinh_xac_thanh_drawtext_co_khung_thoi_gian(tmp_path: Path) -> None:
    """Số điện thoại phải do FFmpeg vẽ, đúng ký tự, đúng khoảng thời gian."""
    argv = build_compose_command(
        _spec(
            tmp_path,
            draw_texts=[DrawTextSpec(text="0909123456", start_sec=2.0, end_sec=6.0)],
        )
    )
    graph = argv[argv.index("-filter_complex") + 1]

    assert "drawtext=" in graph
    assert "0909123456" in graph
    assert "between(t,2.000,6.000)" in graph


def test_drawtext_escape_ky_tu_dac_biet() -> None:
    filter_str = DrawTextSpec(text="Giá: 1,2 tỷ").to_filter()
    assert r"\:" in filter_str
    assert r"\," in filter_str


# --- runner -------------------------------------------------------------------


def test_mock_composer_dung_lenh_nhung_khong_chay(tmp_path: Path) -> None:
    outcome = MockComposer().compose(_spec(tmp_path))

    assert outcome.executed is False
    assert outcome.is_placeholder is True
    assert outcome.command[0] == "ffmpeg"
    assert outcome.output.is_file()


def test_composer_that_bi_chan_khi_gate_chua_toi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hạ gate về D03 thì FFmpeg thật phải từ chối chạy."""
    monkeypatch.setattr("ai_video_agent.CURRENT_GATE", "D03")
    with pytest.raises(GateNotReachedError) as info:
        FfmpegComposer().compose(_spec(tmp_path))
    assert info.value.gate == "D04"


def test_composer_that_tu_choi_ghi_de_file_doi_chung(tmp_path: Path) -> None:
    """Hàng rào bảo vệ golden áp cho cả bước ghép, không riêng TTS."""
    from ai_video_agent.errors import ConfigError

    bao_ve = tmp_path / "giu-lai" / "golden.mp4"
    with pytest.raises(ConfigError, match="đối chứng"):
        FfmpegComposer().compose(_spec(tmp_path, output=bao_ve))


def test_composer_that_bao_loi_ro_khi_thieu_ffmpeg(tmp_path: Path) -> None:
    from ai_video_agent.errors import ConfigError

    with pytest.raises(ConfigError, match="winget"):
        FfmpegComposer(ffmpeg_bin="ffmpeg-khong-ton-tai-tren-may").compose(_spec(tmp_path))
