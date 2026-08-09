# D05-C — THIẾT KẾ / PREFLIGHT (BẢN SỬA 3)

> **KHÔNG gọi API trả phí. KHÔNG render. KHÔNG phát sinh chi phí. KHÔNG sửa code.**
> **KHÔNG cấp hạn mức trả phí nào ở bước này.**

Ngày lập: 2026-08-06 · Bản sửa 3 · Repo `F:\AI-VIDEO-AGENT` · HEAD `5ec4881` · `CURRENT_GATE = "D04"`

**Nguồn ghim cho toàn bộ tài liệu này:**
- Năng lực model: <https://ai.google.dev/gemini-api/docs/veo>
- Bảng giá: <https://ai.google.dev/gemini-api/docs/pricing>
- Điều khoản: <https://ai.google.dev/gemini-api/terms>
- Tên field SDK: introspection `google-genai 2.17.0` → `d05-discovery/veo-params-verified.json`

---

## 0. Căn cứ — lỗi D05-B đã kiểm chứng bằng số

| Chỉ số | Giá trị |
|---|---|
| Vị trí cắt | `pts_time = 3.250000` — **khung 78/120** @24fps |
| `scene_score` tại điểm cắt | **0,308448** |
| `scene_score` nền của clip | 0,037 – 0,053 |
| Số khung vượt 0,10 trong cả clip | **đúng 1** |

Trích khung 75–80: hai bố cục khác hẳn — máy nhảy vị trí, trời đổi màu, hàng dừa tiền
cảnh biến mất. **Cắt cứng, không phải chuyển động máy.**

Clip này là **golden positive** cho hiệu chuẩn detector ở mục 7.

**Nhưng một clip lỗi KHÔNG chứng minh cả model kém.** Xem mục 14.

---

## 1. Năng lực đã XÁC MINH

Phân biệt hai nguồn, không được lẫn:
- **Tài liệu model** (`docs/veo`) — nói Veo 3.1 *làm được gì*.
- **Introspection SDK** (`google-genai 2.17.0`) — nói *field nào tồn tại trong thư viện*.

**Field tồn tại trong SDK tổng quát KHÔNG chứng minh model hỗ trợ.** SDK phục vụ nhiều
model; một field có mặt không có nghĩa Veo 3.1 tôn trọng nó. Nguyên tắc này quyết định
mục 1.3 và 1.4.

### 1.1 `types.GenerateVideosConfig` — tên field thật trong SDK

| Field | Kiểu | Dùng cho Veo? |
|---|---|---|
| `duration_seconds` | `Optional[int]` | **có** — 8 |
| `aspect_ratio` | `Optional[str]` | **có** — `"9:16"` |
| `resolution` | `Optional[str]` | **có** — `"1080p"` |
| `number_of_videos` | `Optional[int]` | **có** — 1 |
| `reference_images` | `Optional[list[VideoGenerationReferenceImage]]` | **có** — xem 1.5 |
| `negative_prompt` | `Optional[str]` | có |
| `seed` | `Optional[int]` | có |
| `generate_audio` | `Optional[bool]` | **KHÔNG dùng — xem 1.3** |
| `fps` | `Optional[int]` | **KHÔNG dùng — xem 1.4** |
| `person_generation`, `last_frame`, `mask`, `enhance_prompt`, `compression_quality`, `resize_mode`, `output_gcs_uri`, `labels`, `pubsub_topic`, `webhook_config`, `http_options` | — | chưa dùng |

### 1.2 Kiểu liên quan

```
types.VideoGenerationReferenceImage:
    image           : Optional[types.Image]
    reference_type  : Optional[types.VideoGenerationReferenceType]

types.VideoGenerationReferenceType  = ASSET | STYLE      (đúng 2 giá trị)
types.Image                         = gcs_uri | image_bytes | mime_type

Models.generate_videos(*, model: str, prompt: Optional[str], image, video, source, config)
```

`client.operations` tồn tại ⇒ `generate_videos()` trả **long-running operation**, phải poll.
Căn cứ cho state machine mục 5.

`client.interactions` là đường Omni Flash đã dùng ở D05-B — **đường khác**.

### 1.3 AUDIO — luôn bật, ĐÃ CHỐT

