"""Kiểm tra và chuyển đổi file audio.

:func:`inspect_wav` kiểm tra bốn mục nghiệm thu của brief §D02.5 (tồn tại, thời
lượng, sample rate, clipping) và cố ý **chỉ dùng thư viện chuẩn** (``wave`` +
``array``), nên đường đi mock không phải cài ``numpy`` hay ``soundfile``.

:func:`convert_to_wav` cần ``soundfile`` (có trong extra ``tts``) và vì thế
import nó **bên trong hàm**, giữ cho module này vẫn nhẹ khi chỉ import.
"""

from __future__ import annotations

import sys
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_agent.errors import ConfigError, ValidationError

#: Biên độ (0..1) coi là chạm trần. 16-bit full scale = 32767.
CLIPPING_THRESHOLD = 0.99
#: Tỷ lệ mẫu chạm trần tối đa còn chấp nhận được (0,1%).
MAX_CLIPPING_RATIO = 0.001
#: Dưới ngưỡng này coi như file câm — dấu hiệu TTS chạy nhưng không ra tiếng.
SILENCE_RMS_THRESHOLD = 1e-4
#: Sai số thời lượng mặc định khi so với kỳ vọng.
DURATION_TOLERANCE_SEC = 0.75

_READ_BLOCK_FRAMES = 1 << 16

#: Đuôi file libsndfile đọc được — **không cần FFmpeg**.
#: Cố ý KHÔNG có ``.m4a``/``.aac``: đó là container MPEG-4, libsndfile không đọc,
#: và FFmpeg thì thuộc Gate D04.
READABLE_SUFFIXES = frozenset(
    {
        ".wav",
        ".wave",
        ".flac",
        ".ogg",
        ".oga",
        ".aiff",
        ".aif",
        ".aifc",
        ".caf",
        ".w64",
        ".au",
        ".snd",
        ".mp3",
        ".rf64",
    }
)


@dataclass(frozen=True)
class WavReport:
    """Kết quả soi một file WAV."""

    path: Path
    exists: bool
    size_bytes: int = 0
    duration_sec: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    sample_width_bits: int = 0
    frames: int = 0
    peak: float = 0.0
    rms: float = 0.0
    clipped_samples: int = 0
    clipping_ratio: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exists and not self.problems

    @property
    def is_silent(self) -> bool:
        return self.rms < SILENCE_RMS_THRESHOLD

    def summary(self) -> str:
        if not self.exists:
            return f"{self.path.name}: KHÔNG TỒN TẠI"
        return (
            f"{self.path.name}: {self.duration_sec:.2f}s @ {self.sample_rate} Hz, "
            f"{self.channels}ch/{self.sample_width_bits}-bit, "
            f"peak {self.peak:.3f}, RMS {self.rms:.4f}, "
            f"clipping {self.clipping_ratio * 100:.3f}%"
        )


def _peak_and_rms(
    handle: wave.Wave_read, width: int, frames: int, channels: int
) -> tuple[float, float, int]:
    """Quét toàn file theo khối, trả về (peak, rms, số mẫu chạm trần) đã chuẩn hoá 0..1."""
    # 'i' luôn là 4 byte, khác 'l' (8 byte trên Linux 64-bit).
    type_code = {1: "B", 2: "h", 4: "i"}[width]
    full_scale = float(2 ** (width * 8 - 1))
    limit = CLIPPING_THRESHOLD * full_scale

    peak = 0.0
    square_sum = 0.0
    total = 0
    clipped = 0

    remaining = frames
    while remaining > 0:
        take = min(remaining, _READ_BLOCK_FRAMES)
        raw = handle.readframes(take)
        if not raw:
            break
        samples = array(type_code)
        samples.frombytes(raw[: len(raw) - len(raw) % samples.itemsize])
        if sys.byteorder == "big":
            samples.byteswap()  # WAV luôn little-endian
        if width == 1:
            # WAV 8-bit là *unsigned*: 0..255 với điểm giữa là 128.
            samples = array("h", (value - 128 for value in samples))
        for value in samples:
            magnitude = abs(value)
            if magnitude > peak:
                peak = float(magnitude)
            square_sum += float(value) * float(value)
            if magnitude >= limit:
                clipped += 1
        total += len(samples)
        remaining -= take

    if total == 0:
        return 0.0, 0.0, 0
    rms = (square_sum / total) ** 0.5
    _ = channels  # kênh không đổi cách tính peak/RMS, giữ tham số cho rõ ý
    return peak / full_scale, rms / full_scale, clipped


