"""D05-C — cổng giá fail-closed và bốn khái niệm chi phí.

Bảo vệ trực tiếp chống lại sai lầm đã có thật: một placeholder 0,50 USD/s tồn
tại từ D01 và làm mọi ước tính trước D05-A vô nghĩa.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ai_video_agent.errors import PriceUnverifiedError
from ai_video_agent.providers.video_api.pricing_gate import (
    PRICE_BOOK,
    CostRecord,
    VerifiedPrice,
    lookup_price,
)

TODAY = date(2026, 8, 6)


def _lookup(model_id: str, **kw: object) -> VerifiedPrice:
    base: dict[str, object] = {
        "provider": "google",
        "model_id": model_id,
        "resolution": "1080p",
        "duration_seconds": 8,
        "audio_mode": "always_on",
        "today": TODAY,
    }
    base.update(kw)
    return lookup_price(**base)  # type: ignore[arg-type]


# --- Giá đúng và dùng Decimal --------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "per_sec", "total"),
    [
        ("veo-3.1-generate-preview", "0.40", "3.2000"),
        ("veo-3.1-fast-generate-preview", "0.12", "0.9600"),
        ("veo-3.1-lite-generate-preview", "0.08", "0.6400"),
    ],
)
def test_gia_1080p_dung_nhu_da_ghim(model_id: str, per_sec: str, total: str) -> None:
    price = _lookup(model_id)
    assert price.usd_per_second == Decimal(per_sec)
    assert price.total_usd() == Decimal(total)


def test_moi_gia_deu_la_decimal_khong_phai_float() -> None:
    for price in PRICE_BOOK:
        assert isinstance(price.usd_per_second, Decimal)
        assert isinstance(price.total_usd(), Decimal)


def test_moi_dong_gia_deu_co_nguon_va_ngay() -> None:
    for price in PRICE_BOOK:
        assert price.source_url.startswith("https://ai.google.dev/")
        assert price.effective_date is not None
        assert price.verified_on is not None
        assert price.snapshot_sha256()


# --- 5. Thiếu, quá hạn hoặc không khớp => fail closed ---------------------


def test_model_khong_co_trong_bang_gia_thi_fail_closed() -> None:
    with pytest.raises(PriceUnverifiedError, match="Không có dòng giá đã kiểm chứng"):
        _lookup("veo-3.1-khong-ton-tai")


def test_do_phan_giai_khong_co_trong_bang_gia_thi_fail_closed() -> None:
    with pytest.raises(PriceUnverifiedError):
        _lookup("veo-3.1-generate-preview", resolution="720p")


def test_thoi_luong_khong_co_trong_bang_gia_thi_fail_closed() -> None:
    with pytest.raises(PriceUnverifiedError):
        _lookup("veo-3.1-generate-preview", duration_seconds=5)


def test_gia_qua_han_kiem_chung_thi_fail_closed() -> None:
    with pytest.raises(PriceUnverifiedError, match="đã 40 ngày"):
        _lookup("veo-3.1-generate-preview", today=date(2026, 9, 15))


def test_snapshot_hash_khong_khop_thi_fail_closed() -> None:
    with pytest.raises(PriceUnverifiedError, match="không khớp"):
        _lookup("veo-3.1-generate-preview", expected_snapshot_sha256="0" * 64)


def test_snapshot_hash_khop_thi_qua() -> None:
    price = _lookup("veo-3.1-generate-preview")
    again = _lookup(
        "veo-3.1-generate-preview", expected_snapshot_sha256=price.snapshot_sha256()
    )
    assert again.usd_per_second == Decimal("0.40")


def test_thieu_source_url_thi_fail_closed() -> None:
    broken = (
        VerifiedPrice(
            provider="google",
            model_id="veo-3.1-generate-preview",
            resolution="1080p",
            duration_seconds=8,
            audio_mode="always_on",
            usd_per_second=Decimal("0.40"),
            source_url="",
            effective_date=date(2026, 8, 5),
            verified_on=date(2026, 8, 6),
        ),
    )
    with pytest.raises(PriceUnverifiedError, match="thiếu source_url"):
        lookup_price(
            provider="google",
            model_id="veo-3.1-generate-preview",
            resolution="1080p",
            duration_seconds=8,
            audio_mode="always_on",
            today=TODAY,
            book=broken,
        )


def test_duong_veo_khong_bao_gio_cham_placeholder_cu() -> None:
    """``VIDEO_API_GENERIC`` là số bịa từ D01 — bảng giá mới không được dính tới nó."""
    from ai_video_agent.providers import pricing as legacy

    assert legacy.VIDEO_API_GENERIC.unit_price_usd == 0.50
    for price in PRICE_BOOK:
        assert price.usd_per_second != Decimal("0.50")
        assert "GIẢ ĐỊNH" not in price.source_url


# --- Bốn khái niệm chi phí tách bạch --------------------------------------


def test_computed_charge_khong_phai_actual_cost() -> None:
    record = CostRecord(
        estimated_cost_usd=Decimal("3.2000"),
        computed_charge_from_duration_usd=Decimal("3.2000"),
    )
    assert record.has_authoritative_cost is False
    assert "KHÔNG phải actual cost" in record.describe()


def test_co_usage_provider_thi_moi_la_co_so_chac_chan() -> None:
    record = CostRecord(
        estimated_cost_usd=Decimal("3.2000"),
        computed_charge_from_duration_usd=Decimal("3.2000"),
        provider_reported_usage={"output_tokens": 46336},
    )
    assert record.has_authoritative_cost is True


def test_billing_console_la_co_so_cao_nhat() -> None:
    record = CostRecord(
        estimated_cost_usd=Decimal("3.2000"),
        billing_reconciled_cost_usd=Decimal("3.1987"),
    )
    assert record.has_authoritative_cost is True
    assert "billing console" in record.describe()


def test_chi_co_uoc_tinh_thi_noi_ro_la_uoc_tinh() -> None:
    record = CostRecord(estimated_cost_usd=Decimal("3.2000"))
    assert "ước tính" in record.describe()
