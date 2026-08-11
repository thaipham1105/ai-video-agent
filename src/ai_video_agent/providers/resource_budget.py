"""Preflight tài nguyên — đối chiếu lời hứa của backend với thứ máy thật sự có.

``AvatarProvider.estimate_resources()`` nói backend cần bao nhiêu. Module này trả
lời câu còn lại: **máy này có chừng đó không**, và chặn trước khi chạm GPU/HTTP
nếu không.

Ba nguyên tắc, đều rút ra từ những lần đã đau ở bake-off D04:

1. **Không biết ≠ bằng 0.** Máy không có ``nvidia-smi`` thì VRAM là *chưa xác
   minh được*, không phải "0 MiB". Giả 0 sẽ chặn nhầm mọi backend; giả vô hạn sẽ
   để lọt mọi backend. Cả hai đều tệ hơn việc nói thẳng là không biết.
2. **Không dò GPU bằng cách nạp model.** Chỉ đọc ``nvidia-smi`` và
   ``shutil.disk_usage`` — đúng cách ``cli/doctor.py`` đang làm.
3. **Cấu hình thắng máy dò.** Người vận hành biết mình đang chia GPU với việc
   khác thì phải khai được con số thấp hơn thực tế và được tôn trọng.

RAM cố ý **không** có bộ dò: Python không có API chuẩn, đa nền tảng để đọc RAM
trống. Viết một nhánh riêng cho Windows rồi trả ``None`` ở nơi khác chỉ tạo ảo
giác có kiểm tra. Ai cần chặn theo RAM thì khai ``AIVA_RAM_BUDGET_MIB``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ai_video_agent.errors import CapabilityError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_video_agent.config import Config
    from ai_video_agent.providers.base import ResourceEstimate

UNVERIFIED = "chưa xác minh được"

#: Đọc VRAM còn trống. ``memory.free`` chứ không phải ``memory.total``: cái đáng
#: quan tâm là phần còn dùng được, không phải phần GPU từng có.
_NVIDIA_SMI_FREE_ARGS = ("--query-gpu=memory.free", "--format=csv,noheader,nounits")

#: Tổng VRAM của card. Chỉ dùng để quy "phần trống thấp nhất quan sát được" thành
#: "phần đã dùng cao nhất" khi lấy mẫu lúc render — xem ``providers.vram_sampler``.
_NVIDIA_SMI_TOTAL_ARGS = ("--query-gpu=memory.total", "--format=csv,noheader,nounits")


def _query_nvidia_smi(args: tuple[str, ...]) -> int | None:
    """Hỏi ``nvidia-smi`` một chỉ số MiB, lấy card có số **lớn nhất**.

    Máy nhiều GPU thì lấy card rảnh nhất / lớn nhất — pipeline chạy một job trên
    một card, nên cộng dồn lại là con số không có thật.

    Mọi lỗi đều thành ``None`` = *chưa xác minh được*, không phải 0.
    """
    binary = shutil.which("nvidia-smi")
    if binary is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - đường dẫn do shutil.which giải, tham số cố định
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None

    values: list[int] = []
    for line in completed.stdout.splitlines():
        raw = line.strip()
        if raw.isdigit():
            values.append(int(raw))
    return max(values) if values else None


def probe_free_vram_mib() -> int | None:
    """VRAM trống theo ``nvidia-smi``, hoặc ``None`` nếu không hỏi được.

    Chỉ đọc, không nạp gì.
    """
    return _query_nvidia_smi(_NVIDIA_SMI_FREE_ARGS)


def probe_total_vram_mib() -> int | None:
    """Tổng VRAM của card, hoặc ``None`` nếu không hỏi được.

    Ở chung nhà với ``probe_free_vram_mib`` vì là hai mặt của cùng một câu hỏi và
    cùng đọc một công cụ. Trước D05-C, MuseTalk giữ một bản riêng — hai bản là
    hai chỗ để lệch nhau, và chính comment ở đó đã hẹn gộp lại khi có nơi thứ hai
    cần dùng. Duix chính là nơi thứ hai đó.
    """
    return _query_nvidia_smi(_NVIDIA_SMI_TOTAL_ARGS)


def probe_free_storage_mib(path: Path) -> int | None:
    """Dung lượng trống nơi sẽ ghi artifact, hoặc ``None`` nếu không đọc được."""
    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        return int(shutil.disk_usage(target).free // (1024 * 1024))
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class ResourceBudget:
    """Tài nguyên máy này có. ``None`` ở đâu nghĩa là **không biết** ở đó."""

    #: **Sức chứa**, không phải phần đang rảnh — đây là con số cổng đem so.
    #:
    #: Vì sao là sức chứa: ``ResourceEstimate.vram_mib`` của các backend đo bằng
    #: ``nvidia-smi --query-gpu=memory.used``, tức **đỉnh của cả card** đã bao
    #: gồm nền desktop và phần container giữ sẵn. Đem con số đó so với VRAM
    #: *trống* là trừ hai lần cùng một phần bộ nhớ. D05-C bắt được lỗi này khi
    #: một máy vừa render xong ở D05-B vẫn bị chặn: cần 8.500, trống 7.651,
    #: trong khi card có 12.282 và lượt chạy thật chỉ chạm đỉnh 11.716.
    vram_mib: int | None = None
    #: VRAM đang trống. **Chỉ để cảnh báo**, không phải cổng — máy có thể tự
    #: nhả bộ nhớ khi job cần, mà cũng có thể không. Nói ra để người vận hành
    #: quyết, thay vì im lặng cho qua hoặc chặn thẳng.
    vram_free_mib: int | None = None
    ram_mib: int | None = None
    storage_mib: int | None = None
    #: Nguồn của từng con số, để báo cáo nói được "biết từ đâu".
    sources: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: Config) -> ResourceBudget:
        """Chỉ lấy số người vận hành đã khai. Không dò máy."""
        sources = tuple(
            f"{label}=config"
            for label, value in (
                ("vram", config.vram_budget_mib),
                ("ram", config.ram_budget_mib),
                ("storage", config.storage_budget_mib),
            )
            if value is not None
        )
        return cls(
            vram_mib=config.vram_budget_mib,
            ram_mib=config.ram_budget_mib,
            storage_mib=config.storage_budget_mib,
            sources=sources,
        )

    @classmethod
    def detect(
        cls,
        config: Config,
        *,
        vram_probe: Callable[[], int | None] | None = None,
        vram_free_probe: Callable[[], int | None] | None = None,
        storage_probe: Callable[[Path], int | None] | None = None,
    ) -> ResourceBudget:
        """Cấu hình trước, máy dò sau. Thiếu cả hai thì để ``None``.

        ``vram_probe`` dò **tổng VRAM của card** (sức chứa), không phải phần
        trống — xem giải thích ở :attr:`vram_mib`.

        Khai ``AIVA_VRAM_BUDGET_MIB`` thì **không dò gì cả**: người vận hành biết
        mình đang chia GPU với việc khác, và con số họ khai phải được tôn trọng
        nguyên vẹn, kể cả phần cảnh báo.

        Bộ dò tiêm được để test không phụ thuộc vào máy đang chạy — và để không
        ai lỡ biến test thành thứ gọi ``nvidia-smi`` thật.
        """
        base = cls.from_config(config)
        sources = list(base.sources)

        vram = base.vram_mib
        free = None
        if vram is None:
            vram = (vram_probe or probe_total_vram_mib)()
            if vram is not None:
                sources.append("vram=nvidia-smi(total)")
            free = (vram_free_probe or probe_free_vram_mib)()
            if free is not None:
                sources.append("vram_free=nvidia-smi")

        storage = base.storage_mib
        if storage is None:
            storage = (storage_probe or probe_free_storage_mib)(config.runtime_dir)
            if storage is not None:
                sources.append("storage=disk_usage")

        return cls(
            vram_mib=vram,
            vram_free_mib=free,
            ram_mib=base.ram_mib,
            storage_mib=storage,
            sources=tuple(sources),
        )

    def describe(self) -> str:
        vram = self._fmt(self.vram_mib)
        if self.vram_free_mib is not None:
            vram += f" (trống {self.vram_free_mib} MiB)"
        parts = [
            f"VRAM {vram}",
            f"RAM {self._fmt(self.ram_mib)}",
            f"đĩa {self._fmt(self.storage_mib)}",
        ]
        origin = ", ".join(self.sources) if self.sources else "không có nguồn nào"
        return f"{'; '.join(parts)} ({origin})"

    @staticmethod
    def _fmt(value: int | None) -> str:
        return UNVERIFIED if value is None else f"{value} MiB"


@dataclass(frozen=True)
class ResourcePreflight:
    """Kết quả đối chiếu: đủ, thiếu, hay không đủ dữ liệu để nói.

    Cố ý **không** ném lỗi ngay trong lúc dựng. Đường render thật gọi
    :meth:`raise_if_insufficient` để chặn; nơi khác có thể chỉ muốn đọc báo cáo.
    Một hàm vừa tính vừa ném thì không dùng lại được cho việc chỉ-xem.
    """

    provider_id: str
    needed: ResourceEstimate
    budget: ResourceBudget
    #: Từng chiều thiếu, dạng câu hoàn chỉnh cho người đọc.
    shortfalls: tuple[str, ...] = ()
    #: Chiều không có dữ liệu để đối chiếu.
    unverified: tuple[str, ...] = ()
    #: Điều đáng nói nhưng **không chặn**. Card đủ sức chứa mà đang bị chiếm là
    #: chuyện người vận hành xử được (đóng app, restart container); chặn thẳng
    #: sẽ khoá cả những máy chạy được — chính là lỗi D05-C đã bắt.
    advisories: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.shortfalls

    @property
    def fully_verified(self) -> bool:
        return not self.unverified

    def raise_if_insufficient(self) -> None:
        if self.ok:
            return
        raise CapabilityError(self.message())

    def message(self) -> str:
        origin = "đo thật" if self.needed.measured else "ước tính từ tài liệu"
        head = (
            f"{self.provider_id} không đủ tài nguyên để chạy "
            f"({origin}"
            + (f", đo ngày {self.needed.measured_on}" if self.needed.measured_on else "")
            + "):"
        )
        body = " ".join(self.shortfalls)
        return f"{head} {body} Không gọi provider."

    def warning(self) -> str:
        """Câu ghi vào manifest khi không chặn nhưng vẫn phải nói rõ."""
        them = (" " + " ".join(self.advisories)) if self.advisories else ""
        if self.fully_verified:
            return (
                f"Preflight tài nguyên {self.provider_id}: đủ. "
                f"Cần {self._need_text()}; máy có {self.budget.describe()}.{them}"
            )
        missing = ", ".join(self.unverified)
        return (
            f"Preflight tài nguyên {self.provider_id}: {UNVERIFIED} cho {missing}. "
            f"Cần {self._need_text()}. Không suy đoán khả năng máy — khai "
            "AIVA_VRAM_BUDGET_MIB / AIVA_RAM_BUDGET_MIB / AIVA_STORAGE_BUDGET_MIB "
            f"nếu muốn chặn theo ngưỡng.{them}"
        )

    def _need_text(self) -> str:
        return (
            f"VRAM {self.needed.vram_mib} MiB, RAM {self.needed.ram_mib} MiB, "
            f"đĩa {self.needed.storage_mib} MiB"
        )


def check_resources(
    provider_id: str, needed: ResourceEstimate, budget: ResourceBudget
) -> ResourcePreflight:
    """Đối chiếu từng chiều. Chiều nào không biết thì ghi nhận, không đoán.

    Cổng VRAM so với **sức chứa** (``budget.vram_mib``), không phải phần trống.
    Phần trống chỉ sinh ra lời nhắc — xem :attr:`ResourceBudget.vram_mib`.
    """
    shortfalls: list[str] = []
    unverified: list[str] = []
    advisories: list[str] = []

    for label, need, have in (
        ("VRAM", needed.vram_mib, budget.vram_mib),
        ("RAM", needed.ram_mib, budget.ram_mib),
        ("đĩa", needed.storage_mib, budget.storage_mib),
    ):
        if have is None:
            unverified.append(label)
        elif need > have:
            shortfalls.append(f"{label} cần {need} MiB, máy còn {have} MiB.")

    if budget.vram_free_mib is not None and budget.vram_free_mib < needed.vram_mib:
        advisories.append(
            f"VRAM đang trống {budget.vram_free_mib} MiB, thấp hơn đỉnh {needed.vram_mib} MiB "
            "đã đo. Card đủ sức chứa nên vẫn chạy, nhưng nếu gặp OOM thì đóng bớt "
            "ứng dụng dùng GPU, hoặc khởi động lại container để nó nhả model của lượt trước."
        )

    return ResourcePreflight(
        provider_id=provider_id,
        needed=needed,
        budget=budget,
        shortfalls=tuple(shortfalls),
        unverified=tuple(unverified),
        advisories=tuple(advisories),
    )