**Veo 3.1 Standard, Fast và Lite đều xuất video có audio. Audio là ALWAYS ON.**

Field `generate_audio` có trong SDK **không chứng minh Veo hỗ trợ tắt audio**. Đây đúng là
trường hợp SDK-tổng-quát ≠ năng-lực-model nêu ở đầu mục 1.

Hệ quả bắt buộc cho capability của Veo:

| Quy tắc | Nội dung |
|---|---|
| `audio_mode` | **`"always_on"`** |
| Gửi `generate_audio=False` | **KHÔNG BAO GIỜ gửi** |
| Cấu hình yêu cầu silent generation | **fail-fast** → `CapabilityError` trước khi gọi provider |
| Composer | **được phép** bỏ audio sau khi tải về |
| Giá | **vẫn tính như video có audio** — bỏ audio ở composer không giảm tiền |

**Đã loại khỏi danh sách cần thử bằng API trả phí**: không tốn một lượt render nào để thử
`generate_audio=False`.

### 1.4 FRAME RATE — cố định 24fps, ĐÃ CHỐT

**Veo 3.1 Standard/Fast/Lite xuất cố định 24 fps.**

Field `fps` có trong SDK **không phải capability của Veo**. Không coi nó là điều có thể dùng.

**Bất định "Veo có chấp nhận fps=30 không" đã BỎ. Không dự kiến thử `fps=30`.**

Hệ quả cho pipeline:

| Giai đoạn | Quy tắc |
|---|---|
| QC trước composer | **expected source fps = 24** — clip Veo phải là 24fps, khác đi là FAIL |
| Composer | **chuyển 24 fps → 30 fps** khi xuất master 1080×1920 |
| Chuyển đổi | nhân bản/bỏ khung của bộ lọc `fps`, **không nội suy chuyển động** |

### 1.5 REFERENCE IMAGE — năng lực ĐÃ XÁC MINH

Nguồn: <https://ai.google.dev/gemini-api/docs/veo>

| Model ID | `reference_images` | Ảnh khởi tạo (image-to-video) |
|---|---|---|
| `veo-3.1-generate-preview` (Standard) | **có — tối đa 3** | có |
| `veo-3.1-fast-generate-preview` (Fast) | **có — tối đa 3** | có |
| `veo-3.1-lite-generate-preview` (Lite) | **KHÔNG hỗ trợ** | **có** |

Thêm ràng buộc đã xác minh: **1080p bắt buộc `duration_seconds = 8`.**

Ảnh khởi tạo đi qua tham số `image=` của `generate_videos()`, **khác** `reference_images`
trong `config`. Hai đường riêng biệt — routing phải phân biệt.

`reference_type` chỉ nhận **`ASSET`** hoặc **`STYLE`**.

Bốn điều trên **không còn là bất định**, đã chuyển sang năng lực đã xác minh.

---

## 2. Cấu hình lượt thử production dự kiến

| Tham số | Giá trị |
|---|---|
| `model` | **`veo-3.1-generate-preview`** |
| `aspect_ratio` | `"9:16"` |
| `resolution` | `"1080p"` |
| `duration_seconds` | **`8`** (bắt buộc ở 1080p) |
| `number_of_videos` | `1` |
| audio | **always on** — không gửi `generate_audio` |
| fps đầu ra | **24, cố định** — không gửi `fps` |

### Chi phí

Nguồn: <https://ai.google.dev/gemini-api/docs/pricing> (trang ghi cập nhật 2026-08-05)

```
8 giây × 0,40 USD/giây = 3,20 USD
```

**Trần lượt thử chính xác: 3,20 USD.**

**Bước này KHÔNG cấp hạn mức trả phí nào.** Con số chỉ để PO cân nhắc ở một quyết định riêng.

---

## 3. Bảng giá đã ghim

| Model | Độ phân giải | USD/giây | Clip 8s |
|---|---|---|---|
| `veo-3.1-generate-preview` | 1080p | **0,40** | **3,20** |
| `veo-3.1-fast-generate-preview` | 1080p | **0,12** | 0,96 |
| `veo-3.1-lite-generate-preview` | 1080p | **0,08** | 0,64 |
| `gemini-omni-flash-preview` | 720p | 0,10 | 0,80 |

