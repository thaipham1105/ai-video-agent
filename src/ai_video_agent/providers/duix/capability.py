"""Năng lực đã xác minh của Duix-Avatar.

**Mọi con số ở đây đo thật trên máy này**, nguồn là
``D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md`` §7 (đã commit), không phải chép từ tài
liệu upstream.

Tách thành module riêng để mock và adapter thật dùng chung đúng một nguồn sự
thật — mock khai rộng hơn bản thật là kiểu lỗi khiến test xanh rồi vỡ khi chạy.
"""

from __future__ import annotations

from ai_video_agent.providers.base import AvatarCapability, ResourceEstimate

#: Đo ở bake-off D04: peak 7.004 MiB cho clip 7,6 s ở 1080x1920.
#: RAM và đĩa lấy theo quan sát container Duix (image 4,66 GB + dữ liệu tạm).
DUIX_RESOURCES = ResourceEstimate(
    vram_mib=7_004,
    ram_mib=4_096,
    storage_mib=5_120,
    #: Duix sinh tất định trên cùng đầu vào — A và C của bake-off trùng nhau
    #: từng byte khi chỉ đổi tham số vô hiệu.
    deterministic_local=True,
    measured=True,
    measured_on="2026-08-05",
)

DUIX_CAPABILITY = AvatarCapability(
    backend_id="duix",
    backend_version="duix.avatar@sha256:1970424d",
    #: Duix chạy đúng fps của video nguồn; dự án dùng 30.
    native_fps=30,
    supported_fps=frozenset({24, 25, 30}),
    max_width=1920,
    max_height=1920,
    audio_sample_rate_hz=48_000,
    audio_channels=1,
    #: Điểm quan trọng nhất của khối này. Duix nội bộ hạ audio xuống 16 kHz rồi
    #: trích đặc trưng bằng WeNet huấn luyện trên AISHELL — kho ngữ liệu tiếng
    #: Quan Thoại. Đây là trần chất lượng khẩu hình tiếng Việt, không phải lỗi
    #: cấu hình (bake-off §0, §14.2).
    audio_encoder="wenet-aishell",
    languages_verified=frozenset({"zh"}),
    accepts_image_source=False,
    accepts_video_source=True,
    requires_gate="D03",
    resources=DUIX_RESOURCES,
    source_url="https://github.com/GuijiAI/duix.ai",
)
