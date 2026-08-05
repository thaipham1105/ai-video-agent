"""Kiểm tra WAV: tồn tại, thời lượng, sample rate, clipping (brief §D02.5).

Các file thử được dựng bằng ``wave`` của thư viện chuẩn nên không cần model,
không cần numpy, và chạy được ở mọi gate.
"""

from __future__ import annotations

import importlib.util
import math
import wave
from array import array
from pathlib import Path

import pytest

from ai_video_agent.composer.audio import (
    CLIPPING_THRESHOLD,
    READABLE_SUFFIXES,
    convert_to_wav,
    inspect_wav,
)
from ai_video_agent.errors import ValidationError
from ai_video_agent.providers._placeholder import write_silent_wav


def _write_tone(
    path: Path,
    *,
    duration_sec: float = 1.0,
    sample_rate: int = 48_000,
    amplitude: float = 0.5,
    channels: int = 1,
    freq: float = 440.0,
) -> Path:
    """Ghi một WAV 16-bit chứa sóng sin, biên độ 0..1."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(duration_sec * sample_rate)
    peak = int(amplitude * 32767)
    samples = array("h")
    for i in range(frames):
        value = int(peak * math.sin(2 * math.pi * freq * i / sample_rate))
        for _ in range(channels):
            samples.append(value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return path


def _write_square_at_full_scale(path: Path, *, duration_sec: float = 0.5) -> Path:
    """WAV bị kẹp trần hoàn toàn — mọi mẫu đều ở biên."""
    sample_rate = 48_000
    frames = int(duration_sec * sample_rate)
    samples = array("h", (32767 if (i // 50) % 2 == 0 else -32767 for i in range(frames)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return path


# --- file tồn tại -------------------------------------------------------------


def test_bao_loi_khi_khong_co_file(tmp_path: Path) -> None:
    report = inspect_wav(tmp_path / "khong-co.wav")

    assert not report.exists
    assert not report.ok
    assert report.problems


def test_bao_loi_khi_file_khong_phai_wav(tmp_path: Path) -> None:
    fake = tmp_path / "gia.wav"
    fake.write_bytes(b"day khong phai WAV")

    report = inspect_wav(fake)

    assert report.exists
    assert not report.ok
    assert any("Không đọc được WAV" in p for p in report.problems)


# --- thời lượng ---------------------------------------------------------------


@pytest.mark.parametrize("duration", [0.5, 1.0, 3.25])
def test_do_dung_thoi_luong(tmp_path: Path, duration: float) -> None:
    path = _write_tone(tmp_path / "a.wav", duration_sec=duration)

    report = inspect_wav(path)

    assert report.duration_sec == pytest.approx(duration, abs=0.01)
    assert report.ok


def test_bao_loi_khi_thoi_luong_lech_qua_nguong(tmp_path: Path) -> None:
    path = _write_tone(tmp_path / "a.wav", duration_sec=1.0)

    report = inspect_wav(path, expected_duration_sec=5.0, duration_tolerance_sec=0.5)

    assert not report.ok
    assert any("Thời lượng" in p for p in report.problems)


def test_thoi_luong_trong_nguong_thi_dat(tmp_path: Path) -> None:
    path = _write_tone(tmp_path / "a.wav", duration_sec=3.0)

    report = inspect_wav(path, expected_duration_sec=3.4, duration_tolerance_sec=0.75)

    assert report.ok


# --- sample rate --------------------------------------------------------------


def test_do_dung_sample_rate_va_kenh(tmp_path: Path) -> None:
    path = _write_tone(tmp_path / "a.wav", sample_rate=24_000, channels=2)

    report = inspect_wav(path)

    assert report.sample_rate == 24_000
    assert report.channels == 2
    assert report.sample_width_bits == 16


def test_bao_loi_khi_sample_rate_khac_ky_vong(tmp_path: Path) -> None:
    path = _write_tone(tmp_path / "a.wav", sample_rate=24_000)

    report = inspect_wav(path, expected_sample_rate=48_000)

    assert not report.ok
    assert any("Sample rate" in p for p in report.problems)


# --- clipping -----------------------------------------------------------------


def test_am_thanh_binh_thuong_khong_bi_bao_clipping(tmp_path: Path) -> None:
    path = _write_tone(tmp_path / "a.wav", amplitude=0.5)

    report = inspect_wav(path)

    assert report.clipping_ratio == 0.0
    assert report.peak == pytest.approx(0.5, abs=0.01)
    assert report.ok


def test_phat_hien_clipping(tmp_path: Path) -> None:
    path = _write_square_at_full_scale(tmp_path / "a.wav")

    report = inspect_wav(path)

    assert report.clipping_ratio > 0.9
    assert report.peak == pytest.approx(1.0, abs=0.001)
    assert not report.ok
    assert any("Clipping" in p for p in report.problems)


def test_nguong_clipping_noi_long_duoc(tmp_path: Path) -> None:
    path = _write_square_at_full_scale(tmp_path / "a.wav")

    report = inspect_wav(path, max_clipping_ratio=1.0)

    assert not any("Clipping" in p for p in report.problems)


def test_bien_do_ngay_duoi_nguong_khong_tinh_la_clipping(tmp_path: Path) -> None:
    path = _write_tone(tmp_path / "a.wav", amplitude=CLIPPING_THRESHOLD - 0.02)

    report = inspect_wav(path)

    assert report.clipped_samples == 0


# --- im lặng ------------------------------------------------------------------


def test_phat_hien_file_cam(tmp_path: Path) -> None:
    """WAV im lặng là dấu hiệu TTS chạy nhưng không ra tiếng."""
    path = tmp_path / "cam.wav"
    write_silent_wav(path, duration_sec=1.0, sample_rate=48_000)

    report = inspect_wav(path)

    assert report.is_silent
    assert not report.ok
    assert any("câm" in p for p in report.problems)


def test_cho_phep_im_lang_khi_duoc_yeu_cau(tmp_path: Path) -> None:
    """Output của mock là im lặng có chủ đích, không phải lỗi."""
    path = tmp_path / "cam.wav"
    write_silent_wav(path, duration_sec=1.0, sample_rate=48_000)

    report = inspect_wav(path, allow_silence=True)

    assert report.ok
    assert report.duration_sec == pytest.approx(1.0, abs=0.01)


# --- chuyển đổi định dạng -----------------------------------------------------


#: Chuyển đổi cần extra 'tts'; bộ test lõi phải chạy được khi chưa cài nó (ADR-0004).
needs_soundfile = pytest.mark.skipif(
    importlib.util.find_spec("soundfile") is None,
    reason="cần extra 'tts' (uv sync --extra tts)",
)


@needs_soundfile
def test_chuyen_stereo_thanh_mono_wav(tmp_path: Path) -> None:
    """Nhập vào định dạng nào cũng phải ra WAV mono 16-bit đọc được bằng thư viện chuẩn."""
    src = _write_tone(tmp_path / "stereo.wav", channels=2, sample_rate=44_100)

    report = convert_to_wav(src, tmp_path / "out.wav")

    assert report.ok
    assert report.channels == 1
    assert report.sample_width_bits == 16
    assert report.sample_rate == 44_100, "giữ nguyên sample rate, chỉ hạ mono"


@needs_soundfile
def test_chuyen_flac_thanh_wav(tmp_path: Path) -> None:
    """FLAC thật (do soundfile ghi ra) phải đọc được mà không cần FFmpeg."""
    import soundfile as sf

    src = tmp_path / "a.flac"
    frames = 48_000 * 2
    sf.write(str(src), [0.4 * math.sin(i / 30) for i in range(frames)], 48_000)

    report = convert_to_wav(src, tmp_path / "out.wav")

    assert report.ok
    assert report.duration_sec == pytest.approx(2.0, abs=0.02)


@needs_soundfile
def test_chuyen_doi_ghi_de_duoc_va_bat_duoc_file_cam(tmp_path: Path) -> None:
    """Mẫu giọng câm phải lộ ra ngay ở bước nhập, không đợi tới lúc render."""
    src = tmp_path / "cam.wav"
    write_silent_wav(src, duration_sec=1.0, sample_rate=48_000)

    report = convert_to_wav(src, tmp_path / "out.wav")

    assert report.is_silent
    assert not report.ok


def test_tu_choi_dinh_dang_can_ffmpeg(tmp_path: Path) -> None:
    """.m4a cần FFmpeg — thuộc Gate D04, phải báo rõ thay vì lỗi khó hiểu."""
    fake = tmp_path / "ghi-am.m4a"
    fake.write_bytes(b"\x00" * 64)

    with pytest.raises(ValidationError, match="FFmpeg"):
        convert_to_wav(fake, tmp_path / "out.wav")


def test_tu_choi_file_nguon_khong_ton_tai(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        convert_to_wav(tmp_path / "khong-co.mp3", tmp_path / "out.wav")


def test_m4a_khong_nam_trong_danh_sach_doc_duoc() -> None:
    assert ".m4a" not in READABLE_SUFFIXES
    assert ".mp3" in READABLE_SUFFIXES
    assert ".wav" in READABLE_SUFFIXES


# --- tóm tắt ------------------------------------------------------------------


def test_summary_doc_duoc(tmp_path: Path) -> None:
    path = _write_tone(tmp_path / "a.wav", duration_sec=2.0, amplitude=0.6)

    text = inspect_wav(path).summary()

    assert "2.00s" in text
    assert "48000 Hz" in text
    assert "clipping" in text
