# D04-A — KẾ HOẠCH NÂNG CẤP LIP-SYNC, GIỮ KIẾN TRÚC THAY MODEL ĐƯỢC

> **Tài liệu thiết kế. Chưa triển khai adapter mới, chưa tải model, chưa gọi API.**
> `CURRENT_GATE = "D04"` · repo `F:\AI-VIDEO-AGENT` · HEAD `ac128c1`

Mục tiêu: chuẩn bị đường thay Duix bằng model lip-sync tiếng Việt tốt hơn
(ưu tiên MuseTalk 1.5), **nhưng không khoá pipeline vào bất kỳ model nào** — kể cả
MuseTalk.

---

## 0. Một mâu thuẫn trong hồ sơ, phải ghi rõ

`D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md` §0 ghi quyết định của PO ngày 2026-08-06:

> **A — Duix: PRODUCTION WINNER** · **B — MuseTalk 1.5: LOẠI**

Batch D04-A này lại đặt MuseTalk làm ưu tiên. Đó là quyền của PO, nhưng hai tài
liệu sẽ mâu thuẫn nếu không ai ghi lại lý do. Kế hoạch này **không** tự ý lật
quyết định cũ; nó chuẩn bị *đường đi* để việc lật (nếu PO muốn) là một thao tác
cấu hình chứ không phải một đợt refactor.

Dữ kiện làm nền cho việc xem lại, tất cả đã đo trên chính máy này (bake-off §7):

| | Duix (winner hiện tại) | MuseTalk 1.5 |
|---|---|---|
| Bộ mã hoá tiếng | **WeNet / AISHELL — tiếng Quan Thoại** | **Whisper — đa ngôn ngữ** |
| Giấy phép | cộng đồng riêng, phải đọc nguyên văn | **MIT**, code lẫn weights |
| A/V lệch | 0,080 s (cụt đuôi) | **0,000 s** |
| Peak VRAM | 7.004 MiB | 9.118 MiB |
| Thời gian render 7,6 s | **22,3 s** | 210,8 s |
| Độ nét vùng miệng | **7,26** | 4,77 |
| fps gốc | **30 (native dự án)** | 25 |

Điểm đáng xem lại nhất là dòng đầu: **Duix dẫn khẩu hình bằng ASR tiếng Trung.**
Đó là trần chất lượng cho tiếng Việt, không phải lỗi cấu hình (memory dự án và
bake-off §14.2 đều ghi). MuseTalk dùng Whisper đa ngôn ngữ — về nguyên lý là
hướng đúng, dù bake-off cho thấy nó **kém hơn về độ nét và chậm hơn 9,5 lần**.

---

## 1. Luồng hiện tại

```
brief tiếng Việt
   └─ planner ──────────────► storyboard.json (shots, provider_hint)
        │
        ├─ RenderStage.TTS      VieNeuTtsProvider   → audio.wav (48 kHz mono)
        │                                              gate D02, local, 0 USD
        ├─ RenderStage.AVATAR   DuixAvatarProvider  → avatar.mp4  ◄── ĐIỂM THAY MODEL
        │                       AvatarRequest{audio_path, avatar_source, w, h, fps, seed}
        │                       AvatarResult{path, duration, w, h, fps, is_placeholder}
        │                                              gate D03, local GPU, 0 USD
        ├─ RenderStage.BROLL    VideoApiBrollProvider → broll.mp4 + broll.qc.json
        │                                              gate D05, TRẢ PHÍ, đang đóng
        ├─ RenderStage.SUBTITLE FfmpegComposer      → subtitles.srt
        └─ RenderStage.COMPOSE  FfmpegComposer      → <project>-<run>.mp4 1080×1920
             ▲
             └─ _assert_paid_broll_approved()  (QC + HUMAN_APPROVED, chỉ cho B-roll trả phí)
```

**QC hiện có** (`qc/broll.py`) mới áp cho **B-roll**, chưa áp cho avatar. Xem §6.