def convert_to_wav(src: Path, dest: Path, *, mono: bool = True) -> WavReport:
    """Chuyển bất kỳ định dạng nào libsndfile đọc được sang WAV PCM 16-bit.

    Dùng khi người dùng đưa vào mẫu giọng ``.mp3``/``.flac``/… Việc chuyển đổi
    diễn ra **một lần lúc nhập**, sau đó cả hệ thống chỉ làm việc với WAV — nhờ
    vậy :func:`inspect_wav` (thuần thư viện chuẩn) luôn đọc được.

    Sample rate được giữ nguyên; chỉ hạ về mono và chuẩn hoá về PCM 16-bit.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.is_file():
        msg = f"Không có file nguồn: {src}"
        raise ValidationError(msg)

    # Kiểm tra đuôi TRƯỚC khi cần soundfile: định dạng không hỗ trợ thì báo lỗi
    # rõ ràng ngay, kể cả trên máy chưa cài extra 'tts'.
    if src.suffix.lower() not in READABLE_SUFFIXES:
        readable = ", ".join(sorted(READABLE_SUFFIXES))
        msg = (
            f"Không đọc được {src.suffix or '(không đuôi)'}. libsndfile hỗ trợ: {readable}.\n"
            "Định dạng .m4a/.aac cần FFmpeg, mà FFmpeg thuộc Gate D04 — "
            "hãy thu hoặc xuất lại sang WAV hoặc MP3."
        )
        raise ValidationError(msg)

    try:
        import soundfile as sf
    except ImportError as exc:
        msg = "Cần 'soundfile' để đọc định dạng ngoài WAV. Chạy: uv sync --extra tts"
        raise ConfigError(msg) from exc

    try:
        data, rate = sf.read(str(src), dtype="float32", always_2d=False)
    except Exception as exc:
        msg = f"Không giải mã được {src.name}: {exc}"
        raise ValidationError(msg) from exc

    if mono and getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        sf.write(str(dest), data, rate, subtype="PCM_16")
    except Exception as exc:
        msg = f"Không ghi được WAV {dest.name}: {exc}"
        raise ValidationError(msg) from exc

    return inspect_wav(dest)


def inspect_wav(
    path: Path,
    *,
    expected_sample_rate: int | None = None,
    expected_duration_sec: float | None = None,
    duration_tolerance_sec: float = DURATION_TOLERANCE_SEC,
    max_clipping_ratio: float = MAX_CLIPPING_RATIO,
    allow_silence: bool = False,
) -> WavReport:
    """Soi một file WAV và liệt kê mọi vấn đề tìm được.

    Hàm **không ném lỗi** khi file có vấn đề — nó trả về báo cáo để lệnh gọi tự
    quyết định. File hỏng tới mức không đọc nổi cũng thành một dòng ``problems``.
    """
    path = Path(path)
    if not path.is_file():
        return WavReport(path=path, exists=False, problems=[f"Không có file: {path}"])

    size = path.stat().st_size
    problems: list[str] = []

    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            if width not in {1, 2, 4}:
                return WavReport(
                    path=path,
                    exists=True,
                    size_bytes=size,
                    channels=channels,
                    sample_rate=rate,
                    sample_width_bits=width * 8,
                    frames=frames,
                    problems=[f"Độ sâu mẫu không hỗ trợ: {width * 8}-bit"],
                )
            peak, rms, clipped = _peak_and_rms(handle, width, frames, channels)
    except (wave.Error, EOFError, OSError) as exc:
        return WavReport(
            path=path, exists=True, size_bytes=size, problems=[f"Không đọc được WAV: {exc}"]
        )

    duration = round(frames / rate, 3) if rate > 0 else 0.0
    total_samples = max(1, frames * channels)
    clipping_ratio = clipped / total_samples

    if frames == 0:
        problems.append("File không có mẫu âm thanh nào")
    if rate <= 0:
        problems.append("Sample rate không hợp lệ")
    if expected_sample_rate is not None and rate != expected_sample_rate:
        problems.append(f"Sample rate {rate} Hz, kỳ vọng {expected_sample_rate} Hz")
    if expected_duration_sec is not None:
        delta = abs(duration - expected_duration_sec)
        if delta > duration_tolerance_sec:
            problems.append(
                f"Thời lượng {duration:.2f}s lệch {delta:.2f}s so với kỳ vọng "
                f"{expected_duration_sec:.2f}s (cho phép {duration_tolerance_sec:.2f}s)"
            )
    if clipping_ratio > max_clipping_ratio:
        problems.append(
            f"Clipping {clipping_ratio * 100:.3f}% số mẫu (ngưỡng {max_clipping_ratio * 100:.3f}%)"
        )
    if not allow_silence and rms < SILENCE_RMS_THRESHOLD:
        problems.append(f"File gần như câm (RMS {rms:.6f}) — TTS có thể đã chạy hỏng")

    return WavReport(
        path=path,
        exists=True,
        size_bytes=size,
        duration_sec=duration,
        sample_rate=rate,
        channels=channels,
        sample_width_bits=width * 8,
        frames=frames,
        peak=peak,
        rms=rms,
        clipped_samples=clipped,
        clipping_ratio=clipping_ratio,
        problems=problems,
    )
