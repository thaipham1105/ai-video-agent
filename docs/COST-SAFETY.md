# An toàn chi phí và dữ liệu

Tài liệu này mô tả cơ chế đã được hiện thực và kiểm thử, không phải lời hứa.
Mọi luật ở đây có test tương ứng trong `tests/test_costguard.py`,
`tests/test_pipeline.py` và `tests/test_no_secrets.py`.

## 1. Ba lớp chặn chi tiêu

Phải vượt **cả ba** mới tốn được một đồng nào:

| Lớp | Mặc định | Muốn vượt phải |
|---|---|---|
| 1. Kiểu chạy | `dry-run` | thêm `--execute` |
| 2. Chế độ provider | `mock` | thêm `--provider-mode real` |
| 3. Provider tính tiền | bị chặn | thêm `--allow-paid` **và** project `APPROVED` **và** ước tính ≤ `budget.cap_usd` |

`budget.cap_usd` mặc định là **0**. Nghĩa là một project mới toanh không thể
tiêu tiền, kể cả khi người dùng gõ đủ mọi cờ.

## 2. Cost guard kiểm tra gì

`orchestrator/costguard.py` là nơi duy nhất quyết định. Với mỗi lần chạy thật:

1. **Trạng thái** — project phải ở `APPROVED`, `COMPOSED` hoặc `DONE`. Ở
   `DRAFT`/`PLANNED` thì bị từ chối kèm hướng dẫn chạy `aiva approve`.
2. **Phê duyệt còn hiệu lực** — `approval.storyboard_sha256` phải khớp hash
   storyboard hiện tại. Sửa kịch bản sau khi duyệt là mất hiệu lực (brief §9).
   Điều này cũng thực thi brief §D05.4: ViMax không thể tự gọi API trong lúc
   người dùng đang sửa storyboard.
3. **Cờ cho phép trả phí** — có bước `billable` mà thiếu `--allow-paid` thì chặn.
4. **Trần ngân sách** — ước tính phần tính tiền phải ≤ `budget.remaining_usd`.
5. **Đồng ý sử dụng tài sản** — ở chế độ `real`, mọi tài sản phải có
   `consent.status ∈ {granted, not_required}`.

Dry-run **không bao giờ** bị chặn — nhưng cũng không gọi provider nào, và nó nói
trước số tiền sẽ tốn nếu chạy thật.

## 3. Ước tính luôn làm tròn lên

`estimator.py` cộng bằng `Decimal` và làm tròn lên tới 1/100 cent
(`ROUND_CEILING`). Ước tính thấp hơn thực tế nguy hiểm hơn nhiều so với ước tính
cao hơn, vì nó có thể lọt qua trần ngân sách.

Mọi dòng chi phí đều kèm **giả định** để người dùng đối chiếu (brief §D05.5).

## 4. Bảng giá là giả định chưa kiểm chứng

`providers/pricing.py` ghi rõ điều này ngay trong chuỗi `assumption`:

| Provider | Đơn giá | Tính tiền | Ghi chú |
|---|---|---|---|
| VieNeu-TTS | 0 USD | không | chạy local CPU/ONNX; chi phí = thời gian máy |
| Duix-Avatar | 0 USD | không | chạy local Docker + GPU; chi phí = thời gian GPU |
| FFmpeg | 0 USD | không | chạy local |
| ViMax | 0,40 USD/giây | **CÓ** | **GIẢ ĐỊNH** — phải đối chiếu bảng giá thật trước D05 |
| Video API | 0,50 USD/giây | **CÓ** | **GIẢ ĐỊNH** — phải đối chiếu bảng giá thật trước D05 |

Hai dòng cuối cố tình đặt cao để hệ thống thà chặn nhầm còn hơn cho qua nhầm.

## 5. Ràng buộc bắt buộc khi gọi API (brief §D05.3)

`providers/video_api/adapter.py::CallPolicy` khai báo sẵn cả sáu:

| Ràng buộc | Hiện thực |
|---|---|
| estimate | `quote()` — chạy được ở mọi gate |
| hard cap | `budget.cap_usd` + `CallPolicy.max_usd_per_run` (mặc định 0) |
| phê duyệt rõ ràng | `--allow-paid` + trạng thái `APPROVED` |
| timeout | `CallPolicy.timeout_sec` (mặc định 600) |
| giới hạn retry | `CallPolicy.max_retries` (mặc định 1) |
| idempotency | `idempotency_key()` — cùng yêu cầu cho cùng khoá, không trả tiền hai lần |

## 6. Secret

- Repo **không bao giờ đọc giá trị** biến môi trường chứa secret. Chỉ có
  `config.secret_present(name)` trả về `True/False`.
- `aiva doctor` báo "present (giá trị không được đọc)", không in nội dung.
- `.env` nằm trong `.gitignore`; chỉ `.env.example` với giá trị giả được commit.
- `tests/test_no_secrets.py` quét mọi file Git đang theo dõi tìm mẫu khoá của
  OpenAI/Anthropic/Google/AWS/GitHub/Slack và khối private key, đồng thời chặn
  mọi file media/model lọt vào Git.

## 7. Đồng ý sử dụng tài sản

Brief §4: không dùng hình ảnh hay giọng của người khác khi chưa có đồng ý rõ ràng.

Mỗi tài sản trong `asset-manifest.json` phải khai báo:

- `owner` — ai sở hữu
- `consent.status` — `granted` / `pending` / `denied` / `not_required`
- `consent.granted_by`, `granted_at`, `scope` — ai cho phép, khi nào, phạm vi nào
- `consent.evidence_ref` — **con trỏ** tới hồ sơ đồng ý nằm ngoài repo, không
  bao giờ nhúng nội dung bằng chứng

Còn tài sản `pending`/`denied` thì render thật bị chặn. Xem mẫu khai báo trong
`assets-example/consent-template.md`.

## 8. Nhãn nội dung AI

`project.ai_disclosure` bật sẵn. Khi `burn_in = True`, composer khắc nhãn
"Nội dung có sử dụng AI" lên khung hình, và `render-manifest.json` ghi
`ai_disclosure_applied` để kiểm chứng về sau (brief §4).
