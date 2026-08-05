"""Adapter Duix-Avatar (https://github.com/duixcom/Duix-Avatar)."""

from __future__ import annotations

from ai_video_agent.providers.duix.adapter import DuixAvatarProvider
from ai_video_agent.providers.duix.mock import MockDuixAvatarProvider

__all__ = ["DuixAvatarProvider", "MockDuixAvatarProvider"]