---

## 2. Interface hiện có và các điểm phụ thuộc cứng vào Duix

### 2.1 Hợp đồng đã tồn tại — không cần phát minh lại

`providers/base.py` đã có `AvatarProvider` Protocol với `info()` / `quote()` /
`generate(request, out_path) -> AvatarResult`. Đây là hợp đồng đúng hướng; vấn
đề **không** nằm ở Protocol.

### 2.2 Bảy điểm khoá cứng vào Duix

| # | Vị trí | Nội dung | Mức |
|---|---|---|---|
| 1 | `registry.py:28` | `KNOWN_AVATAR = frozenset({"duix"})` — danh sách trắng đúng một phần tử | **chặn** |
| 2 | `registry.py:44-59` | `_build_avatar()` gọi thẳng `DuixAvatarProvider(...)` với tham số riêng của Duix | **chặn** |
| 3 | `config.py:67-80` | 5 trường cấp cao nhất mang tên Duix: `duix_base_url`, `duix_timeout_sec`, `duix_inputs_mount`, `duix_image_digest`, `duix_data_dir` | cao |
| 4 | `domain/project.py:83` | `ProviderSelection.avatar: str = "duix"` | thấp (mặc định, đổi được) |
| 5 | `domain/storyboard.py:59` + `planner.py:161` | `provider_hint = "duix"` | thấp |
| 6 | `providers/pricing.py:42` | `DUIX_LOCAL` — tên riêng cho một khái niệm chung "lip-sync local" | trung bình |
| 7 | `cli/doctor.py:25-33` | cổng 8383/18180/10095 và `DUIX_RECOMMENDED_GB = 100` | thấp (chẩn đoán) |

**Điểm 1 và 2 là thứ thật sự chặn.** Còn lại chỉ là đặt tên và mặc định.

### 2.3 Ba thứ hợp đồng hiện **thiếu** để thay model an toàn

| Thiếu | Vì sao cần |
|---|---|
| **Capability** | MuseTalk gốc 25 fps, Duix 30 fps. Không khai năng lực thì pipeline phải đoán, hoặc lặp lại đúng lỗi "SDK có field ≠ model hỗ trợ" đã gặp ở D05-C §1 |
| **Ước tính VRAM/RAM** | 12 GB VRAM là ràng buộc cứng của máy. Phải từ chối **trước** khi nạp model, không phải sau khi OOM |
| **Provenance** | `AvatarResult` không mang model/version/checkpoint hash. Không truy vết được video nào do model nào sinh |

---

## 3. Thiết kế adapter lip-sync chuẩn

Nguyên tắc: **mở rộng, không phá vỡ.** `AvatarProvider` giữ nguyên ba phương
thức; ba thứ thiếu ở §2.3 được thêm dưới dạng **tuỳ chọn có mặc định**, nên
Duix hiện tại vẫn hợp lệ mà không phải sửa dòng nào.

### 3.1 Khai báo năng lực

```python
@dataclass(frozen=True)
class LipSyncCapability:
    backend_id: str                    # "duix" | "musetalk" | ...
    native_fps: int                    # Duix 30, MuseTalk 25
    supported_fps: frozenset[int]      # tập fps model thật sự nhận
    max_width: int
    max_height: int
    audio_sample_rate_hz: int          # tốc độ mẫu model muốn ở đầu vào
    audio_encoder: str                 # "wenet-aishell" | "whisper" — quyết định chất lượng tiếng Việt
    languages_verified: frozenset[str] # {"zh"} với Duix, {"multi"} với Whisper
    supports_image_source: bool
    supports_video_source: bool
    deterministic_with_seed: bool
    est_vram_mib: int                  # ĐO THẬT, không phải con số tài liệu
    est_ram_mib: int
    source_url: str
    measured_on: date                  # ngày đo, để biết số liệu còn tươi không
```

