"""Cửa vào của giao diện web: kiểm dependency rồi mới nạp FastAPI.

Vì sao tách khỏi :mod:`ai_video_agent.webui.routes`: AGENTS.md cấm import nặng ở
cấp module. ``routes`` import fastapi ngay khi nạp (bắt buộc — xem docstring ở
đó), nên module này đứng chắn phía trước và chỉ nạp nó khi thật sự chạy UI.
Nhờ vậy ``aiva --help`` và mọi lệnh khác vẫn chạy trên máy chưa cài extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_video_agent.errors import AivaError
from ai_video_agent.webui import HOST

if TYPE_CHECKING:
    from ai_video_agent.config import Config
    from ai_video_agent.webui.jobs import JobRunner

MISSING_DEPS = (
    "Giao diện web cần fastapi + uvicorn + jinja2. Chúng đi kèm bộ TTS:\n"
    "    uv sync --extra tts\n"
    "Rồi chạy lại: uv run aiva ui"
)

REQUIRED = ("fastapi", "uvicorn", "jinja2")


def require_web_deps() -> None:
    """Kiểm dependency **trước** khi làm gì khác, báo đúng lệnh cần chạy.

    ``ImportError`` thô không nói được phải gõ gì để sửa; câu này thì có.
    """
    import importlib.util

    thieu = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if thieu:
        raise AivaError(MISSING_DEPS + f"\nĐang thiếu: {', '.join(thieu)}")


def create_app(config: Config, *, runner: JobRunner | None = None) -> Any:
    """Dựng ứng dụng FastAPI. Không mở cổng nào — test gọi thẳng được."""
    require_web_deps()
    from ai_video_agent.webui.routes import build_app

    return build_app(config, runner)


def serve(config: Config, *, port: int, open_browser: bool = True) -> None:
    """Chạy server. **Luôn** bind ``127.0.0.1`` — host không phải tham số."""
    require_web_deps()
    import uvicorn

    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{port}/")).start()

    uvicorn.run(create_app(config), host=HOST, port=port, log_level="warning")
