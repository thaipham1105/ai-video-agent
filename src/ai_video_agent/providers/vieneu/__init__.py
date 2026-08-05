"""Adapter VieNeu-TTS (https://github.com/pnnbao97/VieNeu-TTS, Apache-2.0)."""

from __future__ import annotations

from ai_video_agent.providers.vieneu.adapter import VieNeuTtsProvider
from ai_video_agent.providers.vieneu.mock import MockVieNeuTtsProvider

__all__ = ["MockVieNeuTtsProvider", "VieNeuTtsProvider"]
