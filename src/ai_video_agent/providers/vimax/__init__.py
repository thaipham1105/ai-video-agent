"""Adapter ViMax (https://github.com/HKUDS/ViMax, MIT) — mô-đun mở rộng D05."""

from __future__ import annotations

from ai_video_agent.providers.vimax.adapter import ViMaxBrollProvider
from ai_video_agent.providers.vimax.mock import MockBrollProvider

__all__ = ["MockBrollProvider", "ViMaxBrollProvider"]
