"""Bảng giá và các giả định dùng để ước tính chi phí.

⚠️ Toàn bộ giá của provider tính tiền ở đây là **giả định chưa kiểm chứng**, chỉ
dùng để hệ thống chặn chi tiêu và hiển thị con số cho người dùng xem trước.
Trước khi mở D05 phải đối chiếu lại với bảng giá chính thức của nhà cung cấp và
cập nhật file này.

Provider chạy local (VieNeu trên CPU, Duix trên GPU của máy) có giá 0 USD: chi
phí của chúng là thời gian máy và điện, không phải hoá đơn API.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Tốc độ đọc tiếng Việt trung bình (ký tự/giây) dùng để quy đổi thoại -> thời lượng.
VI_CHARS_PER_SECOND = 15.0

#: Thời lượng tối thiểu của một shot, tránh chia cho 0 và tránh shot chớp nhoáng.
MIN_SHOT_SECONDS = 1.0


@dataclass(frozen=True)
class PriceBook:
    """Đơn giá theo đơn vị của một provider."""

    unit: str
    unit_price_usd: float
    billable: bool
    assumption: str


#: VieNeu-TTS chạy local (ONNX/CPU) — không tốn tiền API.
VIENEU_LOCAL = PriceBook(
    unit="character",
    unit_price_usd=0.0,
    billable=False,
    assumption="VieNeu-TTS chạy local trên CPU/ONNX (Apache-2.0). Chi phí = thời gian máy.",
)

#: Duix-Avatar chạy local bằng Docker + GPU của máy — không tốn tiền API.
DUIX_LOCAL = PriceBook(
    unit="second",
    unit_price_usd=0.0,
    billable=False,
    assumption="Duix-Avatar chạy local qua Docker + GPU của máy. Chi phí = thời gian GPU.",
)

#: ViMax điều phối nhưng gọi API trả phí ở lớp LLM/image/video.
VIMAX_ORCHESTRATED = PriceBook(
    unit="second",
    unit_price_usd=0.40,
    billable=True,
    assumption=(
        "GIẢ ĐỊNH CHƯA KIỂM CHỨNG: ViMax gọi API trả phí cho LLM + image + video. "
        "0,40 USD/giây là con số đặt tạm để chặn chi tiêu; phải đối chiếu bảng giá "
        "thật trước khi mở D05."
    ),
)

#: API sinh video trực tiếp (Veo hoặc tương đương).
VIDEO_API_GENERIC = PriceBook(
    unit="second",
    unit_price_usd=0.50,
    billable=True,
    assumption=(
        "GIẢ ĐỊNH CHƯA KIỂM CHỨNG: 0,50 USD/giây video. Phải thay bằng bảng giá "
        "chính thức của nhà cung cấp trước khi gọi thật ở D05."
    ),
)


def duration_from_text(text: str, *, chars_per_second: float = VI_CHARS_PER_SECOND) -> float:
    """Ước lượng thời lượng đọc của một đoạn thoại tiếng Việt.

    Dùng cho cả planner (chia thời lượng shot) lẫn estimator (quy đổi ra giây
    tính tiền), nên hai bên luôn nhất quán.
    """
    seconds = len(text.strip()) / max(chars_per_second, 1e-6)
    return round(max(MIN_SHOT_SECONDS, seconds), 3)
