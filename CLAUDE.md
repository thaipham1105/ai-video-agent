# CLAUDE.md — quy tắc làm việc trên repo AI-VIDEO-AGENT

Tài liệu nguồn: [AI_VIDEO_AGENT_BUILD_BRIEF.md](AI_VIDEO_AGENT_BUILD_BRIEF.md).
File này tóm tắt phần bắt buộc phải tuân theo trong mọi phiên làm việc.

## 1. Quy trình cổng (gate)

Công việc đi tuần tự D00 → D05. **Không được tự nhảy sang gate kế tiếp.**
Mỗi gate kết thúc bằng báo cáo và dừng chờ đúng câu duyệt (`D0x = APPROVED`).

| Gate | Phạm vi | Trạng thái |
|---|---|---|
| D00 | Khảo sát máy + upstream | APPROVED |
| D01 | Repo điều phối + mock pipeline | APPROVED |
| D02 | VieNeu-TTS thật | APPROVED (PO 8/10) |
| D03 | Duix-Avatar thật | HOÀN THÀNH |
| D04 | Composer FFmpeg | HOÀN THÀNH |
| D05 | ViMax / Video API tuỳ chọn | **cố ý KHÔNG mở** — tuỳ chọn, gọi API tính tiền |

Code phải tự bảo vệ ranh giới này: adapter của gate chưa mở phải ném
`GateNotReachedError` (xem `src/ai_video_agent/errors.py`).

## 2. Được tự làm, không cần hỏi

- Kiểm tra phiên bản công cụ, GPU, RAM, đĩa, trạng thái Git.
- Đọc tài liệu/repo công khai, lập bản đồ kiến trúc.
- Viết tài liệu, schema, interface, test mock, khung source nhẹ.
- Chạy test **không GPU, không tải model, không gọi API thật**.

## 3. Phải dừng xin duyệt trước khi

- Cài/cập nhật WSL, Docker Desktop, CUDA, driver NVIDIA hay phần mềm hệ thống.
- Pull Docker image, tải model hoặc dữ liệu ≥ 1 GB.
- Clone repo ra ngoài `F:\AI-VIDEO-AGENT` hoặc đổi Docker data root.
- Chạy GPU lâu, huấn luyện avatar, clone giọng thật, render video thật.
- Gọi Gemini, Veo hay bất kỳ API tính tiền nào.
- Đọc/ghi secret, `git commit`, `git push`, tạo remote, deploy.

## 4. Bảo mật và dữ liệu

- **Không** đọc, in, log hay index `.env`, API key, token, dữ liệu thật, mẫu
  giọng thật. Chỉ được kiểm tra *sự tồn tại* của biến môi trường, không đọc giá trị.
- Chỉ tạo `.env.example` với tên biến và giá trị giả.
- Không ghi key vào `CLAUDE.md`, source, test, lịch sử lệnh hay
  `.claude/settings.local.json`.
- Dữ liệu thật (model, voice sample, avatar video, renders, Docker volumes) nằm
  ở `F:\AI-VIDEO-AGENT-RUNTIME`, ngoài Git và ngoài index CodeGraph.
- Test phải mock provider. Test tự động **không được** gọi API mất tiền.

## 5. Đạo đức nội dung

- Không dùng hình ảnh/giọng của người khác nếu chưa có đồng ý rõ ràng.
  Mọi tài sản phải có `consent.status = granted` trong `asset-manifest.json`
  trước khi được dùng cho render thật.
- Video AI công khai phải có tuỳ chọn gắn nhãn AI (`project.ai_disclosure`).
- Chữ chính xác (số điện thoại, giá, pháp lý) **do composer chèn**, không giao
  cho model sinh video tự vẽ.

## 6. Quy ước code

- Ngôn ngữ: **Python 3.12** (xem [ADR-0001](docs/adr/0001-language-choice-python.md)).
- Quản lý môi trường: `uv`. Chạy lệnh qua `uv run ...`.
- `ruff` cho lint/format, `mypy --strict` cho `src/`, `pytest` cho test.
- Model dữ liệu dùng `pydantic`; mọi file JSON ghi ra đĩa phải khớp
  JSON Schema tương ứng trong `schemas/`.
- Không tự tạo lại cảnh vì lý do thẩm mỹ. Chỉ render lại shot được chỉ định
  (`aiva render --only-shot <id>`).

## 7. Trước mỗi thay đổi

```powershell
git status                 # không được làm mất thay đổi có sẵn
uv run pytest
uv run ruff check .
uv run mypy
git diff --check
```

## 8. Báo cáo sau mỗi gate

Phải gồm: kết quả chính, bằng chứng/lệnh + PASS/WARN/FAIL, file đã tạo/sửa,
diff summary, dung lượng tải thêm + VRAM/RAM/đĩa quan sát được, việc không làm
và lý do, rủi ro còn lại, câu duyệt chính xác cho gate kế tiếp.
