"""Giao diện web **chạy local** bọc quanh CLI production.

Lớp này là *vỏ*, không phải lõi. Nó không biết render là gì — mọi việc thật đều
gọi lại đúng hàm mà ``aiva make`` gọi. Có hai lý do cứng:

1. Một pipeline thứ hai là một pipeline sẽ trôi khỏi cái đầu tiên, và cái trôi
   đi luôn là cái không có test.
2. Mọi hàng rào đã dựng (gate, consent, cost guard, preflight tài nguyên) nằm
   trên đường CLI. Đi vòng qua nó là vô hiệu hoá tất cả cùng lúc.

``fastapi``/``uvicorn``/``jinja2`` **cố ý không import ở đây** — AGENTS.md cấm
import nặng ở cấp module, và ba gói đó chỉ có khi cài kèm extra. Xem
:mod:`ai_video_agent.webui.app`.
"""

from __future__ import annotations

__all__ = ["DEFAULT_PORT", "HOST"]

#: **Không đổi được từ dòng lệnh.** Máy này dựng video từ hình và giọng thật của
#: người dùng; mở ra LAN là biến nó thành một dịch vụ không xác thực cho cả mạng.
#: Muốn truy cập từ máy khác thì dùng SSH tunnel, đừng sửa dòng này.
HOST = "127.0.0.1"

DEFAULT_PORT = 8765
