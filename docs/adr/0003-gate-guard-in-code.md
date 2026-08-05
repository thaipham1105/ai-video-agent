# ADR-0003 — Ranh giới gate được thực thi bằng mã, không chỉ bằng tài liệu

- Trạng thái: **Chấp nhận** (Gate D01)
- Ngày: 2026-08-04
- Bối cảnh: brief §5 liệt kê những việc phải dừng xin duyệt: tải model, pull
  Docker image, chạy GPU lâu, gọi API tính tiền…

## Vấn đề

Quy trình gate viết trong tài liệu chỉ có tác dụng khi người (hoặc agent) đọc
tài liệu nhớ ra đúng lúc. Một lần quên là một lần tải 70 GB image hoặc một hoá
đơn API ngoài dự tính. Tài liệu là hàng rào mềm; cần thêm hàng rào cứng.

## Quyết định

Biến ranh giới gate thành mã chạy được.

1. `ai_video_agent.CURRENT_GATE` giữ gate cao nhất đã được duyệt (hiện là
   `"D01"`), và `gate_is_open()` so sánh theo thứ tự trong `GATES`.
2. Mỗi adapter thật khai báo hằng `GATE` của nó và kiểm tra trước khi làm bất cứ
   việc gì tốn kém:

   | Adapter | Gate | Việc bị chặn |
   |---|---|---|
   | `providers/vieneu/adapter.py` | D02 | tải model, sinh giọng |
   | `providers/duix/adapter.py` | D03 | pull image ~70 GB, chạy GPU |
   | `composer/runner.py::FfmpegComposer` | D04 | chạy FFmpeg thật |
   | `providers/vimax/adapter.py` | D05 | gọi API LLM/image/video trả phí |
   | `providers/video_api/adapter.py` | D05 | gọi API sinh video trả phí |

3. Vi phạm ném `GateNotReachedError` kèm gợi ý khắc phục, chứ không im lặng
   chạy tiếp.
4. `tests/test_providers.py` kiểm tra từng hàng rào, nên hạ gate xuống là một
   thay đổi **cố ý và nhìn thấy được** trong diff, không phải tai nạn.

## Quan trọng: `quote()` không bị chặn

Adapter thật vẫn báo giá được ở mọi gate, vì `quote()` chỉ tính toán. Nhờ vậy
`aiva estimate` và `aiva render --dry-run` cho ra con số thật của cấu hình thật
mà không chạm vào provider nào.

## Mở gate như thế nào

Khi người dùng duyệt gate kế tiếp: sửa `CURRENT_GATE` trong
`src/ai_video_agent/__init__.py`, cập nhật bảng trong `CLAUDE.md` và `README.md`.
Đây là một thay đổi một dòng, cố tình để nó hiện rõ trong code review.

## Hệ quả

- Không thể "vô tình" chạy việc của gate sau.
- Thông báo lỗi trở thành tài liệu tại chỗ: nó nói rõ gate nào mở tính năng đó.
- Đổi lại phải nhớ cập nhật `CURRENT_GATE` — chi phí nhỏ so với việc chặn được
  một lần tải 70 GB hay một hoá đơn API ngoài ý muốn.