**Quy tắc bắt buộc, rút ra từ D05-C §1:** `est_vram_mib` phải là **số đã đo trên
máy này**, không phải số trong README của upstream. LatentSync ghi 18 GB trong
tài liệu nhưng đo thật là 11.942 MiB — chênh 34%. Tin tài liệu là loại nhầm một
ứng viên chạy được.

### 3.2 Kiểm tương thích **trước** khi chạm GPU

```python
def check_lipsync_request(cap: LipSyncCapability, req: AvatarRequest,
                          available_vram_mib: int) -> None:
    # fps không hỗ trợ            -> CapabilityError
    # kích thước vượt trần        -> CapabilityError
    # nguồn là ảnh mà model không nhận ảnh -> CapabilityError
    # est_vram_mib > available    -> CapabilityError, nêu rõ cần bao nhiêu
```

Dùng lại nguyên mẫu `providers/video_api/capability.py` đã viết ở D05-C — cùng
triết lý, cùng lớp lỗi `CapabilityError`, chết **trước** provider boundary.

### 3.3 Provenance trong kết quả

```python
@dataclass(frozen=True)
class LipSyncProvenance:
    backend_id: str
    model: str
    model_version: str
    checkpoint_sha256: str      # "" nếu nằm trong Docker image
    image_digest: str           # cho backend chạy container
    source_fps: int             # fps model THỰC SỰ xuất ra
    audio_encoder: str
    params: dict[str, str]      # tham số inference thật, để tái lập
    peak_vram_mib: int | None
    render_seconds: float
```

Gắn vào `AvatarResult` dưới dạng `provenance: LipSyncProvenance | None = None`
và ghi vào `render-manifest.json`. Đây là thứ để sau này nhìn một video bất kỳ
và biết ngay model nào sinh ra nó với tham số gì.

### 3.4 Registry mở

Thay hai điểm chặn ở §2.2:

```python
AVATAR_BACKENDS: dict[str, AvatarBackendSpec] = {
    "duix":     AvatarBackendSpec(real=_build_duix,     mock=MockDuixAvatarProvider,
                                  capability=DUIX_CAPABILITY),
    "musetalk": AvatarBackendSpec(real=_build_musetalk, mock=MockMuseTalkProvider,
                                  capability=MUSETALK_CAPABILITY),
}
KNOWN_AVATAR = frozenset(AVATAR_BACKENDS)   # tự suy ra, không gõ tay
```

`KNOWN_AVATAR` **suy ra từ registry** thay vì khai riêng — quên đăng ký thì
không thể quên cập nhật danh sách trắng.

### 3.5 Cấu hình theo backend

Gom cấu hình riêng của từng backend vào một khoá lồng, thay vì rải ở cấp cao nhất:

```
AIVA_AVATAR_BACKEND=duix|musetalk
AIVA_DUIX_BASE_URL=...            (giữ nguyên, tương thích ngược)
AIVA_MUSETALK_ENV_PATH=...        (mới, chỉ dùng khi backend=musetalk)
```

Giữ nguyên tên biến Duix cũ để không phá cấu hình đang chạy.

---

## 4. MuseTalk 1.5 — tương thích, chỉ dựa trên dữ liệu đã có trong repo

Nguồn: `D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md` (đã commit). **Không tải gì thêm.**

