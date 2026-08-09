"""D05-C — gửi đúng một lần, write-ahead persistence và fail-closed.

Đây là nhóm test bảo vệ tiền. Điều quan trọng nhất được chứng minh ở đây:
khi cổng còn đóng, **số lần gọi provider bằng 0**.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ai_video_agent.errors import (
    BudgetExceededError,
    GateNotReachedError,
    PaidApiNotAllowedError,
    ProviderError,
    SubmissionUnknownError,
)
from ai_video_agent.providers.video_api.capability import VEO_STANDARD, VideoRequestConfig
from ai_video_agent.providers.video_api.fake import FakeVideoTransport
from ai_video_agent.providers.video_api.submission import (
    RetryPolicy,
    SubmissionMachine,
    SubmissionRecord,
    SubmissionState,
    SubmissionStore,
)
from ai_video_agent.providers.video_api.veo import PaidCallGuard, VeoVideoProvider

CONFIG = VideoRequestConfig(
    model_id=VEO_STANDARD, resolution="1080p", aspect_ratio="9:16", duration_seconds=8
)
TODAY = date(2026, 8, 6)


def _machine(tmp_path: Path, transport: FakeVideoTransport) -> SubmissionMachine:
    return SubmissionMachine(
        store=SubmissionStore(tmp_path / "submission.json"), transport=transport
    )


# --- 6. Cổng đóng => provider call count = 0 ------------------------------


def test_gate_dong_thi_provider_khong_bi_goi_lan_nao() -> None:
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(transport=transport, today=TODAY)
    with pytest.raises(GateNotReachedError):
        provider.plan(config=CONFIG, prompt="x", project_id="p")
    assert transport.counter.total == 0


def test_max_usd_bang_khong_thi_provider_khong_bi_goi_lan_nao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trần 0,0 USD phải chặn ngay sau gate — trước cả capability lẫn pricing.

    Bản test cũ chỉ khẳng định "có ném BudgetExceededError", nên vẫn xanh khi
    ngân sách bị kiểm nhầm chỗ (sau capability và pricing). Nay khẳng định thêm
    **thứ tự** qua ``trace``.
    """
    monkeypatch.setattr("ai_video_agent.providers.video_api.veo.gate_is_open", lambda _g: True)
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(
        transport=transport,
        guard=PaidCallGuard(allow_paid_apis=True, max_usd_per_run=Decimal("0.0")),
        today=TODAY,
    )
    trace: list[str] = []
    with pytest.raises(BudgetExceededError, match="bất kể giá bao nhiêu"):
        provider.plan(config=CONFIG, prompt="x", project_id="p", trace=trace)
    assert trace == ["gate_ok"], f"phải dừng ngay sau gate, thực tế đi qua {trace}"
    assert transport.counter.total == 0


def test_chua_bat_allow_paid_thi_provider_khong_bi_goi_lan_nao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_video_agent.providers.video_api.veo.gate_is_open", lambda _g: True)
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(transport=transport, today=TODAY)
    with pytest.raises(PaidApiNotAllowedError):
        provider.plan(config=CONFIG, prompt="x", project_id="p")
    assert transport.counter.total == 0


def test_uoc_tinh_chay_duoc_ma_khong_cham_provider() -> None:
    transport = FakeVideoTransport()
    provider = VeoVideoProvider(transport=transport, today=TODAY)
    cost = provider.estimate_only(config=CONFIG)
    assert cost.estimated_cost_usd == Decimal("3.2000")
    assert transport.counter.total == 0


# --- 7. Submit đúng một lần ------------------------------------------------


def test_submit_attempts_phai_bang_1() -> None:
    assert RetryPolicy().submit_attempts == 1
    with pytest.raises(ValueError, match="submit_attempts phải bằng 1"):
        RetryPolicy(submit_attempts=2)


def test_submit_chi_goi_provider_dung_mot_lan(tmp_path: Path) -> None:
    transport = FakeVideoTransport()
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    assert transport.counter.submit == 1
    assert record.state == SubmissionState.SUBMITTED.value
    assert record.operation_name == transport.operation_name


