"""Hợp đồng dữ liệu và state machine của AI-VIDEO-AGENT."""

from __future__ import annotations

from ai_video_agent.domain.assets import AssetEntry, AssetManifest, Consent, sha256_file
from ai_video_agent.domain.enums import (
    AspectRatio,
    AssetKind,
    BrollKind,
    ConsentStatus,
    OnScreenTextKind,
    ProjectState,
    ProviderKind,
    ProviderMode,
    RenderStage,
    SceneRole,
    StageStatus,
)
from ai_video_agent.domain.project import (
    AiDisclosure,
    Approval,
    BudgetPolicy,
    Project,
    ProviderSelection,
    TransitionRecord,
)
from ai_video_agent.domain.render import CostLine, RenderManifest, RenderRecord
from ai_video_agent.domain.state import (
    ALLOWED_TRANSITIONS,
    assert_transition,
    can_transition,
    next_states,
)
from ai_video_agent.domain.storyboard import BrollPlan, OnScreenText, Scene, Shot, Storyboard

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AiDisclosure",
    "Approval",
    "AspectRatio",
    "AssetEntry",
    "AssetKind",
    "AssetManifest",
    "BrollKind",
    "BrollPlan",
    "BudgetPolicy",
    "Consent",
    "ConsentStatus",
    "CostLine",
    "OnScreenText",
    "OnScreenTextKind",
    "Project",
    "ProjectState",
    "ProviderKind",
    "ProviderMode",
    "ProviderSelection",
    "RenderManifest",
    "RenderRecord",
    "RenderStage",
    "Scene",
    "SceneRole",
    "Shot",
    "StageStatus",
    "Storyboard",
    "TransitionRecord",
    "assert_transition",
    "can_transition",
    "next_states",
    "sha256_file",
]