Nguồn: <https://ai.google.dev/gemini-api/docs/pricing>

---

## 4. Model routing

### 4.1 Bảng định tuyến

| Tình huống | Model | Giá | Căn cứ |
|---|---|---|---|
| **Draft tiết kiệm** | `veo-3.1-lite-generate-preview` 1080p | 0,08 USD/s | rẻ nhất, vẫn 1080p |
| **Draft cần ảnh tham chiếu** | `veo-3.1-fast-generate-preview` 1080p | 0,12 USD/s | Lite không có `reference_images` |
| **Ứng viên chất lượng production** | `veo-3.1-generate-preview` 1080p | 0,40 USD/s | bậc cao nhất — **chưa phải winner** |
| **Ứng viên đã đánh giá** | `gemini-omni-flash-preview` 720p | 0,10 USD/s | **giữ trong kiến trúc**, đã có kết quả D05-B |

### 4.2 Kiểm tra capability TRƯỚC khi gọi provider

Routing phải từ chối cấu hình bất hợp lệ **trước khi** chạm provider — không để provider
từ chối sau khi đã có khả năng bị tính tiền.

```
capability(model) -> {
    supports_reference_images: bool,
    max_reference_images: int,
    supports_initial_image: bool,
    supported_resolutions: set[str],
    supported_aspect_ratios: set[str],
    duration_constraint: dict[resolution, allowed_seconds],
    audio_mode: "always_on",
    output_fps: 24,
}
```

Quy tắc fail-fast:

| Cấu hình | Kết quả |
|---|---|
| Lite + `reference_images` không rỗng | **`CapabilityError`** |
| `reference_images` > 3 (Standard/Fast) | **`CapabilityError`** |
| `resolution="1080p"` + `duration_seconds != 8` | **`CapabilityError`** |
| Yêu cầu **silent generation** trên Veo | **`CapabilityError`** — audio always on |
| Yêu cầu **fps ≠ 24** từ Veo | **`CapabilityError`** — Veo cố định 24 |
| `aspect_ratio` ngoài danh sách hỗ trợ | **`CapabilityError`** |

---

## 5. Exactly-one submission

### 5.1 State machine

```
AUTHORIZED
   │  (PO duyệt hạn mức cho đúng một lượt)
   ▼
[ghi + flush SUBMITTING xuống đĩa]      ← WRITE-AHEAD, trước khi chạm mạng
   ▼
SUBMITTING ──────────► SUBMISSION_UNKNOWN
   │                          │
   │                          └─► CHẶN resubmit tự động
   │                              yêu cầu manual reconciliation
   ▼
SUBMITTED  (operation_name ĐÃ ghi + flush)
   ▼
POLLING    (được retry — không tạo generation mới)
   ▼
DOWNLOADED (được retry từ operation/file đã có)
   ▼
QC_PENDING
   ▼
HUMAN_APPROVED  ──hoặc──  REJECTED
```

### 5.2 Write-ahead persistence

| Thứ tự | Hành động |
|---|---|
| 1 | **Ghi trạng thái `SUBMITTING` xuống đĩa và flush/commit** |
| 2 | Chỉ sau khi flush xong mới gọi network submit |
| 3 | Submit trả về ⇒ **ghi + flush `operation_name` NGAY**, trước mọi thao tác khác |

Khi khởi động lại:

| Trạng thái đọc được | Xử lý |
|---|---|
| `SUBMITTING` **không có** `operation_name` | ⇒ **`SUBMISSION_UNKNOWN`** |
| `SUBMITTED` có `operation_name` | tiếp tục poll bình thường |

**Không tự resubmit trong mọi trường hợp.**

### 5.3 Ba loại hành động, ba chính sách retry KHÁC NHAU

**Không dùng chung một `max_retries`.** Sửa khiếm khuyết `CallPolicy.max_retries = 1`.

| Hành động | Chính sách | Lý do |
|---|---|---|
| **Submit generation** | **`max_submit_attempts = 1`** | Mỗi submit **có thể tạo generation bị tính tiền** |
| **Poll operation** | **được retry** (backoff, có trần thời gian) | Chỉ đọc trạng thái |
| **Download kết quả** | **được retry** từ operation/file đã có | Không tạo generation mới |

