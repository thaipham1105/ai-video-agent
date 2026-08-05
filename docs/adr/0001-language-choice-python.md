# ADR-0001 — Chọn Python cho repo điều phối

- Trạng thái: **Chấp nhận** (Gate D01)
- Ngày: 2026-08-04
- Bối cảnh: brief §D01.2 — "Chọn Python hay TypeScript dựa trên bằng chứng tích
  hợp, ghi ADR; không chọn theo sở thích."

## Bối cảnh

Repo điều phối phải gọi được ba upstream và FFmpeg. Câu hỏi duy nhất cần trả
lời: ngôn ngữ nào **giảm được nhiều lớp trung gian nhất**?

## Bằng chứng khảo sát (D00 §4)

| Upstream | Cách tích hợp thật sự có | Hệ quả với Python | Hệ quả với TypeScript |
|---|---|---|---|
| VieNeu-TTS | **SDK Python thuần** (`pip install vieneu`), v3 Turbo ONNX int8 chạy CPU | Gọi in-process, không cần server | Phải dựng thêm một HTTP server Python rồi gọi sang — thêm một tiến trình và một lớp lỗi |
| Duix-Avatar | **HTTP API local** (`POST /easy/submit`, `GET /easy/query`) | HTTP client bình thường | HTTP client bình thường |
| ViMax | **Dự án Python + `uv`**, chạy qua CLI/module | Cùng hệ sinh thái, dùng chung `uv` | Chỉ gọi được qua subprocess |
| FFmpeg | CLI | subprocess | subprocess |

Tóm lại: Duix và FFmpeg **trung lập** về ngôn ngữ. VieNeu và ViMax **nghiêng hẳn
về Python**. Không có hạng mục nào nghiêng về TypeScript.

## Quyết định

Dùng **Python 3.12**, quản lý môi trường bằng **uv**.

Kèm theo:

- `pydantic` cho model dữ liệu (có sẵn kiểm tra ràng buộc + serialize JSON).
- `typer` cho CLI.
- `jsonschema` để đối chiếu với hợp đồng trong `schemas/`.
- `ruff` + `mypy --strict` cho chất lượng mã.

## Hệ quả

**Được:**

- VieNeu gọi thẳng trong tiến trình → ít một lớp mạng, ít một chỗ hỏng.
- ViMax dùng chung `uv` và cùng hệ sinh thái khi mở D05.
- `mypy --strict` bù lại phần lớn lợi thế kiểu tĩnh của TypeScript.

**Mất / phải chấp nhận:**

- Web UI (nếu sau này cần) sẽ phải là dự án Node riêng, gọi CLI hoặc API của
  repo này. Đây là ranh giới sạch, không phải nợ kỹ thuật.
- Máy phải có Python. Đã xử lý bằng cách để **uv tự quản runtime Python**
  (`uv python install 3.12`), không đụng tới Python hệ thống.

## Điểm lệch so với sơ đồ thư mục trong brief §6

Brief vẽ `src/domain/`, `src/orchestrator/`… Python theo bố cục `src/` cần một
thư mục gốc cho package, nên thực tế là:

```text
src/ai_video_agent/{domain,orchestrator,providers,composer,cli}/
```

Ranh giới module giữ nguyên 1:1 với brief; chỉ thêm một cấp tên package. Ngoài
ra `providers/video-api` phải viết thành `providers/video_api` vì tên module
Python không được chứa dấu gạch ngang.

## Đã cân nhắc và loại

- **TypeScript/Node**: buộc phải bọc VieNeu bằng một server Python phụ. Thêm
  tiến trình, thêm cách hỏng, không đổi lại lợi ích nào tương xứng.
- **Hai ngôn ngữ (Node điều phối + Python worker)**: phức tạp gấp đôi khi MVP
  chưa cần Web UI.
