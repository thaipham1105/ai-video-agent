"""AI-VIDEO-AGENT — repo điều phối cho pipeline video tiếng Việt chạy local."""

from __future__ import annotations

__version__ = "0.1.0"

#: Thứ tự các cổng thực hiện theo brief §8.
GATES: tuple[str, ...] = ("D00", "D01", "D02", "D03", "D04", "D05")

#: Gate cao nhất đã được người dùng duyệt. Tính năng của gate lớn hơn phải bị chặn.
CURRENT_GATE = "D04"


def gate_is_open(gate: str, *, current: str | None = None) -> bool:
    """``True`` nếu ``gate`` đã được duyệt so với gate hiện tại.

    Đây là hàng rào duy nhất quyết định adapter thật có được chạy hay không, nên
    nó cố tình từ chối mọi tên gate lạ thay vì đoán mò.
    """
    now = current if current is not None else CURRENT_GATE
    if gate not in GATES or now not in GATES:
        return False
    return GATES.index(gate) <= GATES.index(now)


__all__ = ["CURRENT_GATE", "GATES", "__version__", "gate_is_open"]
