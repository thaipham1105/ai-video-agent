"""Cổng giá fail-closed cho provider sinh video trả phí.

Ba nguyên tắc, đều rút ra từ sai lầm có thật của dự án này:

1. **Dùng ``Decimal``, không dùng ``float``.** Sai số dấu phẩy động không chấp
   nhận được với dữ liệu tài chính.
2. **Fail-closed.** Thiếu nguồn, quá hạn kiểm chứng, sai hash hay không khớp
   khoá đều phải ném lỗi. ``VIDEO_API_GENERIC = 0.50 USD/s`` trong
   :mod:`ai_video_agent.providers.pricing` là một con số bịa tồn tại từ D01 và
   đã làm mọi ước tính trước D05-A trở thành vô nghĩa. Đường Veo **không bao giờ**
   được chạm vào placeholder đó.
3. **Bốn khái niệm chi phí tách bạch.** Không được gọi con số suy ra từ thời
   lượng là "actual cost" khi provider không trả usage.

Nguồn giá: https://ai.google.dev/gemini-api/docs/pricing (trang ghi cập nhật 2026-08-05)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from ai_video_agent.errors import PriceUnverifiedError

PRICING_SOURCE_URL = "https://ai.google.dev/gemini-api/docs/pricing"

#: Làm tròn LÊN tới 0,0001 USD — không bao giờ báo thấp hơn thực tế.
_QUANT = Decimal("0.0001")


def ceil_usd(value: Decimal) -> Decimal:
    return value.quantize(_QUANT, rounding=ROUND_CEILING)


@dataclass(frozen=True)
class VerifiedPrice:
    """Một dòng giá đã kiểm chứng, khoá đủ chặt để không lẫn giữa các cấu hình."""

    provider: str
    model_id: str
    resolution: str
    duration_seconds: int
    audio_mode: str
    usd_per_second: Decimal
    source_url: str
    effective_date: date
    verified_on: date
    max_age_days: int = 30

    @property
    def key(self) -> tuple[str, str, str, int, str]:
        return (
            self.provider,
            self.model_id,
            self.resolution,
            self.duration_seconds,
            self.audio_mode,
        )

    def snapshot_sha256(self) -> str:
        """Hash nội dung dòng giá — đổi một ký tự là hash đổi."""
        material = "|".join(
            [
                self.provider,
                self.model_id,
                self.resolution,
                str(self.duration_seconds),
                self.audio_mode,
                str(self.usd_per_second),
                self.source_url,
                self.effective_date.isoformat(),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def total_usd(self) -> Decimal:
        return ceil_usd(Decimal(self.duration_seconds) * self.usd_per_second)


_EFFECTIVE = date(2026, 8, 5)
_VERIFIED = date(2026, 8, 6)


def _veo(model_id: str, usd_per_second: str) -> VerifiedPrice:
    return VerifiedPrice(
        provider="google",
        model_id=model_id,
        resolution="1080p",
        duration_seconds=8,
        audio_mode="always_on",
        usd_per_second=Decimal(usd_per_second),
        source_url=PRICING_SOURCE_URL,
        effective_date=_EFFECTIVE,
        verified_on=_VERIFIED,
    )


#: Chỉ ba dòng này. Không có dòng nào thiếu nguồn hay ngày kiểm chứng.
PRICE_BOOK: tuple[VerifiedPrice, ...] = (
    _veo("veo-3.1-generate-preview", "0.40"),
    _veo("veo-3.1-fast-generate-preview", "0.12"),
    _veo("veo-3.1-lite-generate-preview", "0.08"),
)


def _required_fields_present(price: VerifiedPrice) -> str | None:
    if not price.source_url:
        return "thiếu source_url"
    if not price.model_id:
        return "thiếu model_id"
    if not price.resolution:
        return "thiếu resolution"
    if not price.audio_mode:
        return "thiếu audio_mode"
    if price.usd_per_second <= 0:
        return "usd_per_second không hợp lệ"
    return None


def lookup_price(
    *,
    provider: str,
    model_id: str,
    resolution: str,
    duration_seconds: int,
    audio_mode: str,
    today: date,
    expected_snapshot_sha256: str | None = None,
    book: tuple[VerifiedPrice, ...] = PRICE_BOOK,
) -> VerifiedPrice:
    """Tra giá theo khoá đầy đủ. Fail-closed ở mọi điểm nghi ngờ."""
    want = (provider, model_id, resolution, duration_seconds, audio_mode)
    match = next((p for p in book if p.key == want), None)

    if match is None:
        available = ", ".join(f"{p.model_id}@{p.resolution}/{p.duration_seconds}s" for p in book)
        msg = (
            f"Không có dòng giá đã kiểm chứng cho {want}. Đã ghim: {available}. "
            "KHÔNG dùng placeholder, KHÔNG đoán — dừng và xin duyệt lại bảng giá."
        )
        raise PriceUnverifiedError(msg)

    missing = _required_fields_present(match)
    if missing is not None:
        msg = f"Dòng giá {match.model_id} không hợp lệ: {missing}."
        raise PriceUnverifiedError(msg)

    age_days = (today - match.verified_on).days
    if age_days > match.max_age_days:
        msg = (
            f"Giá của {match.model_id} kiểm chứng ngày {match.verified_on.isoformat()}, "
            f"đã {age_days} ngày (trần {match.max_age_days}). "
            f"Kiểm tra lại {match.source_url} rồi cập nhật trước khi gọi."
        )
        raise PriceUnverifiedError(msg)

    if age_days < 0:
        msg = f"verified_on của {match.model_id} nằm ở tương lai — dữ liệu giá không tin được."
        raise PriceUnverifiedError(msg)

    actual = match.snapshot_sha256()
    if expected_snapshot_sha256 is not None and actual != expected_snapshot_sha256:
        msg = (
            f"Snapshot giá của {match.model_id} không khớp. "
            f"Chờ {expected_snapshot_sha256[:16]}…, thực tế {actual[:16]}…. "
            "Bảng giá đã đổi — dừng và xin PO duyệt lại."
        )
        raise PriceUnverifiedError(msg)

    return match


@dataclass(frozen=True)
class CostRecord:
    """Bốn khái niệm chi phí, cố ý tách bạch.

    Nhầm lẫn giữa chúng chính là điều đã xảy ra ở D05-B: con số 0,5070 USD được
    báo như "actual cost" trong khi thực chất chỉ là suy ra từ thời lượng, vì
    usage của API đã mất do lỗi serialization.
    """

    #: Trước khi gọi, lấy từ bảng giá đã ghim.
    estimated_cost_usd: Decimal
    #: Sau khi có clip: thời lượng thật nhân đơn giá. **Không phải** actual cost.
    computed_charge_from_duration_usd: Decimal | None = None
    #: Chỉ điền khi API thật sự trả usage.
    provider_reported_usage: dict[str, object] | None = None
    #: Chỉ điền khi đối chiếu được billing console.
    billing_reconciled_cost_usd: Decimal | None = None

    @property
    def has_authoritative_cost(self) -> bool:
        """``True`` chỉ khi có số từ provider hoặc từ billing console."""
        return (
            self.provider_reported_usage is not None
            or self.billing_reconciled_cost_usd is not None
        )

    def describe(self) -> str:
        if self.billing_reconciled_cost_usd is not None:
            return f"{self.billing_reconciled_cost_usd} USD (đối chiếu billing console)"
        if self.provider_reported_usage is not None:
            return "chi phí theo usage provider trả về"
        if self.computed_charge_from_duration_usd is not None:
            return (
                f"{self.computed_charge_from_duration_usd} USD "
                "(SUY RA từ thời lượng — KHÔNG phải actual cost)"
            )
        return f"{self.estimated_cost_usd} USD (mới là ước tính)"
