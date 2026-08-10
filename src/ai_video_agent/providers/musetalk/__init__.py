"""Adapter MuseTalk 1.5 (https://github.com/TMElyralab/MuseTalk) — gate D04G."""

from __future__ import annotations

from ai_video_agent.providers.musetalk.adapter import MuseTalkAvatarProvider
from ai_video_agent.providers.musetalk.mock import MockMuseTalkProvider

__all__ = ["MockMuseTalkProvider", "MuseTalkAvatarProvider"]
