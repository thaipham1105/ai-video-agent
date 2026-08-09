"""D05-C — chứng minh **thứ tự** các lớp chặn, không chỉ chứng minh "có ném lỗi".

Thứ tự đã duyệt:

    gate -> budget -> capability -> pricing -> transport

Mỗi test dưới đây khẳng định hai điều cùng lúc:

1. Đúng những mốc nào đã đi qua trước khi dừng (qua ``trace``).
2. ``transport.counter.total == 0`` — provider chưa bị chạm lần nào.

Điểm 1 là thứ bản triển khai đầu tiên thiếu: test cũ chỉ khẳng định "ném đúng
loại lỗi", nên không phát hiện được rằng ngân sách đang bị kiểm **sau** capability
và pricing thay vì trước.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ai_video_agent.errors import (
    BudgetExceededError,
    CapabilityError,
    GateNotReachedError,
    PaidApiNotAllowedError,
    PriceUnverifiedError,
)
from ai_video_agent.providers.video_api.capability import (
    VEO_LITE,
    VEO_STANDARD,
    VideoRequestConfig,
)
from ai_video_agent.providers.video_api.fake import FakeVideoTransport
from ai_video_agent.providers.video_api.veo import GuardEvent, PaidCallGuard, VeoVideoProvider

TODAY = date(2026, 8, 6)
GOOD = VideoRequestConfig(
    model_id=VEO_STANDARD, resolution="1080p", aspect_ratio="9:16", duration_seconds=8
)

GATE = GuardEvent.GATE_OK.value
BUDGET_PRE = GuardEvent.BUDGET_PRECHECK_OK.value
CAP = GuardEvent.CAPABILITY_OK.value
PRICE = GuardEvent.PRICING_OK.value
BUDGET_CAP = GuardEvent.BUDGET_CAP_OK.value


@pytest.fixture
def open_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ai_video_agent.providers.video_api.veo.gate_is_open", lambda _g: True)


def _run(
    provider: VeoVideoProvider, config: VideoRequestConfig = GOOD, **kw: object
) -> list[str]:
    trace: list[str] = []
    provider.plan(config=config, prompt="p", project_id="proj", trace=trace, **kw)  # type: ignore[arg-type]
    return trace


# --- 1. Gate đóng: dừng TRƯỚC budget, capability, pricing, transport ------


def test_gate_dong_dung_truoc_moi_lop_con_lai() -> None:
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("100")),
        today=TODAY,
    )
    trace: list[str] = []
    with pytest.raises(GateNotReachedError):
        provider.plan(config=GOOD, prompt="p", project_id="proj", trace=trace)

    assert trace == [], f"gate đóng mà vẫn đi qua {trace}"
    assert BUDGET_PRE not in trace
    assert CAP not in trace
    assert PRICE not in trace
    assert transport.counter.total == 0


# --- 2. Ngân sách: dừng TRƯỚC capability, pricing, transport --------------


def test_paid_flag_tat_dung_truoc_capability_va_pricing(open_gate: None) -> None:
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=False, max_usd_per_run=Decimal("100")),
        today=TODAY,
    )
    trace: list[str] = []
    with pytest.raises(PaidApiNotAllowedError):
        provider.plan(config=GOOD, prompt="p", project_id="proj", trace=trace)

    assert trace == [GATE], f"phải dừng ngay sau gate, thực tế đi qua {trace}"
    assert CAP not in trace
    assert PRICE not in trace
    assert transport.counter.total == 0


def test_tran_bang_0_dung_truoc_capability_va_pricing(open_gate: None) -> None:
    """Trần 0 chặn được **mà không cần biết giá** — đây là điểm sửa của review."""
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("0.0")),
        today=TODAY,
    )
    trace: list[str] = []
    with pytest.raises(BudgetExceededError, match="bất kể giá bao nhiêu"):
        provider.plan(config=GOOD, prompt="p", project_id="proj", trace=trace)

    assert trace == [GATE], f"phải dừng ngay sau gate, thực tế đi qua {trace}"
    assert CAP not in trace
    assert PRICE not in trace
    assert transport.counter.total == 0


def test_tran_bang_0_chan_ke_ca_khi_cau_hinh_sai(open_gate: None) -> None:
    """Ngân sách phải chặn TRƯỚC capability: cấu hình sai cũng không tới được capability."""
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("0.0")),
        today=TODAY,
    )
    bad = VideoRequestConfig(
        model_id=VEO_LITE,
        resolution="1080p",
        aspect_ratio="9:16",
        duration_seconds=8,
        reference_image_count=3,
    )
    trace: list[str] = []
    # Lỗi phải là ngân sách, KHÔNG phải capability — chứng minh ngân sách chạy trước.
    with pytest.raises(BudgetExceededError):
        provider.plan(config=bad, prompt="p", project_id="proj", trace=trace)
    assert trace == [GATE]
    assert transport.counter.total == 0


# --- 3. Capability lỗi: dừng TRƯỚC pricing, transport ---------------------


@pytest.mark.parametrize(
    "bad",
    [
        VideoRequestConfig(
            model_id=VEO_LITE, resolution="1080p", aspect_ratio="9:16",
            duration_seconds=8, reference_image_count=1,
        ),
        VideoRequestConfig(
            model_id=VEO_STANDARD, resolution="1080p", aspect_ratio="9:16",
            duration_seconds=5,
        ),
        VideoRequestConfig(
            model_id=VEO_STANDARD, resolution="1080p", aspect_ratio="9:16",
            duration_seconds=8, want_silent=True,
        ),
        VideoRequestConfig(
            model_id=VEO_STANDARD, resolution="1080p", aspect_ratio="9:16",
            duration_seconds=8, requested_fps=30,
        ),
    ],
)
def test_capability_loi_dung_truoc_pricing(open_gate: None, bad: VideoRequestConfig) -> None:
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("100")),
        today=TODAY,
    )
    trace: list[str] = []
    with pytest.raises(CapabilityError):
        provider.plan(config=bad, prompt="p", project_id="proj", trace=trace)

    assert trace == [GATE, BUDGET_PRE], f"phải dừng trước pricing, thực tế {trace}"
    assert PRICE not in trace
    assert transport.counter.total == 0


# --- 4. Pricing lỗi: dừng TRƯỚC transport ---------------------------------


def test_pricing_thieu_dong_gia_dung_truoc_transport(open_gate: None) -> None:
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("100")),
        today=TODAY,
    )
    only_720p = VideoRequestConfig(
        model_id=VEO_STANDARD, resolution="720p", aspect_ratio="9:16", duration_seconds=8
    )
    trace: list[str] = []
    with pytest.raises(PriceUnverifiedError):
        provider.plan(config=only_720p, prompt="p", project_id="proj", trace=trace)

    assert trace == [GATE, BUDGET_PRE, CAP], f"phải dừng ngay sau capability, thực tế {trace}"
    assert BUDGET_CAP not in trace
    assert transport.counter.total == 0


def test_pricing_qua_han_dung_truoc_transport(open_gate: None) -> None:
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("100")),
        today=date(2026, 12, 1),
    )
    trace: list[str] = []
    with pytest.raises(PriceUnverifiedError, match="ngày"):
        provider.plan(config=GOOD, prompt="p", project_id="proj", trace=trace)

    assert trace == [GATE, BUDGET_PRE, CAP]
    assert transport.counter.total == 0


def test_pricing_sai_snapshot_dung_truoc_transport(open_gate: None) -> None:
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("100")),
        today=TODAY,
    )
    trace: list[str] = []
    with pytest.raises(PriceUnverifiedError, match="không khớp"):
        provider.plan(
            config=GOOD,
            prompt="p",
            project_id="proj",
            expected_snapshot_sha256="0" * 64,
            trace=trace,
        )

    assert trace == [GATE, BUDGET_PRE, CAP]
    assert transport.counter.total == 0


# --- 5. Trần thấp hơn giá: dừng ở lớp cuối, vẫn trước transport ----------


def test_tran_thap_hon_gia_dung_o_lop_cuoi(open_gate: None) -> None:
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("1.00")),
        today=TODAY,
    )
    trace: list[str] = []
    with pytest.raises(BudgetExceededError, match="vượt trần"):
        provider.plan(config=GOOD, prompt="p", project_id="proj", trace=trace)

    assert trace == [GATE, BUDGET_PRE, CAP, PRICE]
    assert BUDGET_CAP not in trace
    assert transport.counter.total == 0


# --- 6. Đường thông suốt: đủ 5 mốc, đúng thứ tự, vẫn chưa chạm transport --


def test_duong_thong_suot_di_dung_thu_tu_da_duyet(open_gate: None) -> None:
    del open_gate
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("5.00")),
        today=TODAY,
    )
    trace = _run(provider)

    assert trace == [GATE, BUDGET_PRE, CAP, PRICE, BUDGET_CAP]
    # plan() chỉ lập kế hoạch — transport vẫn chưa bị chạm.
    assert transport.counter.total == 0


def test_thu_tu_dung_bang_yeu_cau_da_duyet(open_gate: None) -> None:
    """Khẳng định tường minh: gate -> budget -> capability -> pricing."""
    del open_gate
    provider = VeoVideoProvider(
        transport=FakeVideoTransport(),
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("5.00")),
        today=TODAY,
    )
    trace = _run(provider)
    assert trace.index(GATE) < trace.index(BUDGET_PRE) < trace.index(CAP) < trace.index(PRICE)
