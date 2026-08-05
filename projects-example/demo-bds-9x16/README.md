# Project mẫu — `demo-bds-9x16`

Ba file trong thư mục này là **ví dụ đọc hiểu hợp đồng dữ liệu**, không phải dữ
liệu thật và không phải nơi làm việc. Project thật nằm ở
`F:\AI-VIDEO-AGENT-RUNTIME\projects\<id>\` (xem
[ADR-0002](../../docs/adr/0002-runtime-data-outside-repo.md)).

Chúng được sinh ra bằng chính code của dự án và được
`tests/test_examples.py` đối chiếu lại với `schemas/` mỗi lần chạy test — nên
chúng không thể lỗi thời một cách âm thầm.

| File | Nội dung |
|---|---|
| `project.json` | project 9:16, 40 giây, trần ngân sách 0 USD, đã ở trạng thái `APPROVED` |
| `storyboard.json` | 5 shot / 3 scene (hook · body · CTA) |
| `asset-manifest.json` | 3 tài sản, đủ khai báo chủ sở hữu và đồng ý sử dụng |

## Điểm đáng chú ý

**Chữ chính xác đã được trích sẵn.** Planner tìm ra và gắn vào đúng shot chứa nó:

| Shot | Chuỗi | Loại |
|---|---|---|
| `shot-001` | `thổ cư` | `legal` |
| `shot-002` | `sổ hồng riêng`, `công chứng` | `legal` |
| `shot-003` | `1,2 tỷ` | `price` |
| `shot-005` | `0909123456` | `phone` |
| `shot-005` | `Liên hệ ngay để được tư vấn` | `cta` |

Tất cả đều có `"exact": true` — nghĩa là composer phải chèn chúng bằng FFmpeg,
không được giao cho model sinh video vẽ (brief §D04.2).

Lưu ý số điện thoại: brief viết `0909123456`, và chuỗi giữ nguyên **từng chữ
số**. Đây chính là thứ mà việc để model tự vẽ chữ có thể làm hỏng.

**Phê duyệt được neo vào hash.** `project.json` chứa
`approval.storyboard_sha256`. Sửa `storyboard.json` là hash đổi, phê duyệt hết
hiệu lực, và `aiva render --execute` sẽ bị chặn cho tới khi duyệt lại.

**Đồng ý sử dụng tài sản.** Video avatar và mẫu giọng đều có `granted_by`,
`granted_at`, `scope` và `evidence_ref` — con trỏ tới hồ sơ nằm ngoài repo.
Logo công ty là `not_required` vì do chính dự án tạo ra.

## Tự tạo project như thế này

```powershell
uv run aiva plan --brief "Bán lô đất thổ cư mặt tiền đường nhựa 8m tại TP. Biên Hoà, Đồng Nai. Diện tích 100m2, sổ hồng riêng, công chứng trong ngày. Giá chỉ 1,2 tỷ. Liên hệ 0909123456 để xem đất ngay hôm nay." --duration 40
uv run aiva approve <project-id> --by "Tên bạn"
uv run aiva render <project-id>            # dry-run
```

Giá trị `sha256` và `bytes` của tài sản trong file mẫu là con số minh hoạ; tài
sản thật phải dùng `Get-FileHash ... -Algorithm SHA256`.
