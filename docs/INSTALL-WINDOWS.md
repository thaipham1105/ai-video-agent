# Cài đặt trên Windows

Viết cho đúng máy đã khảo sát ở D00: Windows 11 Pro, i7-14700F, 32 GB RAM,
RTX 4070 SUPER 12 GB, dự án ở `F:\AI-VIDEO-AGENT`.

## Cần cho Gate D01 (mock pipeline)

Chỉ cần hai thứ. Không cần GPU, không cần Docker, không cần FFmpeg.

### 1. uv

```powershell
winget install --id astral-sh.uv -e --scope user
```

Mở PowerShell mới (hoặc nạp lại PATH) rồi kiểm tra:

```powershell
uv --version
```

### 2. Môi trường dự án

```powershell
cd F:\AI-VIDEO-AGENT
uv sync
```

`uv sync` tự tải runtime Python 3.12 do nó quản lý (**không** đụng Python hệ
thống), tạo `.venv` và cài toàn bộ phụ thuộc. Khoảng 30 gói, ~120 MB.

### 3. Kiểm tra

```powershell
uv run aiva doctor
```

Ở D01, các mục `ffmpeg`, `ffprobe`, `docker daemon` báo **WARN** là đúng — chúng
chỉ cần từ D03/D04 trở đi.

---

## Thư mục dữ liệu runtime

Toàn bộ dữ liệu thật nằm **ngoài** repo, mặc định `F:\AI-VIDEO-AGENT-RUNTIME`.
Thư mục này được tạo tự động khi chạy `aiva plan` lần đầu.

Đổi vị trí bằng biến môi trường:

```powershell
$env:AIVA_RUNTIME_DIR = "H:\AI-VIDEO-AGENT-RUNTIME"
```

Hoặc copy `.env.example` thành `.env` rồi sửa (`.env` đã nằm trong `.gitignore`).

> **Sao lưu:** repo Git không chứa sản phẩm. Muốn giữ video và project thì phải
> sao lưu thư mục runtime riêng. Xem [ADR-0002](adr/0002-runtime-data-outside-repo.md).

---

## Chạy thử end-to-end (toàn bộ bằng mock)

```powershell
uv run aiva plan --brief "Bán lô đất thổ cư tại Biên Hoà, sổ hồng riêng, giá 1,2 tỷ. Liên hệ 0909123456." --duration 30
uv run aiva status
uv run aiva approve <project-id> --by "Tên bạn"
uv run aiva estimate <project-id> --detail
uv run aiva render <project-id>              # dry-run, không chạy provider
uv run aiva render <project-id> --execute    # chạy pipeline bằng mock
```

Output của `--execute` mang đuôi `.mock.mp4` — đó là **file đánh dấu**, không
phải video thật. Video thật chỉ có từ D04.

---

## Chuẩn bị cho các gate sau (CHƯA cài ở D01)

### FFmpeg — cần từ D04

```powershell
winget install --id Gyan.FFmpeg -e
```

### Docker Desktop + GPU — cần từ D03

D00 đã ghi nhận Docker Desktop có mặt nhưng daemon đang tắt, và distro
`docker-desktop` ở trạng thái Stopped. Trước khi pull image Duix (~70 GB) phải:

1. Bật Docker Desktop, xác nhận `docker info` chạy được.
2. Kiểm tra GPU passthrough: `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`
3. **Cân nhắc chuyển Docker data root sang F hoặc H** — ổ C chỉ còn ~97 GB và
   `docker_data.vhdx` đang nằm ở đó. Việc này cần duyệt riêng.
4. Viết compose override cục bộ vì máy **không có ổ D** trong khi compose của
   Duix hardcode `d:/duix_avatar_data/...`.

Chi tiết: [UPSTREAM-AUDIT.md](UPSTREAM-AUDIT.md).

### VieNeu-TTS — cần từ D02

`uv add vieneu` + tải model ONNX từ Hugging Face (~1–2 GB). Chạy CPU/ONNX để
không tranh GPU với Duix.

---

## Xử lý sự cố

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `uv` không có trên PATH sau khi cài | PATH của shell cũ | Mở PowerShell mới, hoặc `$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")` |
| `python` mở Microsoft Store | Stub App Execution Alias của Windows | Bỏ qua — `uv` dùng runtime riêng, không cần Python hệ thống |
| `doctor` báo FAIL ở mục `schemas` | Chạy lệnh ngoài thư mục repo | `cd F:\AI-VIDEO-AGENT` hoặc đặt `AIVA_REPO_ROOT` |
| `Không tìm thấy file: ...project.json` | Sai `AIVA_RUNTIME_DIR` | `uv run aiva status` để xem đang trỏ vào đâu |
| Lệnh render báo cần `approve` | Project chưa được duyệt | `uv run aiva approve <id> --by "Tên"` |
| Duyệt rồi vẫn bị chặn | Storyboard đã đổi sau khi duyệt | Xem lại rồi `approve` lại |

## Lệnh phát triển

```powershell
uv run pytest          # toàn bộ test (mock, không GPU, không tải model)
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy            # typecheck strict trên src/
```
