"""AI-VIDEO-AGENT — repo điều phối cho pipeline video tiếng Việt chạy local."""

from __future__ import annotations

__version__ = "0.1.0"

#: Thứ tự các cổng thực hiện theo brief §8.
#:
#: ``D04G`` là cổng của bake-off MuseTalk, chèn **giữa** D04 và D05 vì
#: :func:`gate_is_open` so theo **chỉ số**: đặt sau D05 thì D04G sẽ mở kèm theo
#: mỗi khi D05 mở, còn đặt trước D04 thì nó mở ngay từ bây giờ.
GATES: tuple[str, ...] = ("D00", "D01", "D02", "D03", "D04", "D04G", "D05")

#: Gate cao nhất đã được người dùng duyệt. Tính năng của gate lớn hơn phải bị chặn.
#:
#: D04G **đã đóng lại** sau khi bake-off MuseTalk hoàn thành (2026-08-10).
#: Kết luận: giữ Duix làm production winner, MuseTalk là research candidate —
#: xem ``D04G_MUSETALK_BAKEOFF_DESIGN.md`` §10.
#:
#: ``D04G`` vẫn nằm trong ``GATES`` để giữ đúng thứ tự đã dùng, nhưng gate đóng
#: vì nó đứng **sau** gate hiện tại. Mở lại = nâng dòng này lên ``"D04G"``, và
#: đó là một thay đổi thấy rõ trong diff chứ không phải một cờ cấu hình.
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