### 5.4 Reconciliation — giới hạn phải nói rõ

**KHÔNG khẳng định có thể "list provider operations".** Chưa xác minh Gemini API hỗ trợ
liệt kê operations của một dự án.

Reconciliation vì vậy **chỉ có thể** dựa vào:

1. **Operation đã lưu trên đĩa** — nếu `operation_name` kịp ghi.
2. **Billing console** — người vận hành đối chiếu thủ công.

Ở trạng thái `SUBMISSION_UNKNOWN` không có `operation_name`, khả năng cao **chỉ còn
billing console** để biết có bị tính tiền hay không. Đây là lý do write-ahead ở 5.2 là
bắt buộc chứ không phải tuỳ chọn.

### 5.5 Đính chính về idempotency

`idempotency_key()` trong `video_api/adapter.py:81` là **khoá nội bộ của repo**. Nó chỉ có
tác dụng nếu **provider nhận và tôn trọng khoá đó** — **chưa xác minh**.

⇒ **Không được khẳng định exactly-once.** Bảo vệ thật đến từ: write-ahead persistence +
`max_submit_attempts = 1` + `SUBMISSION_UNKNOWN`. `idempotency_key()` chỉ là khoá truy vết.

---

## 6. Pricing và cost record

### 6.1 `Decimal`, không `float`

Toàn bộ đường tính tiền dùng `decimal.Decimal`.

### 6.2 Khoá của một bản ghi giá

```python
@dataclass(frozen=True)
class VerifiedPrice:
    provider: str
    model_id: str                  # "veo-3.1-generate-preview"
    resolution: str                # "1080p"
    duration_seconds: int          # 8
    audio_mode: str                # "always_on"
    usd_per_second: Decimal
    source_url: str                # https://ai.google.dev/gemini-api/docs/pricing
    effective_date: date
    verified_on: date
    pricing_snapshot_sha256: str
    max_age_days: int = 30
```

**Fail-closed** — `quote()` ném `PriceUnverifiedError` khi: thiếu trường · `verified_on`
quá hạn · snapshot hash không khớp · không có bản ghi khớp đúng khoá.

Giá đổi hoặc không khớp ⇒ **dừng, xin PO duyệt lại**.

### 6.3 Bốn khái niệm chi phí — KHÔNG được lẫn

| Khái niệm | Nguồn |
|---|---|
| `estimated_cost` | bảng giá đã ghim, trước khi gọi |
| `computed_charge_from_duration` | thời lượng thật × đơn giá |
| `provider_reported_usage` | **chỉ điền nếu API thật sự trả** |
| `billing_reconciled_cost` | **chỉ điền nếu đối chiếu được console** |

Không gọi `computed_charge_from_duration` là "actual cost" khi provider không trả usage.

Áp dụng ngược cho D05-B: **0,5070 USD là `computed_charge_from_duration`**, không phải
actual cost — usage đã mất do lỗi serialization, chưa đối chiếu console.

---

## 7. QC

### 7.1 Ngưỡng scene cut — **PROVISIONAL**

0,10 **chưa production-ready**. Một golden positive không đủ chốt ngưỡng.

### 7.2 Ngưỡng freeze — **BỎ CON SỐ CỨNG**

Ngưỡng "mpdecimate > 5%" ở bản trước **đã bỏ**.

**`mpdecimate` chỉ phát hiện khung gần trùng nhau — nó KHÔNG tự chứng minh video bị lỗi
freeze.** Cảnh quay tĩnh hợp lệ, chuyển động rất chậm, hoặc bầu trời phẳng đều tạo ra
khung gần trùng mà không có lỗi nào.

Không đặt con số cho tới khi hiệu chuẩn xong.

### 7.3 Kế hoạch hiệu chuẩn (bắt buộc trước khi dùng thật)

**Scene cut:**

| Bước | Nội dung |
|---|---|
| 1 | **Golden positive**: clip D05-B — `pts_time=3.25`, khung 78/120, `scene_score=0.308` |
| 2 | **Expected-no-cut**: 5 đầu ra bake-off D04, đoạn nguồn 8s, video demo-vn |
| 3 | Chạy detector, **lưu raw output** từng clip |
| 4 | Đo **false positive** và **false negative** |
| 5 | Chốt ngưỡng, ghi kèm số mẫu và tỉ lệ lỗi |