| Tiêu chí | Kết quả đã đo | Đánh giá |
|---|---|---|
| **RTX 4070 SUPER 12 GB** | peak **9.118 MiB** ở 25fps, **9.798 MiB** ở 30fps | **Chạy được.** Dư ~2,5 GB ở 25fps. Nhưng lưu ý: máy có 1.700–4.000 MiB bị desktop chiếm, nên biên thật hẹp hơn |
| **WSL2** | đã chạy thật trong WSL2 Ubuntu, GPU passthrough OK | **Được.** venv Python 3.10, torch 2.0.1+cu118, mmcv 2.0.1, mmdet 3.1.0, mmpose 1.1.0 |
| **Tiếng Việt** | bộ mã hoá **Whisper** — đa ngôn ngữ | **Về nguyên lý phù hợp hơn Duix.** Nhưng bake-off §8: r chỉ 0,320 so với 0,264 của Duix — khá hơn nhưng cả hai đều thấp |
| **Giấy phép** | **MIT** cho cả code lẫn weights, "even commercially" | **Sạch nhất trong 4 ứng viên** |
| **fps** | gốc 25; chạy được 30 nhưng ngoài điều kiện huấn luyện | Cần bước 25→30, hoặc chấp nhận 30 với chất lượng có thể kém hơn |
| **Thời gian render** | 210,8 s cho 7,6 s video | **Chậm hơn Duix 9,5 lần.** Video 60 s ước ~28 phút |
| **Độ nét vùng miệng** | 4,77 (Duix 7,26; nguồn gốc 8,11) | **Kém hơn rõ rệt** — đây là lý do PO loại nó |

### Bốn rào cản triển khai đã biết, không phải suy đoán

1. **`chumpy` không build được** trên setuptools mới. Cách đã dùng: cài `mmpose`
   với `--no-deps` cộng phụ thuộc runtime thật; MuseTalk chỉ dùng DWPose 2D nên
   không cần SMPL.
2. **`setuptools` bị gỡ** khỏi venv trong các bước `--force-reinstall`, làm
   `mmengine.get_installed_path()` hỏng. Phải ghim lại.
3. **numpy phải là 1.23.5.** Các gói native build theo nó; để pip đẩy lên 2.x là
   `mmcv`/`cv2` gãy.
4. **`download_weights.bat` của upstream đặt `HF_ENDPOINT=hf-mirror.com`** — mirror
   bên thứ ba. Phải tải từ `huggingface.co` chính thức (quy tắc nguồn chính thức).

### Ba điều **chưa** biết

- MuseTalk có tránh được scene jump / méo môi trên clip dài hơn 8 s không.
- Chất lượng ở 30 fps so với 25 fps — mới có một mẫu mỗi bên.
- Thời gian render có giảm được bằng `--batch_size` lớn hơn không (VRAM còn ~2,5 GB).

---

## 5. Kế hoạch thử MuseTalk bằng bản sample ngắn

**Chưa chạy. Cần PO duyệt từng bước.**

| Bước | Nội dung | Tốn gì |
|---|---|---|
| A | Viết `MockMuseTalkProvider` + capability declaration. Test contract §7 phủ luôn | 0 |
| B | Viết `MuseTalkAvatarProvider` (adapter thật), gate D04, chưa chạy | 0 |
| C | Dựng lại venv WSL2 theo đúng 4 rào cản §4 | ~7,5 GB đĩa WSL |
| D | Tải weights từ nguồn chính thức | ~4,2 GB trên ổ F |
| E | **Chạy 1 sample 5–8 s** bằng golden audio + avatar nguồn hiện có | ~4 phút GPU |
| F | Chấm theo tiêu chí §6, so trực tiếp với `A_duix_baseline.mp4` | 0 |

Đầu vào dùng lại nguyên bản đã chuẩn hoá ở bake-off: `inputs/golden_48k.wav`
(hash khớp golden gốc) và `inputs/source_25fps_8s.mp4`. **Không tạo TTS mới,
không đổi nội dung hay độ dài lời nói.**

---

## 6. Tiêu chí chấm

### 6.1 Tầng máy — có quyền từ chối, không có quyền chấp nhận

Dùng lại bộ QC ở `qc/broll.py`, **mở rộng cho avatar**:

