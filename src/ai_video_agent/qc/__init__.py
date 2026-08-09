"""Kiểm tra chất lượng tự động cho tài sản sinh bằng model.

QC ở đây **chỉ có quyền từ chối**. Không hàm nào trong gói này được phép cấp
``HUMAN_APPROVED`` — đó là quyết định của con người (D05-C §7.5).
"""

from ai_video_agent.qc.broll import (
    GOLDEN_POSITIVE,
    PROVISIONAL_SCENE_THRESHOLD,
    CheckResult,
    QcReport,
    detect_scene_cuts,
    run_qc,
)

__all__ = [
    "GOLDEN_POSITIVE",
    "PROVISIONAL_SCENE_THRESHOLD",
    "CheckResult",
    "QcReport",
    "detect_scene_cuts",
    "run_qc",
]