**Freeze — corpus bắt buộc:**

| Loại mẫu | Mục đích |
|---|---|
| Video chuyển động bình thường | mốc âm tính |
| **Cảnh camera gần như đứng yên** | bắt false positive |
| **Cảnh chuyển động chậm** | bắt false positive |
| **Clip freeze tổng hợp, nhiều độ dài** | mốc dương tính, đo ngưỡng theo độ dài |

Đo false positive/false negative trên toàn bộ corpus rồi mới chốt.

Lưu lệnh FFmpeg nguyên văn và raw output vào `d05-discovery/qc-calibration/`.

```bash
ffmpeg -v error -i CLIP -filter_complex "select='gt(scene,T)',metadata=print:file=-" -f null -
ffmpeg -v error -i CLIP -vf mpdecimate -loglevel debug -f null -
```

### 7.4 Bảng phép kiểm

| # | Lỗi | Cách đo | Ngưỡng |
|---|---|---|---|
| 1 | Hard cut | `select='gt(scene,T)'` | **provisional 0,10 — chốt sau hiệu chuẩn** |
| 2 | Freeze / khung trùng | `mpdecimate` | **CHƯA CÓ NGƯỠNG — chờ hiệu chuẩn** |
| 3 | Decode failure | `ffmpeg -v error -f null -` | bất kỳ dòng lỗi nào |
| 4 | Morphing / rung | `signalstats` YDIF | **WARN only, chưa hiệu chuẩn** |
| 5 | Sai độ phân giải | `ffprobe stream=width,height` | khớp chính xác 1080×1920 |
| 6 | **Sai fps nguồn** | `ffprobe stream=r_frame_rate` | **phải đúng 24** (Veo cố định) |
| 7 | Sai thời lượng | `ffprobe format=duration` | lệch ≤ 0,10 s so với 8 s |

### 7.5 Quyền của QC

| Loại | Quyền của máy |
|---|---|
| Hard cut vượt ngưỡng **đã hiệu chuẩn** | **AUTO-REJECT** |
| Decode fail / sai res / sai fps / sai duration | **AUTO-REJECT** |
| Freeze | **chỉ WARN** cho tới khi có ngưỡng đã hiệu chuẩn |
| Morphing, rung, thẩm mỹ | **chỉ WARN + human review** |
| PASS tự động | **vẫn BẮT BUỘC human approval** |

**QC không bao giờ có quyền tuyên bố đạt thẩm mỹ.**

---

## 8. Usage serialization

Lỗi `ModalityTokens` thuộc đường Omni Flash (`client.interactions`).
**Không giả định Veo (`generate_videos` + `operations`) trả cùng loại usage metadata.**

1. Pydantic model ⇒ **`model_dump(mode="json")`** (SDK dùng pydantic — xác minh qua `model_fields`).
2. Không phải ⇒ chuẩn hoá đệ quy về kiểu nguyên thuỷ.
3. `json.dumps(..., default=str)` là lưới an toàn cuối.
4. **Ghi raw/repr trước khi chuẩn hoá.**
5. **Bọc khối ghi báo cáo trong `try/except`** — lỗi ghi báo cáo **không bao giờ được làm
   mất `operation_name` hay file kết quả**.

---

## 9. File code dự kiến thay đổi khi triển khai

**Chưa file nào bị sửa.**

| File | Loại | Nội dung |
|---|---|---|
| `providers/pricing.py` | sửa | `VerifiedPrice` dùng `Decimal`; bỏ placeholder |
| `errors.py` | sửa | `PriceUnverifiedError`, `CapabilityError`, `BrollQcFailedError`, `HumanApprovalRequiredError`, `SubmissionUnknownError` |
| `providers/video_api/adapter.py` | sửa | Tách 3 chính sách retry; đính chính `idempotency_key` |
| `providers/video_api/veo.py` | **mới** | Adapter Veo 3.1, state machine mục 5 |
| `providers/video_api/capability.py` | **mới** | Bảng capability + fail-fast mục 4.2 |
| `qc/broll.py`, `qc/__init__.py` | **mới** | 7 phép kiểm mục 7.4 |
| `orchestrator/pipeline.py` | sửa | QC + human approval trước composer |
| `composer/` | sửa | **Chuyển 24 → 30 fps khi xuất master** |
| `cli/main.py` | sửa | `aiva broll review` / `approve` / `reconcile` |
| `providers/registry.py` | sửa | Thêm `"veo"`; **giữ nguyên** `video_api` (Omni) |
| `schemas/broll-qc.schema.json`, `schemas/broll-submission.schema.json` | **mới** | — |