| Phép kiểm | Ngưỡng | Ghi chú |
|---|---|---|
| Giải mã sạch | không dòng lỗi nào | đã có |
| Độ phân giải | khớp chính xác 1080×1920 | đã có |
| fps nguồn | khớp `capability.native_fps` | đã có |
| Thời lượng | lệch ≤ 0,10 s so với WAV | đã có |
| Cắt cảnh | `scene_score` — **ngưỡng 0,10 vẫn PROVISIONAL** | đã có, chưa hiệu chuẩn |
| **A/V lệch** | ≤ 0,02 s | *mới cho avatar* |
| **Khẩu hình ~ tiếng** | r và độ trễ tại đỉnh | *mới* — xem cảnh báo dưới |
| **Độ nét vùng miệng** | so với nguồn gốc (8,11) | *mới* |

> **Cảnh báo về metric khẩu hình.** Bake-off §8 ghi rõ: r của Duix là 0,264 trong
> khi một tín hiệu **hoàn toàn không liên quan** cũng đạt 0,218 do trùng hợp.
> Biên phân biệt quá hẹp. Metric này **chỉ để đối chiếu tương đối giữa các model
> trên cùng đoạn tiếng**, tuyệt đối không dùng làm bằng chứng "khẩu hình đã đạt".

### 6.2 Tầng người — quyết định cuối

Chân thật, không morphing/méo, môi khớp âm tiết tiếng Việt, ánh sáng nhất quán,
**đủ đẹp để đăng chính thức**. Máy không bao giờ được tự tuyên bố đạt thẩm mỹ.

### 6.3 Ngưỡng vận hành

| | Chấp nhận được | Đáng lo |
|---|---|---|
| Peak VRAM | ≤ 10.000 MiB | > 11.000 MiB (biên < 1 GB) |
| Render / giây video | ≤ 30 s | > 30 s |
| A/V lệch | ≤ 0,02 s | > 0,05 s |

---

## 7. Test contract cho adapter

**Đã triển khai** trong `tests/test_d04a_avatar_contract.py` — 19 test, dùng đúng
pattern parametrize sẵn có của `tests/test_providers.py`.

Thêm backend mới = thêm một dòng vào `AVATAR_BACKENDS`, toàn bộ hợp đồng áp lên
nó ngay. Các điều khoản, mỗi cái đến từ một lỗi có thật của dự án:

| Điều khoản | Bài học gốc |
|---|---|
| `quote()` chạy khi **chưa có WAV** | `estimate` và `--dry-run` chạy trước TTS |
| `quote()` không nạp model, không chạm GPU | xem giá phải rẻ |
| `info()` khai đủ name/model/version/gate | không có version thì không truy vết được |
| Adapter thật **chặn theo gate của chính nó** | hàng rào gate là cốt lõi của dự án |
| Adapter thật **gọi `gate_is_open` thật**, hỏi đúng gate đã khai | chống hardcode hàng rào |
| Không import SDK nặng ở cấp module | AGENTS.md §Ranh giới |
| `AvatarResult.path` trỏ tới **file có thật** | D05-C FIX 3: pipeline từng tin đường *yêu cầu* thay vì đường *đã ghi* |
| Mock deterministic | nền tảng của test tái lập |
| Mock lấy thời lượng từ **WAV thật** | TTS sinh sai độ dài phải bị bắt |
| Mọi backend trong `KNOWN_AVATAR` đều được hợp đồng phủ | quên đăng ký = lọt lưới |

Một chi tiết đáng nói: điều khoản gate ban đầu tôi viết dạng `skip` khi gate đang
mở — và vì gate của Duix là D03 còn `CURRENT_GATE` là D04, nó **luôn bị bỏ qua**.
Điều khoản quan trọng nhất của hợp đồng chưa từng chạy. Đã sửa thành ép gate đóng
bằng `monkeypatch`, nên nó kiểm thật: 19 pass, **0 skip**.

---

## 8. Checkpoint và rollback

### Checkpoint trước khi bắt đầu bước C của §5

```
branch main · HEAD ac128c1 · worktree sạch · CURRENT_GATE = "D04"
avatar-goc.mp4  71cf0baa2f4506f95019c0ccffd702bfff6c29f1b7b18e96c08c73c7271180da
golden          311471e7d059ba11245586e18d5ff2b6a5eda5b81f1a48a2af4d7d2e6253985c
Duix baseline   5f7ce378e128317b2bfc6babfd8c909569966f8b071aba23e6fef04276eecb7f
```

