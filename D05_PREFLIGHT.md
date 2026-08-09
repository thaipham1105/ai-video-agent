# D05 — PREFLIGHT VÀ PHẠM VI (CHƯA MỞ, CHỜ PO DUYỆT)

Tài liệu này **không mở gate**. Nó mô tả phạm vi, rủi ro và điều kiện để PO quyết định
có mở D05 hay không.

> **Trạng thái: D05-A ĐÃ CHẠY XONG. D05-B CHƯA MỞ.**
> `CURRENT_GATE` vẫn `"D04"` · `AIVA_ALLOW_PAID_APIS=0` · `max_usd_per_run=0.0` ·
> approval gate còn nguyên. **Không API key, không gọi endpoint, không sinh B-roll thật,
> không đồng nào bị tiêu.** Không file nào trong `src/`, `tests/`, `schemas/` bị sửa.
>
> Kết quả discovery ở [mục 6](#6-d05-a--kết-quả-discovery-đã-chạy).

---

## 1. Bối cảnh

D00→D04 đã xong. D04 vừa được PO duyệt với **Duix làm production winner**
(xem [D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md](D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md) mục 0).
Pipeline hiện chạy trọn vẹn và **hoàn toàn miễn phí, hoàn toàn local**:

```
brief tiếng Việt → storyboard → VieNeu-TTS → Duix-Avatar → FFmpeg → MP4 9:16
```

D05 là gate **tuỳ chọn** duy nhất còn lại trong brief §8.

## 2. D05 là gì

Theo `CLAUDE.md` và `AI_VIDEO_AGENT_BUILD_BRIEF.md`: **ViMax / Video API sinh B-roll**.

Đây là thứ duy nhất trong toàn dự án **gọi API tính tiền**. Mọi thứ khác chạy local.

Mục tiêu: sinh cảnh minh hoạ (B-roll) xen giữa các shot người nói, thay vì video
chỉ có một khuôn mặt nói suốt từ đầu đến cuối.

## 3. Điều đã có sẵn trong code — D05 không phải viết từ đầu

Khung đã dựng từ D01, có test mock, chỉ thiếu phần HTTP thật:

| Thành phần | File | Trạng thái |
|---|---|---|
| Giao diện provider | `providers/base.py` — `BrollProvider` | xong |
| Adapter API trả phí | `providers/video_api/adapter.py` | khung xong, `generate()` là `NotImplementedError` |
| Adapter ViMax | `providers/vimax/adapter.py` | khung xong |
| Mock cho cả hai | `providers/*/mock.py` | xong, test xanh |
| Chính sách gọi | `video_api/adapter.py:39` — `CallPolicy` | xong, `max_usd_per_run` mặc định **0.0** |
| Cổng chi phí | `orchestrator/costguard.py` — `evaluate()`, `enforce()` | xong |
| Hàng rào gate | `adapter.py:32` `GATE = "D05"` → `GateNotReachedError` | **đang chặn** |
| Đăng ký | `registry.py` — `KNOWN_BROLL = {"none","vimax","video_api"}` | xong |
| Biến môi trường | `AIVA_VIDEO_API_PROVIDER`, `AIVA_VIDEO_API_KEY`, `AIVA_VIDEO_API_MAX_USD_PER_RUN`, `AIVA_ALLOW_PAID_APIS` | khai báo xong, mặc định TẮT |

Bốn lớp chặn hiện đang xếp chồng, theo `adapter.py:9`:

1. Gate D05 chưa mở → `GateNotReachedError`
2. `AIVA_ALLOW_PAID_APIS=0` → `PaidApiNotAllowedError`
3. `max_usd_per_run=0.0` → `BudgetExceededError`
4. Thiếu phê duyệt rõ ràng → `ApprovalRequiredError` / `ApprovalStaleError`

**Mở D05 nghĩa là gỡ lần lượt bốn lớp này.** Đó là lý do nó cần PO duyệt tường minh.

## 4. Việc phải làm nếu D05 được mở

| # | Việc | Ghi chú |
|---|---|---|
| 1 | Chọn nhà cung cấp cụ thể | Chưa chọn. Cần PO quyết vì ảnh hưởng giá và điều khoản |
| 2 | Đọc điều khoản dịch vụ và giấy phép đầu ra | Nội dung sinh ra có được dùng thương mại không, có phải gắn nhãn không |
| 3 | Nối phần HTTP vào `video_api/adapter.py::generate()` | Chỗ duy nhất hiện là `NotImplementedError` |
| 4 | Ghim giá vào `providers/pricing.py` | Để `quote()` và `estimate` ra số thật |
| 5 | Đặt `max_usd_per_run` > 0 | PO quyết con số |
| 6 | Cấu hình `.env` với API key thật | **PO tự làm.** Tôi không đọc, không ghi, không in secret |
| 7 | Nâng `CURRENT_GATE` lên `"D05"` | Một dòng, sau khi mọi thứ trên đã xong |
| 8 | Test: mock vẫn phải xanh, không test nào gọi API thật | Bắt buộc theo `CLAUDE.md` §4 |

## 5. Rủi ro

| Rủi ro | Mức | Giảm thiểu đã có |
|---|---|---|
| **Tiêu tiền ngoài ý muốn** | **cao** | 4 lớp chặn ở mục 3; `--dry-run` là mặc định; `estimate` chạy được mà không chạm provider |
| Vòng lặp render lỗi gọi API nhiều lần | cao | `max_usd_per_run` là hard cap cho mỗi lần chạy |
| Lộ API key | cao | `.env` đã trong `.gitignore`; `test_no_secrets.py` đang canh; tôi không đọc secret |
| Giấy phép đầu ra không cho thương mại | trung bình | Việc #2 phải làm trước khi gọi lần đầu |
| Nhà cung cấp đổi giá hoặc API | trung bình | Ghim giá ở `pricing.py`, ghi vào `render-manifest.json` mỗi lần chạy |
| B-roll AI làm sai lệch thông tin BĐS | trung bình | `CLAUDE.md` §5: chữ chính xác (giá, số điện thoại, pháp lý) **do composer chèn**, không giao model vẽ |

## 6. D05-A — Kết quả discovery (đã chạy)

Ngày kiểm tra: **2026-08-06**. Không gọi API, không đặt key, không sinh B-roll.

### 6.1 Bảng giá kiểm chứng từ trang chính thức

| Nhà cung cấp | Nguồn giá chính thức | Đơn vị tính | Biến thể / giá |
|---|---|---|---|
| **Google Veo 3.1** | `ai.google.dev/gemini-api/docs/pricing` (trang ghi cập nhật **2026-08-05**) | **giây** | Lite 1080p **0,08** · Fast 1080p **0,12** · Standard 720p/1080p **0,40** · Standard 4K 0,60 · Lite 720p 0,05 · Fast 720p 0,10 USD/s |
| **OpenAI Sora 2** | `developers.openai.com/api/docs/pricing` | **giây** | Sora 2 720p **0,10** (batch 0,05) · Pro 720p 0,30 · Pro 1024p 0,50 · **Pro 1080p 0,70** (batch 0,35) USD/s |
| **Runway Gen-4** | `docs.dev.runwayml.com/guides/pricing/` | **credit** (0,01 USD/credit) | Gen-4 Turbo 5 cr/s = **0,05** · Gen-4.5 12 cr/s = **0,12** USD/s |
| **Luma Ray3.2** | `lumalabs.ai/api/pricing` | **mỗi clip**, không theo giây | 5s: 0,30 (720p) / **1,20 (1080p)** · 10s: 0,90 / 3,60 USD |

**Không đưa vào bảng vì không lấy được trang chính thức**: Kling (chỉ tìm được blog tổng
hợp và đại lý bán lại — **không dùng số chưa kiểm chứng**), MiniMax Hailuo (chưa kiểm
chứng đợt này). **ViMax** không có bảng giá riêng: nó là lớp *điều phối*, tự gọi API của
bên khác ở cả ba lớp LLM + image + video, nên chi phí thật = giá nhà cung cấp bên dưới
**cộng thêm** chi phí LLM và image.

Dữ liệu máy đọc được: `F:\AI-VIDEO-AGENT-RUNTIME\d05-discovery\pricing-verified.json`

### 6.2 Quota, giới hạn vận hành và điều kiện giá

| | Veo 3.1 | Sora 2 | Runway | Luma Ray3.2 |
|---|---|---|---|---|
| Hỗ trợ 9:16 dọc | **có** (xác minh) | **có** (720×1280, 1080×1920 dọc) | **chưa xác minh** | **có** (9:16 trong danh sách) |
| Đạt 1080×1920 của dự án | có (1080p) | **có, đúng 1080×1920** | trang giá **không nêu độ phân giải theo bậc** | có (1080p) |
| Độ dài clip | 8 s | không nêu | **4–15 s** | 5/10/15/20 s |
| Audio kèm theo | **có** (đã tính trong giá) | không nêu | không nêu | không nêu |
| Free tier | không | không | không | không |
| Điều kiện giá đáng lưu ý | 4K đắt gấp 1,5× | batch rẻ một nửa | tính theo credit | **1080p đắt gấp 4× so với 720p**; HDR ×2, HDR+EXR ×3 |

### 6.3 Quyền thương mại

| Nhà cung cấp | Nguồn điều khoản | Kết luận |
|---|---|---|
| **Google Veo** | `ai.google.dev/gemini-api/terms` | **Xác minh được.** "Google won't claim ownership over that content". Bản **trả phí**: "Google doesn't use your prompts … or responses to improve our products". **Không** bắt buộc gắn nhãn AI. Lưu ý: Google giữ quyền sinh nội dung tương tự cho người khác |
| Sora 2 / Runway / Luma | — | **CHƯA XÁC MINH trong đợt này.** Phải đọc trước khi gọi lần đầu |

### 6.4 Estimate cho các cấu hình đại diện

Tái hiện đúng công thức `estimator._ceil_usd` — **làm tròn LÊN** tới 0,0001 USD, không bao
giờ báo thấp hơn thực tế. Script: `d05-discovery\estimate_broll.py`.

| Cấu hình | B-roll | Veo Lite 1080p | Veo Fast 1080p | Runway Turbo | Sora 2 720p | Sora 2 Pro 1080p | Veo Standard 1080p |
|---|---|---|---|---|---|---|---|
| **Demo hiện tại** (1 shot 7,68 s, không B-roll) | 0 s | **0** | **0** | **0** | **0** | **0** | **0** |
| Video 30 s, 2 cảnh × 5 s | 10 s | **0,80** | 1,20 | 0,50 | 1,00 | 7,00 | 4,00 |
| Video 60 s, 4 cảnh × 5 s | 20 s | **1,60** | 2,40 | 1,00 | 2,00 | 14,00 | 8,00 |
| Video 60 s, B-roll nặng 8 cảnh × 5 s | 40 s | **3,20** | 4,80 | 2,00 | 4,00 | 28,00 | 16,00 |

Đơn vị USD. Bảng đầy đủ 10 biến thể có trong đầu ra của script.

**Điều quan trọng nhất trong bảng này**: dòng đầu tiên. Video hiện tại của dự án **không có
B-roll**, nên chi phí là **0 USD với mọi nhà cung cấp**. Toàn bộ pipeline hiện tại
(VieNeu + Duix + FFmpeg) chạy local, miễn phí. D05 chỉ phát sinh tiền khi PO chủ động
thêm cảnh B-roll vào storyboard.

### 6.5 Đề xuất

**Đề xuất: Google Veo 3.1, bắt đầu ở bậc Lite 1080p (0,08 USD/s).**

Lý do, xếp theo trọng số:

1. **Là nhà cung cấp duy nhất tôi xác minh được CẢ giá LẪN điều khoản từ trang chính thức.**
   Ba nhà còn lại mới có giá, chưa có quyền thương mại.
2. **Điều khoản thương mại rõ ràng và có lợi**: không nhận sở hữu nội dung; bản trả phí
   không dùng prompt/output để huấn luyện — quan trọng vì prompt sẽ chứa thông tin dự án BĐS.
3. **Đúng định dạng dự án**: 9:16 dọc, 1080p, không phải upscale.
4. **Có thang giá trong cùng một API**: Lite 0,08 → Fast 0,12 → Standard 0,40 USD/s.
   Bắt đầu rẻ, nâng bậc nếu chất lượng chưa đạt, **không phải tích hợp lại**.
5. `CLAUDE.md` §3 đã nêu sẵn "Gemini, Veo" là API tính tiền được dự trù.

**Rủi ro của đề xuất này, nói thẳng:**

- Endpoint còn ở dạng `-preview`. **Veo 2 và Veo 3 đã bị khai tử 30/06/2026** — vòng đời
  phiên bản ngắn, phải theo dõi thông báo deprecation.
- **Giá đã bao gồm audio mà dự án không cần** (đã có VieNeu-TTS). Đang trả cho thứ không dùng.
- Không có free tier — không thử được miễn phí.
- Runway Gen-4 Turbo rẻ hơn (0,05 USD/s) nhưng **trang giá không nêu độ phân giải theo bậc**
  và **chưa xác minh hỗ trợ 9:16**, nên chưa chắc dùng được cho video dọc 1080×1920.

**Không phải quyết định của tôi.** Đây là đề xuất để PO chọn.

## 7. Bảng kết thúc D05-A

| Provider | Nguồn giá chính thức | Đơn vị tính | Estimate / video 60 s (4 cảnh × 5 s) | Quyền thương mại | Quota / rủi ro | Đề xuất |
|---|---|---|---|---|---|---|
| **Google Veo 3.1 Lite 1080p** | `ai.google.dev/gemini-api/docs/pricing` (2026-08-05) | giây — 0,08 USD/s | **1,60 USD** | **Xác minh:** không nhận sở hữu; bản trả phí không huấn luyện trên dữ liệu của bạn | Endpoint `-preview`; Veo 2/3 đã khai tử 30/06/2026; không free tier; giá gồm audio dự án **không dùng** | **ĐỀ XUẤT** |
| Google Veo 3.1 Fast 1080p | như trên | giây — 0,12 USD/s | 2,40 USD | như trên | như trên | dự phòng nếu Lite chưa đạt |
| Google Veo 3.1 Standard 1080p | như trên | giây — 0,40 USD/s | 8,00 USD | như trên | như trên | chỉ khi cần chất lượng cao nhất |
| Runway Gen-4 Turbo | `docs.dev.runwayml.com/guides/pricing/` | credit — 5 cr/s = 0,05 USD/s | 1,00 USD | **chưa xác minh** | Trang giá **không nêu độ phân giải theo bậc**; **chưa xác minh 9:16**; clip 4–15 s | rẻ nhất nhưng **chưa đủ dữ liệu để chọn** |
| Luma Ray3.2 720p | `lumalabs.ai/api/pricing` | **mỗi clip** — 0,30 USD/clip 5 s | 1,20 USD | **chưa xác minh** | 1080p đắt gấp 4×; HDR ×2; tính theo clip nên giá/giây không tuyến tính | cân nhắc nếu chấp nhận 720p |
| OpenAI Sora 2 720p | `developers.openai.com/api/docs/pricing` | giây — 0,10 USD/s | 2,00 USD | **chưa xác minh** | 720p là mức duy nhất của bản thường | — |
| OpenAI Sora 2 Pro 1080p | như trên | giây — 0,70 USD/s | 14,00 USD | **chưa xác minh** | Đúng 1080×1920 nhưng **đắt nhất nhóm** | — |
| Kling / MiniMax | **không lấy được trang chính thức** | — | — | — | Chỉ có blog và đại lý bán lại | **loại khỏi đợt này** |
| ViMax | không có bảng giá riêng | — | giá provider bên dưới **+ LLM + image** | — | Là lớp điều phối, cộng thêm chi phí | — |

**Chi phí hiện tại của dự án vẫn là 0 USD** — video đang không dùng B-roll.

## 7b. Ba lựa chọn tiếp theo cho PO

| | Lựa chọn | Hệ quả |
|---|---|---|
| **1** | **Dừng ở đây, không mở D05-B** | Dự án giữ nguyên: chạy được, miễn phí, hoàn toàn local. Bốn lớp chặn còn nguyên. **An toàn nhất về chi phí** |
| **2** | **D05-B: ghim giá vào code, chưa gọi API** | Tôi sửa `providers/pricing.py` với giá đã kiểm chứng, chạy `aiva estimate` thật trên storyboard có B-roll. **Vẫn không gọi API, vẫn giữ `AIVA_ALLOW_PAID_APIS=0`.** Đây là lần đầu chạm vào `src/` |
| **3** | **D05-C: nối HTTP và gọi thật** | Cần PO: chọn nhà cung cấp, đặt hạn mức USD mỗi lần chạy, **tự đặt API key vào `.env`** (tôi không đọc, không ghi secret). Chỉ sau khi #2 xong |

Tôi đề xuất **lựa chọn 2** nếu PO muốn đi tiếp — nó đưa số thật vào hệ thống để `estimate`
và cost guard hoạt động đúng, mà vẫn chưa tiêu đồng nào.

## 8. Việc khác đang treo, độc lập với D05

| Mục | Nguồn | Trạng thái |
|---|---|---|
| **BL-001 "Tủ đồ AI"** | `docs/BACKLOG.md` | Cần **gate riêng**, không thuộc D05. Nhiều trang phục trên cùng nhân vật |
| Cách TTS đọc chữ số | bàn giao D02 | Chưa chấm riêng ("1,2 tỷ", "0909123456") |
| Đường nhiều shot chạy thật | bàn giao | Mới có test mock, chưa chạy thật liên tiếp |
| Giấy phép Duix | `docs/UPSTREAM-AUDIT.md` | **Phải đọc nguyên văn trước khi phát hành ra công chúng** |
| LatentSync 1.5 (backup) | D04 mục 0 | Môi trường và weights đã sẵn, tái lập được ngay nếu cần đánh giá lại |

## 9. Câu duyệt cho bước kế tiếp

D05-A đã xong. Để đi tiếp, PO trả lời **đúng một** trong ba dòng sau:

```
D05 = DUNG O DAY
D05-B = APPROVED, nha cung cap: <ten>          (ghim gia vao pricing.py, VAN chua goi API)
D05-C = APPROVED, nha cung cap: <ten>, han muc: <so> USD moi lan chay
```

Nếu chọn `D05-B`, tôi sẽ:

1. Sửa `src/ai_video_agent/providers/pricing.py` — thay placeholder `VIDEO_API_GENERIC`
   (0,50 USD/s, ghi rõ "GIẢ ĐỊNH CHƯA KIỂM CHỨNG") bằng giá đã xác minh của nhà cung cấp
   PO chọn, kèm URL nguồn và ngày kiểm tra trong `assumption`.
2. Cập nhật test tương ứng nếu có test canh giá.
3. Chạy `aiva estimate` thật trên một storyboard có B-roll để PO xem bảng chi phí do
   chính hệ thống sinh ra.
4. **Giữ nguyên** `CURRENT_GATE="D04"`, `AIVA_ALLOW_PAID_APIS=0`, `max_usd_per_run=0.0`
   và approval gate. Không gọi endpoint nào.

Trước khi chọn `D05-C`, phải xong hai việc chưa làm được ở D05-A:

- **Đọc điều khoản thương mại** của nhà cung cấp được chọn nếu không phải Google
  (Sora, Runway, Luma đều **chưa xác minh**).
- Quyết định có chấp nhận trả tiền cho **audio kèm theo mà dự án không dùng** hay không
  (áp dụng với Veo).

---

D05_A_STATUS = HOÀN TẤT — discovery xong, không gọi API, không tiêu tiền
D05_B_STATUS = CHƯA MỞ, CHỜ PO DUYỆT