**Không đụng**: `providers/duix/`, `providers/vieneu/`, và ba file untracked hiện có.

---

## 10. Test dự kiến

| Test | Kiểm gì |
|---|---|
| `test_qc_bat_duoc_scene_cut_d05b` | **Golden positive** — FAIL trên D05-B tại 3,25 s |
| `test_qc_khong_bao_nham_tren_clip_bakeoff` | 5 đầu ra bake-off ⇒ không false positive |
| `test_qc_freeze_chi_warn_khi_chua_hieu_chuan` | Freeze ⇒ WARN, không AUTO-REJECT |
| `test_qc_bat_sai_fps_24` | fps ≠ 24 từ Veo ⇒ FAIL |
| `test_qc_bat_sai_res_duration_decode` | từng phép kiểm |
| `test_capability_lite_reject_reference_images` | Lite + `reference_images` ⇒ `CapabilityError` |
| `test_capability_qua_3_reference_images` | > 3 ⇒ `CapabilityError` |
| `test_capability_1080p_bat_buoc_8_giay` | ≠ 8 ⇒ `CapabilityError` |
| `test_capability_veo_tu_choi_silent` | yêu cầu tắt audio ⇒ `CapabilityError` |
| `test_capability_veo_tu_choi_fps_khac_24` | fps ≠ 24 ⇒ `CapabilityError` |
| `test_khong_bao_gio_gui_generate_audio_false` | payload không chứa `generate_audio=False` |
| `test_write_ahead_ghi_submitting_truoc_network` | thứ tự ghi đúng |
| `test_khoi_dong_lai_submitting_khong_co_operation_name` | ⇒ `SUBMISSION_UNKNOWN`, **chặn resubmit** |
| `test_submit_chi_mot_lan` | `max_submit_attempts == 1` |
| `test_poll_va_download_duoc_retry` | retry được, không tạo generation mới |
| `test_pricing_dung_decimal` | không `float` |
| `test_pricing_fail_closed_*` | thiếu nguồn / quá hạn / sai snapshot hash |
| `test_bon_khai_niem_chi_phi_tach_bach` | `computed_charge` ≠ actual |
| `test_usage_serialization_khong_lam_mat_ket_qua` | vẫn giữ `operation_name` và file |
| `test_composer_chuyen_24_sang_30fps` | master ra 30fps, không nội suy |
| `test_qc_fail_thi_khong_vao_composer` | `verdict=FAIL` ⇒ chặn |
| `test_pass_van_can_human_approval` | PASS + `human_approval=null` ⇒ chặn |
| `test_gate_d05_van_chan` | hàng rào gate còn nguyên |

Mọi test **mock provider**, **không gọi API thật** — `CLAUDE.md` §4.

---

## 11. Tiêu chí nghiệm thu chất lượng

**Tầng máy** (chỉ có quyền từ chối): scene cut dưới ngưỡng đã hiệu chuẩn · giải mã sạch ·
1080×1920 chính xác · **fps nguồn = 24** · thời lượng lệch ≤ 0,10 s so với 8 s.

**Tầng người** (quyết định cuối): chân thật, không morphing/biến dạng, một cú máy liên tục,
ánh sáng nhất quán, **đủ đẹp để đăng chính thức**.

---

## 12. Rollback boundary

| Lớp | Trạng thái | Cách quay lại |
|---|---|---|
| **Production hiện tại** | Duix + VieNeu + FFmpeg — **0 USD, 100% local** | Không phụ thuộc D05 |
| Gate | `CURRENT_GATE = "D04"` | Không nâng cho tới khi PO duyệt |
| Cost guard | 4 lớp chặn còn nguyên | `max_usd_per_run = 0.0` chặn hết |
| Code | **Chưa sửa dòng nào** | `git checkout` — repo mới có 1 commit |
| Omni Flash | **giữ trong kiến trúc** | Không xoá |
| Model bake-off | 28,98 GB | **Không xoá** |