def test_goi_submit_lan_hai_khong_tao_generation_moi(tmp_path: Path) -> None:
    transport = FakeVideoTransport()
    machine = _machine(tmp_path, transport)
    machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    assert transport.counter.submit == 1


# --- 8. Poll và download được retry mà không submit lại -------------------


def test_poll_duoc_thu_lai_ma_khong_submit_them(tmp_path: Path) -> None:
    transport = FakeVideoTransport(poll_done_after=4)
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    machine.poll_until_done(record)
    assert transport.counter.poll == 4
    assert transport.counter.submit == 1


def test_download_duoc_thu_lai_ma_khong_submit_them(tmp_path: Path) -> None:
    transport = FakeVideoTransport(fail_download_times=2)
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    record = machine.download(record, tmp_path / "out.mp4")
    assert transport.counter.download == 3
    assert transport.counter.submit == 1
    assert (tmp_path / "out.mp4").is_file()


def test_ba_chinh_sach_retry_tach_biet() -> None:
    policy = RetryPolicy()
    assert policy.submit_attempts == 1
    assert policy.poll_attempts > 1
    assert policy.download_attempts > 1


# --- 9/10/11. Crash, khởi động lại, phục hồi operation_name ---------------


def test_crash_sau_submitting_truoc_operation_name_thi_unknown(tmp_path: Path) -> None:
    """Mô phỏng đúng ca nguy hiểm: đã ghi SUBMITTING, chưa kịp có operation_name."""
    store = SubmissionStore(tmp_path / "submission.json")
    store.save(
        SubmissionRecord(
            submission_id="s1",
            state=SubmissionState.SUBMITTING.value,
            model_id=VEO_STANDARD,
        )
    )
    machine = _machine(tmp_path, FakeVideoTransport())
    recovered = machine.recover()
    assert recovered is not None
    assert recovered.state == SubmissionState.SUBMISSION_UNKNOWN.value
    assert "KHÔNG tự gửi lại" in recovered.note


def test_khoi_dong_lai_khong_tu_gui_lai(tmp_path: Path) -> None:
    store = SubmissionStore(tmp_path / "submission.json")
    store.save(
        SubmissionRecord(
            submission_id="s1",
            state=SubmissionState.SUBMITTING.value,
            model_id=VEO_STANDARD,
        )
    )
    transport = FakeVideoTransport()
    machine = _machine(tmp_path, transport)
    with pytest.raises(SubmissionUnknownError, match="Không được tự gửi lại"):
        machine.submit_once(
            submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
        )
    assert transport.counter.submit == 0


def test_operation_name_duoc_luu_va_phuc_hoi(tmp_path: Path) -> None:
    transport = FakeVideoTransport()
    machine = _machine(tmp_path, transport)
    machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    reloaded = SubmissionStore(tmp_path / "submission.json").load()
    assert reloaded.operation_name == transport.operation_name
    assert reloaded.state == SubmissionState.SUBMITTED.value


def test_write_ahead_ghi_submitting_truoc_khi_cham_mang(tmp_path: Path) -> None:
    """Transport hỏng ⇒ trên đĩa vẫn phải có dấu vết của lần thử."""
    boom = FakeVideoTransport(fail_submit_with=ProviderError("transport chet"))
    machine = _machine(tmp_path, boom)
    with pytest.raises(SubmissionUnknownError):
        machine.submit_once(
            submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
        )
    saved = SubmissionStore(tmp_path / "submission.json").load()
    assert saved.state == SubmissionState.SUBMISSION_UNKNOWN.value
    assert saved.submit_attempts == 1


def test_loi_transport_khong_biet_provider_da_nhan_hay_chua_thi_fail_closed(
    tmp_path: Path,
) -> None:
    boom = FakeVideoTransport(fail_submit_with=TimeoutError("mang treo"))
    machine = _machine(tmp_path, boom)
    with pytest.raises(SubmissionUnknownError, match="fail closed"):
        machine.submit_once(
            submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
        )


def test_khong_poll_duoc_khi_chua_co_operation_name(tmp_path: Path) -> None:
    machine = _machine(tmp_path, FakeVideoTransport())
    with pytest.raises(SubmissionUnknownError):
        machine.poll_until_done(SubmissionRecord(submission_id="s1"))
