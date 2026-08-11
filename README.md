# AI-VIDEO-AGENT

Hệ thống chạy **local trên Windows** để biến một yêu cầu tiếng Việt thành video hoàn chỉnh:

```text
Brief tiếng Việt
  -> storyboard JSON có schema
  -> duyệt kịch bản
  -> VieNeu-TTS tạo WAV
  -> Duix-Avatar nhận WAV + avatar source -> video người nói
  -> FFmpeg chèn phụ đề / logo / B-roll
  -> MP4 + manifest + báo cáo chi phí
```

Repo này là **repo điều phối (orchestrator)**. Nó *không* chứa mã nguồn của
VieNeu-TTS, Duix-Avatar hay ViMax — ba upstream đó được giữ tách biệt và chỉ
được gọi qua adapter. Xem [docs/UPSTREAM-AUDIT.md](docs/UPSTREAM-AUDIT.md).

---

## Trạng thái: Gate D03 (Duix-Avatar thật)

| Gate | Nội dung | Trạng thái |
|---|---|---|
| D00 | Khảo sát máy + upstream | ✅ APPROVED — [D00_AUDIT.md](D00_AUDIT.md) |
| D01 | Repo điều phối + mock pipeline | ✅ APPROVED — [D01_REPORT.md](D01_REPORT.md) |
| D02 | VieNeu-TTS thật | ✅ APPROVED (PO 8/10) — [D02_REPORT.md](D02_REPORT.md) |
| D03 | Duix-Avatar thật | ✅ HOÀN THÀNH — [D03_PREFLIGHT.md](D03_PREFLIGHT.md) |
| D04 | Composer FFmpeg + video hoàn chỉnh | ✅ HOÀN THÀNH |
| D05 | ViMax / Video API tuỳ chọn | ⏸ **cố ý không mở** — tuỳ chọn, gọi API tính tiền |
| D06 | Giao diện local + nghiệm thu render dài | ✅ HOÀN THÀNH — [D06_ACCEPTANCE.md](D06_ACCEPTANCE.md) |

Tổng kết: [FINAL_PROJECT_REPORT.md](FINAL_PROJECT_REPORT.md)

Từ D02, **TTS chạy thật** trên CPU/ONNX (`uv sync --extra tts`). Duix, FFmpeg và
mọi API tính tiền vẫn bị `GateNotReachedError` chặn cho tới gate của chúng.
Render pipeline vẫn mặc định dry-run và mặc định mock.

---

## Cài đặt (Windows)

Chi tiết: [docs/INSTALL-WINDOWS.md](docs/INSTALL-WINDOWS.md).

```powershell
winget install --id astral-sh.uv -e --scope user
uv sync                 # nhân lõi, nhẹ (~90 MB) — đủ cho mock pipeline
uv sync --extra tts     # thêm VieNeu-TTS thật (~550 MB gói + ~285 MB model)
uv run aiva doctor
```

Xem [ADR-0004](docs/adr/0004-vieneu-dependencies.md) để biết vì sao VieNeu là
extra riêng chứ không phải phụ thuộc chính.

---

## Dựng một video

**Cách dễ nhất** — tạo shortcut Desktop trỏ vào `scripts\aiva-ui.bat`, double-click,
điền form trên trình duyệt. Chi tiết ở [docs/VAN-HANH.md](docs/VAN-HANH.md).

```powershell
uv run aiva ui          # mở giao diện local ở http://127.0.0.1:8765/
```

Giao diện chạy trên chính máy này, chỉ bind `127.0.0.1`, và chỉ là vỏ bọc quanh
các lệnh CLI dưới đây — mọi hàng rào an toàn vẫn nguyên hiệu lực.

**Bằng dòng lệnh:**

```powershell
uv run aiva make --id video-dau-tien --brief "..."          # lập kế hoạch, in việc còn thiếu
uv run aiva avatar-add "toi-noi.mp4" --project video-dau-tien --owner "Tên bạn"
uv run aiva voice-add  "giong-toi.wav" --project video-dau-tien --owner "Tên bạn"
uv run aiva make --id video-dau-tien --brief "..." --by "Tên bạn" --mock   # chạy thử
uv run aiva make --id video-dau-tien --brief "..." --by "Tên bạn"          # dựng thật
```

Backend production là **Duix**, chạy local, không tốn tiền API.

---

## CLI

```powershell
uv run aiva doctor                      # kiểm tra môi trường, không sửa gì
uv run aiva tts-check                   # health check VieNeu bằng giọng dựng sẵn
uv run aiva tts-check --list-voices     # 14 giọng dựng sẵn
uv run aiva voice-add <file.wav> --project <id> --owner "Tên"   # đăng ký mẫu giọng
uv run aiva plan --brief "..." --duration 45     # brief tiếng Việt -> storyboard
uv run aiva status                      # liệt kê project và trạng thái
uv run aiva validate <project-id>       # kiểm tra JSON theo schemas/
uv run aiva estimate <project-id>       # bảng chi phí dự kiến
uv run aiva approve <project-id> --by "Tên"      # DRAFT/PLANNED -> APPROVED
uv run aiva render <project-id>         # MẶC ĐỊNH dry-run, không thực thi provider
uv run aiva render <project-id> --execute        # chạy provider (mặc định vẫn là mock)
```

### Ba lớp chặn chi phí

1. `render` **mặc định là dry-run** — phải có `--execute` mới chạy provider.
2. Provider **mặc định là `mock`** — phải có `--provider-mode real` mới gọi thật.
3. Provider tính tiền còn cần `--allow-paid` **và** project ở trạng thái
   `APPROVED` **và** tổng chi phí ước tính ≤ `budget.cap_usd`.

Chi tiết: [docs/COST-SAFETY.md](docs/COST-SAFETY.md).

---

## Cấu trúc

```text
AI-VIDEO-AGENT/            <- repo Git (chỉ code do dự án sở hữu)
├── docs/                  <- ARCHITECTURE, INSTALL-WINDOWS, COST-SAFETY, UPSTREAM-AUDIT, adr/
├── schemas/               <- 4 JSON Schema là hợp đồng dữ liệu
├── src/ai_video_agent/
│   ├── domain/            <- model + state machine
│   ├── orchestrator/      <- planner, estimator, cost guard, pipeline, repository
│   ├── providers/         <- vieneu/ duix/ vimax/ video_api/ (interface + mock)
│   ├── composer/          <- phụ đề + trình dựng lệnh FFmpeg
│   └── cli/
├── tests/
├── assets-example/        <- mô tả tài sản mẫu (KHÔNG chứa media thật)
└── projects-example/      <- project mẫu để đọc hiểu schema

F:\AI-VIDEO-AGENT-RUNTIME\ <- dữ liệu thật, NGOÀI Git (model, voice, renders, docker volumes)
```

Dữ liệu thật **không bao giờ** nằm trong repo này. Xem
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Quy tắc vận hành

Mọi thay đổi phải theo cổng D00 → D05 trong
[AI_VIDEO_AGENT_BUILD_BRIEF.md](AI_VIDEO_AGENT_BUILD_BRIEF.md), và tuân thủ
[CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md).

- Không dùng hình ảnh/giọng người khác khi chưa có đồng ý rõ ràng — mọi tài sản
  phải khai báo `consent` trong `asset-manifest.json`.
- Video AI công khai phải có tuỳ chọn gắn nhãn nội dung AI (`ai_disclosure`).
- Không commit secret, model, media thật hay dữ liệu khách hàng.