---

## 13. Bất định còn lại

| # | Bất định | Ảnh hưởng |
|---|---|---|
| 1 | **Provider có nhận idempotency key của client không** | Quyết định exactly-once (5.5) |
| 2 | **Gemini API có cho liệt kê operations không** | Quyết định reconciliation làm được gì (5.4) |
| 3 | **Veo có tránh được scene jump không** | Chưa có bằng chứng — prompt chỉ giảm xác suất |
| 4 | **Ngưỡng scene cut thật** | 0,10 provisional, cần hiệu chuẩn |
| 5 | **Ngưỡng freeze** | Chưa có con số nào |
| 6 | **Ngưỡng morphing/rung** | Chưa có phép đo tin cậy |
| 7 | **Veo có trả usage metadata không, dạng gì** | Quyết định có `provider_reported_usage` |
| 8 | **Quyền thương mại của Sora/Runway/Luma** | Chưa xác minh ⇒ chưa đủ điều kiện production |

*(Bất định về audio, fps và reference image ở bản trước đã chuyển sang mục 1.3 / 1.4 / 1.5
với tư cách năng lực đã xác minh.)*

---

## 14. Decision matrix

### 14.1 Trạng thái ứng viên

| Ứng viên | Trạng thái | Ghi chú |
|---|---|---|
| **Omni Flash** `gemini-omni-flash-preview` | **EXISTING EVALUATED CANDIDATE** | D05-B có scene jump tại 3,25 s. 720p. Giữ trong kiến trúc |
| **Veo 3.1 Standard** `veo-3.1-generate-preview` | **PRODUCTION-QUALITY CANDIDATE TIẾP THEO** | 1080p, reference images, first/last frame. **Chưa chạy lần nào** |
| **Final production baseline** | **PENDING CONTROLLED A/B COMPARISON** | Chưa chốt |

### 14.2 Vì sao KHÔNG chốt Veo là winner trước khi thử

| Lý do | Nội dung |
|---|---|
| 1 | Tài liệu Google hiện mô tả **Omni Flash là default cho coherence và multi-input workflow** — không phải model kém |
| 2 | Veo mạnh ở **cinematic control, reference images, first/last frame, 1080p/4K** — thế mạnh khác, không đương nhiên tốt hơn |
| 3 | **Một clip Omni lỗi chưa đủ chứng minh cả model kém.** n=1 |
| 4 | Một lượt Veo Standard **phải được so với D05-B** trước khi chọn người thắng |

Đây là điều chỉnh so với bản sửa 2, nơi tôi đã chốt Veo là "production winner" **trước khi
có bất kỳ mẫu Veo nào**. Kết luận đó không có căn cứ thực nghiệm và đã được rút lại.

### 14.3 Những gì ĐÃ chốt được

| Quyết định | Chốt | Căn cứ |
|---|---|---|
| Thời lượng lượt thử | **8 giây, cứng** | 1080p bắt buộc `duration_seconds=8` |
| Chi phí lượt thử | **3,20 USD chính xác** | 8 × 0,40 |
| Hạn mức cấp ở bước này | **KHÔNG CẤP** | Cần quyết định riêng của PO |
| Audio | **always on, không gửi `generate_audio`** | Tài liệu model |
| fps nguồn | **24 cố định**, composer chuyển sang 30 | Tài liệu model |
| Retry submit | **1 lần duy nhất** | Mỗi submit có thể bị tính tiền |
| Retry poll/download | **được phép** | Không tạo generation mới |
| Ngưỡng scene cut | **0,10 provisional** | Chốt sau hiệu chuẩn |
| Ngưỡng freeze | **chưa có** | Chốt sau hiệu chuẩn |
| Quyền QC | **chỉ từ chối** | Human approval luôn bắt buộc |
| Production baseline | **PENDING A/B** | Chưa có mẫu Veo để so |

---

D05C_DESIGN_STATUS = REVISION 3 — READY FOR PO REVIEW