Lệch bất kỳ dòng nào ⇒ dừng, báo, **không** tải model.

### Ranh giới rollback

| Lớp | Trạng thái | Cách quay lại |
|---|---|---|
| **Production hiện tại** | Duix + VieNeu + FFmpeg, 0 USD, 100% local | Không phụ thuộc gì vào MuseTalk |
| Registry | `KNOWN_AVATAR` mở rộng nhưng mặc định vẫn `"duix"` | Đổi một dòng cấu hình |
| Adapter mới | file riêng, không sửa `duix/adapter.py` | Xoá file, gỡ một dòng registry |
| Weights MuseTalk | ~4,2 GB ngoài Git, dưới `model-bakeoff/` | Xoá thư mục |
| Video đối chứng | `A_duix_baseline.mp4` giữ nguyên, **không ghi đè** | — |
| Git | 2 commit, không remote | `git revert` — **không** dùng reset/force |

**Bất biến tuyệt đối:** video nguồn và golden voice không bao giờ được sửa. Duix
adapter không bị đụng cho tới khi PO chốt đổi model.

---

## 9. Đường nâng cấp về sau

### 9.1 Lên GPU lớn hơn (32 GB)

Ràng buộc 12 GB đang loại bỏ hoặc bóp nghẹt nhiều lựa chọn. Với 32 GB:

| Mở ra được | Vì sao hiện chưa được |
|---|---|
| LatentSync 1.6 chạy thoải mái | nay peak 11.942/12.282 MiB — dư **340 MiB**, không tái lập ổn định |
| `--batch_size` lớn hơn cho MuseTalk | có thể cắt đáng kể 210,8 s |
| Chạy hai model song song để so trực tiếp | quy tắc bake-off buộc chạy tuần tự vì 12 GB |
| Model 1080p native, không phải upscale | — |

**Việc cần làm khi đổi GPU:** đo lại **toàn bộ** `est_vram_mib` trong capability.
Con số cũ vô giá trị trên phần cứng mới.

### 9.2 Model mạnh hơn

Kiến trúc ở §3 khiến việc thêm ứng viên chỉ là: viết capability + adapter + một
dòng registry + một dòng `AVATAR_BACKENDS` trong test contract. Ba ứng viên đã
khảo sát mà chưa dùng:

| Ứng viên | Trạng thái |
|---|---|
| LatentSync 1.5 | **backup chính thức của PO**. Môi trường + weights đã dựng, tái lập được ngay |
| LatentSync 1.6 | Apache-2.0 + openrail++, cần > 12 GB để ổn định |
| Ditto (`antgroup/ditto-talkinghead`) | Apache-2.0, đã khảo sát, **hoãn** để bảo vệ hạn mức 40 GB |

### 9.3 Hướng ngoài phạm vi lip-sync

Nếu cả họ lip-sync đều không đạt cho tiếng Việt, hướng còn lại là **fine-tune bộ
mã hoá tiếng trên dữ liệu tiếng Việt** — việc này cần gate riêng, dữ liệu có
consent, và phần cứng lớn hơn nhiều.

---

## 10. Việc batch này ĐÃ làm và CHƯA làm

**Đã:** map luồng · liệt kê 7 điểm khoá cứng · thiết kế hợp đồng adapter ·
đối chiếu MuseTalk từ dữ liệu đã đo trong repo · **19 test contract chạy được** ·
tài liệu này.

**Chưa:** không viết adapter MuseTalk · không sửa `registry.py` / `config.py` /
`duix/adapter.py` · không tải model · không chạy GPU · không gọi API · không commit.

---

D04A_STATUS = THIẾT KẾ XONG, CHỜ PO DUYỆT BƯỚC TIẾP
