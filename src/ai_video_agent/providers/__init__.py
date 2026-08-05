"""Adapter tới các hệ thống bên ngoài.

Mỗi thư mục con giữ một upstream tách biệt và **không** chứa mã nguồn của
upstream đó (brief §3):

* ``vieneu``   — VieNeu-TTS, SDK Python in-process (thật từ D02).
* ``duix``     — Duix-Avatar, HTTP tới container local (thật từ D03).
* ``vimax``    — ViMax, mô-đun mở rộng (thật từ D05).
* ``video_api`` — API sinh video tính tiền (thật từ D05, mặc định tắt).
"""

from __future__ import annotations

from ai_video_agent.providers.base import (
    AvatarProvider,
    AvatarRequest,
    AvatarResult,
    BrollProvider,
    BrollRequest,
    BrollResult,
    CostQuote,
    ProviderInfo,
    ProviderSet,
    TtsProvider,
    TtsRequest,
    TtsResult,
)
from ai_video_agent.providers.registry import build_provider_set

__all__ = [
    "AvatarProvider",
    "AvatarRequest",
    "AvatarResult",
    "BrollProvider",
    "BrollRequest",
    "BrollResult",
    "CostQuote",
    "ProviderInfo",
    "ProviderSet",
    "TtsProvider",
    "TtsRequest",
    "TtsResult",
    "build_provider_set",
]
