"""Adapter Veo 3.1 — D05-C, triển khai local với transport tiêm vào.

Thứ tự chặn là phần quan trọng nhất của file này:

    gate  ->  ngân sách  ->  capability  ->  giá  ->  (mới chạm transport)

Mỗi lớp phải chết trước lớp sau. Nhờ vậy khi cổng còn đóng, **số lần gọi provider
bằng 0** — chứ không phải "gọi rồi mới phát hiện sai".

Adapter này **không** khởi tạo client Gemini, **không** đọc API key, **không**
tạo request mạng. Nó nhận một :class:`~ai_video_agent.providers.video_api.submission.VideoTransport`
từ bên ngoài; ở D05-C transport đó là bản giả.

Omni Flash **không** bị thay thế hay xoá: nó vẫn là ứng viên đã đánh giá, giữ
trong kiến trúc để đối chứng. Veo 3.1 Standard mới chỉ là *ứng viên chất lượng
production tiếp theo* — người thắng chưa được chốt, phải chờ A/B có kiểm soát.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from ai_video_agent import gate_is_open
from ai_video_agent.errors import (
    BudgetExceededError,
    GateNotReachedError,
    PaidApiNotAllowedError,
)
from ai_video_agent.providers.video_api.capability import (
    VideoRequestConfig,
    build_provider_payload,
    check_config,
)
from ai_video_agent.providers.video_api.pricing_gate import (
    CostRecord,
    VerifiedPrice,
    lookup_price,
)
from ai_video_agent.providers.video_api.submission import (
    SubmissionMachine,
    SubmissionRecord,
    SubmissionStore,
    VideoTransport,
)

GATE = "D05"
PROVIDER = "google"


class GuardEvent(StrEnum):
    """Mốc đi qua từng lớp chặn, để test chứng minh được **thứ tự** chứ không chỉ kết quả."""

    GATE_OK = "gate_ok"
    BUDGET_PRECHECK_OK = "budget_precheck_ok"
    CAPABILITY_OK = "capability_ok"
    PRICING_OK = "pricing_ok"
    BUDGET_CAP_OK = "budget_cap_ok"


@dataclass(frozen=True)
class PaidCallGuard:
    """Điều kiện phải đủ trước khi một lần gọi tính tiền được phép xảy ra.

    Cố ý tách làm **hai** kiểm tra thay vì một:

    * :meth:`assert_paid_allowed` không cần biết giá, nên chạy được **ngay sau
      gate** — trước capability và trước pricing.
    * :meth:`assert_within_cap` cần con số ước tính nên phải chạy sau pricing.

    Gộp cả hai vào một hàm là lý do bản triển khai đầu tiên bị lệch thứ tự: phụ
    thuộc dữ liệu của phép so sánh số tiền đã kéo toàn bộ kiểm tra ngân sách
    xuống cuối, trong khi hai điều kiện chặn mạnh nhất — cờ tắt và trần bằng 0 —
    vốn không cần giá để quyết định.
    """

    allow_paid_apis: bool = False
    max_usd_per_run: Decimal = Decimal("0.0")

    def assert_paid_allowed(self) -> None:
        """Kiểm tra được **mà không cần biết giá**. Chạy ngay sau gate."""
        if not self.allow_paid_apis:
            msg = (
                "API tính tiền đang bị chặn (AIVA_ALLOW_PAID_APIS chưa bật). "
                "Không gọi provider."
            )
            raise PaidApiNotAllowedError(msg)
        if self.max_usd_per_run <= 0:
            msg = (
                f"Trần chi tiêu của lần chạy này là {self.max_usd_per_run} USD nên không "
                "lời gọi tính tiền nào được phép, bất kể giá bao nhiêu. Không gọi provider."
            )
            raise BudgetExceededError(msg)

    def assert_within_cap(self, estimated_usd: Decimal) -> None:
        """So số tiền cụ thể với trần. Chỉ chạy được sau khi có giá."""
        if estimated_usd > self.max_usd_per_run:
            msg = (
                f"Ước tính {estimated_usd} USD vượt trần {self.max_usd_per_run} USD "
                "của lần chạy này. Không gọi provider."
            )
            raise BudgetExceededError(msg)


@dataclass
class VeoGenerationPlan:
    """Kết quả của giai đoạn kiểm tra — chưa gọi provider lần nào."""

    config: VideoRequestConfig
    price: VerifiedPrice
    payload: dict[str, object]
    cost: CostRecord
    idempotency_key: str


class VeoVideoProvider:
    """Client Veo 3.1 với paid boundary đóng theo mặc định."""

    def __init__(
        self,
        *,
        transport: VideoTransport,
        guard: PaidCallGuard | None = None,
        today: date | None = None,
    ) -> None:
        self._transport = transport
        self._guard = guard or PaidCallGuard()
        self._today = today or date(2026, 8, 6)

    @property
    def guard(self) -> PaidCallGuard:
        return self._guard

    @staticmethod
    def idempotency_key(config: VideoRequestConfig, prompt: str, project_id: str) -> str:
        """Khoá truy vết **nội bộ**.

        Cố ý không gọi là bảo đảm exactly-once: nó chỉ có tác dụng nếu provider
        nhận và tôn trọng khoá, mà điều đó chưa được xác minh. Bảo vệ thật nằm ở
        write-ahead persistence và ``submit_attempts = 1``.
        """
        material = "|".join(
            [
                project_id,
                config.model_id,
                prompt,
                config.resolution,
                config.aspect_ratio,
                str(config.duration_seconds),
                str(config.number_of_videos),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def plan(
        self,
        *,
        config: VideoRequestConfig,
        prompt: str,
        project_id: str,
        expected_snapshot_sha256: str | None = None,
        trace: list[str] | None = None,
    ) -> VeoGenerationPlan:
        """Chạy đủ các lớp chặn theo đúng thứ tự đã duyệt. **Không chạm transport.**

        Thứ tự: ``gate -> budget -> capability -> pricing -> budget(cap)``.

        ``trace`` nhận tên các mốc đã đi qua, để test khẳng định được **thứ tự**
        chứ không chỉ khẳng định "có ném lỗi".
        """
        log = trace if trace is not None else []

        # 1. Gate
        if not gate_is_open(GATE):
            raise GateNotReachedError(
                "API sinh video trả phí (Veo 3.1)",
                GATE,
                hint="Giữ CURRENT_GATE ở D04 cho tới khi PO duyệt nghiệm thu.",
            )
        log.append(GuardEvent.GATE_OK.value)

        # 2. Ngân sách, phần không cần biết giá: cờ tắt hoặc trần bằng 0 thì
        #    dừng ngay — không tốn công kiểm capability lẫn tra bảng giá.
        self._guard.assert_paid_allowed()
        log.append(GuardEvent.BUDGET_PRECHECK_OK.value)

        # 3. Capability — cấu hình sai phải chết trước provider boundary
        check_config(config)
        payload = build_provider_payload(config)
        log.append(GuardEvent.CAPABILITY_OK.value)

        # 4. Giá — fail-closed, không bao giờ chạm placeholder VIDEO_API_GENERIC
        price = lookup_price(
            provider=PROVIDER,
            model_id=config.model_id,
            resolution=config.resolution,
            duration_seconds=config.duration_seconds,
            audio_mode="always_on",
            today=self._today,
            expected_snapshot_sha256=expected_snapshot_sha256,
        )
        estimated = price.total_usd()
        log.append(GuardEvent.PRICING_OK.value)

        # 5. Ngân sách, phần cần con số cụ thể
        self._guard.assert_within_cap(estimated)
        log.append(GuardEvent.BUDGET_CAP_OK.value)

        return VeoGenerationPlan(
            config=config,
            price=price,
            payload=payload,
            cost=CostRecord(estimated_cost_usd=estimated),
            idempotency_key=self.idempotency_key(config, prompt, project_id),
        )

    def estimate_only(
        self, *, config: VideoRequestConfig, expected_snapshot_sha256: str | None = None
    ) -> CostRecord:
        """Ước tính chi phí mà **không** cần gate mở và **không** chạm provider."""
        check_config(config)
        price = lookup_price(
            provider=PROVIDER,
            model_id=config.model_id,
            resolution=config.resolution,
            duration_seconds=config.duration_seconds,
            audio_mode="always_on",
            today=self._today,
            expected_snapshot_sha256=expected_snapshot_sha256,
        )
        return CostRecord(estimated_cost_usd=price.total_usd())

    def submit(
        self,
        plan: VeoGenerationPlan,
        *,
        submission_id: str,
        store_path: Path,
    ) -> SubmissionRecord:
        """Gửi **đúng một lần** qua máy trạng thái. Chỉ gọi sau :meth:`plan`."""
        machine = SubmissionMachine(
            store=SubmissionStore(store_path), transport=self._transport
        )
        return machine.submit_once(
            submission_id=submission_id,
            model_id=plan.config.model_id,
            payload=plan.payload,
            idempotency_key=plan.idempotency_key,
        )
