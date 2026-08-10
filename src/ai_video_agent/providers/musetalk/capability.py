"""Năng lực đã xác minh của MuseTalk 1.5.

**Mọi con số ở đây đo thật trên máy này** ở bake-off D04, nguồn là
``D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md`` §7 và ``D04G_MUSETALK_BAKEOFF_DESIGN.md``
§1/§3 (cả hai đã commit) — không chép từ tài liệu upstream.

Tách thành module riêng để mock và adapter thật dùng chung đúng một nguồn sự
thật, giống cách ``providers/duix/capability.py`` đã làm.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from ai_video_agent.providers.base import AvatarCapability, ResourceEstimate
from ai_video_agent.providers.pricing import PriceBook

#: Gate riêng của backend này. **Cố ý KHÔNG nằm trong** ``ai_video_agent.GATES``:
#: ``gate_is_open()`` từ chối mọi tên gate lạ, nên khai chuỗi này là gate đóng
#: theo cấu trúc, không phụ thuộc vào ai nhớ đóng nó. Mở D04G = thêm tên vào
#: ``GATES`` — một sửa đổi thấy được trong diff, không phải một cờ cấu hình.
GATE = "D04G"

#: Commit đã ghim của repo upstream (bake-off §11, đã xác minh bằng ``git log``).
REPO_COMMIT = "0a89dec45a0192b824e3cf4daf96c239440c5ed8"

#: SHA-256 của trọng số chính. Nguồn: ``weights/musetalk-weights-manifest.json``.
UNET_SHA256 = "7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007"

#: Đường dẫn **tương đối** so với ``Config.runtime_dir``. Cố ý không viết đường
#: tuyệt đối vào source: máy khác có ổ khác, và repo không được chứa đường dẫn
#: dữ liệu thật (ADR-0002).
INSTALL_SUBPATH = PurePosixPath("model-bakeoff/repos/MuseTalk")

#: File bắt buộc phải có mặt thì adapter mới chạy được. Thiếu bất kỳ file nào
#: là hỏng ngay với thông điệp rõ, không phải chạy nửa chừng rồi mới lộ.
REQUIRED_WEIGHTS: tuple[str, ...] = (
    "models/musetalkV15/unet.pth",
    "models/musetalkV15/musetalk.json",
    "models/sd-vae/diffusion_pytorch_model.bin",
    "models/whisper/pytorch_model.bin",
    "models/dwpose/dw-ll_ucoco_384.pth",
    "models/face-parse-bisent/79999_iter.pth",
    "models/face-parse-bisent/resnet18-5c106cde.pth",
)

#: Chạy local trong WSL bằng GPU của máy — không tốn tiền API. Dựng ở đây thay
#: vì thêm vào ``providers/pricing.py``: batch D04-G không được sửa pricing dùng
#: chung, và giả định của MuseTalk khác Duix (WSL, không phải Docker).
MUSETALK_LOCAL = PriceBook(
    unit="second",
    unit_price_usd=0.0,
    billable=False,
    assumption="MuseTalk 1.5 (MIT) chạy local trong WSL2 + GPU của máy. Chi phí = thời gian GPU.",
)

#: Đo ở bake-off D04 cho clip 7,6 s ở 1080x1920. **fps đổi thì VRAM đổi thật** —
#: 25 fps sinh 192 khung, 30 fps sinh 230 khung, và cả hai số dưới đây đều đo
#: trên chính máy này (báo cáo bake-off §7).
#:
#: Khai một con số cho mọi fps là sai theo cả hai chiều: lấy số 30 fps cho lượt
#: 25 fps thì hàng rào chặn nhầm một cấu hình chạy được; lấy số 25 fps cho lượt
#: 30 fps thì nó cho qua rồi OOM giữa chừng.
#: Peak VRAM quan sát được trên đường chạy production của D04-G. **Cao hơn số
#: bake-off rất nhiều**, và đây là số được dùng để đặt ngưỡng cho 25 fps:
#:
#: * ``f16bd2a245d4`` — 10.418 MiB. Run **INVALID/INCONCLUSIVE** (nguồn 30 fps
#:   nên MuseTalk sinh 30 fps dù truyền ``--fps 25``). Giữ làm bằng chứng, không
#:   dùng làm cơ sở kết luận.
#: * ``10a88c290ee8`` — 10.354 MiB. Run **D04-G2 HỢP LỆ**: nguồn/avatar/output
#:   đều đo được 25/1 fps.
#:
#: Bake-off từng ghi 9.118 MiB cho 25 fps, nhưng con số đó **không tái lập được**
#: trên đường production — hai run độc lập đều cho ~10,4 GB. Nguyên nhân nhiều
#: khả năng là khác biệt kích thước/độ dài nguồn và cách adapter đo (lấy mẫu
#: 1 s bắt được đỉnh mà script bake-off có thể bỏ lỡ).
D04G_OBSERVED_PEAK_25FPS_MIB = 10_354

MUSETALK_RESOURCES_BY_FPS: dict[int, ResourceEstimate] = {
    25: ResourceEstimate(
        #: Bảo thủ hơn đỉnh hợp lệ đã quan sát (10.354) một biên ~250 MiB.
        #: Khai thấp hơn số đã đo là để hàng rào cho qua rồi OOM giữa chừng —
        #: đúng thứ ``ResourceEstimate`` sinh ra để chặn.
        vram_mib=10_600,
        ram_mib=15_360,
        storage_mib=30_720,
        deterministic_local=True,
        measured=True,
        #: Ngày của run D04-G2, không phải ngày bake-off: con số này đến từ
        #: thực nghiệm production, không phải từ báo cáo cũ.
        measured_on="2026-08-10",
    ),
    30: ResourceEstimate(
        vram_mib=9_798,
        ram_mib=15_360,
        storage_mib=30_720,
        deterministic_local=True,
        measured=True,
        measured_on="2026-08-06",
    ),
}

#: Mặc định khai theo **30 fps** — cấu hình chính thức của D04G design §5.2, và
#: là số cao hơn, nên nơi nào chưa biết fps thì vẫn an toàn theo hướng đúng.
MUSETALK_RESOURCES = MUSETALK_RESOURCES_BY_FPS[30]

MUSETALK_CAPABILITY = AvatarCapability(
    backend_id="musetalk",
    backend_version=f"musetalk-v15@{REPO_COMMIT[:8]}",
    #: fps huấn luyện chính thức là 25. Chạy 30 được nhưng ngoài điều kiện
    #: huấn luyện — bake-off đo r 0,272 @30 so với 0,320 @25.
    native_fps=25,
    supported_fps=frozenset({25, 30}),
    max_width=1920,
    max_height=1920,
    audio_sample_rate_hz=48_000,
    audio_channels=1,
    #: Điểm khác biệt cốt lõi so với Duix. Whisper là bộ mã hoá **đa ngôn ngữ**,
    #: nên `language_is_verified()` trả True cho 'vi' và pipeline KHÔNG phát
    #: cảnh báo ngôn ngữ. Đó là toàn bộ giả thuyết mà D04-G đi kiểm.
    audio_encoder="whisper-tiny",
    languages_verified=frozenset({"multi"}),
    accepts_image_source=True,
    accepts_video_source=True,
    requires_gate=GATE,
    resources=MUSETALK_RESOURCES,
    source_url="https://github.com/TMElyralab/MuseTalk",
)
