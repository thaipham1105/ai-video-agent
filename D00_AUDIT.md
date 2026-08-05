# D00_AUDIT — Khảo sát máy và upstream (Gate D00)

- Ngày khảo sát: 2026-08-04
- Máy: Windows 11 Pro (build 26100), Intel Core i7-14700F, 31,8 GB RAM, NVIDIA RTX 4070 SUPER 12 GB (driver 591.86, CUDA reported 13.1)
- Phạm vi: chỉ khảo sát, **không** cài đặt, không pull image, không tải model, không sửa hệ thống.

## 1. Bảng trạng thái công cụ và môi trường

| Hạng mục | Kết quả kiểm tra (bằng chứng) | Trạng thái |
|---|---|---|
| PowerShell | 5.1.26100.8875 | PASS |
| git | 2.54.0.windows.1 (`git --version`) | PASS |
| claude (Claude Code) | 2.1.221 | PASS |
| nvidia-smi / driver | RTX 4070 SUPER 12282 MiB, driver 591.86, CUDA 13.1 | PASS |
| node / npm | v24.16.0 / 11.13.0 | PASS |
| python | **Chưa cài** — PATH chỉ có stub Microsoft Store (`Python was not found; run without arguments to install...`) | WARN |
| uv | Không có trên PATH | WARN |
| ffmpeg / ffprobe | Không có trên PATH | WARN |
| docker CLI | Client 29.6.1 (Docker Desktop) có mặt | PASS |
| docker daemon | **Không chạy** — `docker version` báo không kết nối được `dockerDesktopLinuxEngine` pipe; distro `docker-desktop` đang Stopped. Không tự khởi động theo nguyên tắc D00. | WARN |
| WSL2 | Đã cài, default version 2; distro: Ubuntu (Stopped), docker-desktop (Stopped) | PASS |
| GPU đang dùng | ~2,5 GB / 12 GB VRAM bị chiếm bởi các app desktop (Chrome, Zalo, Adobe, …) khi idle | WARN |

## 2. Dung lượng đĩa và vị trí Docker data

| Ổ | Tổng | Trống | Ghi chú |
|---|---|---|---|
| C | 441,8 GB | **97,0 GB** | Duix khuyến nghị 100 GB trống trên C → sát ngưỡng |
| E | 931,5 GB | 362,6 GB | |
| F (dự án) | 390,6 GB | **382,1 GB** | Đủ chỗ cho runtime data/model |
| H | 1863 GB | 1447,8 GB | |
| **D** | — | — | **Máy KHÔNG có ổ D**, trong khi docker-compose của Duix hardcode `d:/duix_avatar_data/...` |

Vị trí Docker data hiện tại (chỉ ghi nhận, **không di chuyển**):

- `docker-desktop` distro: `C:\Users\admin\AppData\Local\Docker\wsl\main`
- `docker_data.vhdx`: `C:\Users\admin\AppData\Local\Docker\wsl\disk\docker_data.vhdx` — hiện **18,68 GB**, nằm trên ổ C.
- Ubuntu distro: `C:\Users\admin\AppData\Local\wsl\{1fe5639b-...}`

→ Nếu pull ~70 GB image Duix vào vị trí hiện tại, ổ C (97 GB trống) sẽ gần cạn. Đề xuất ở D03: chuyển Docker data root sang F hoặc H (cần duyệt riêng, chưa làm).

## 3. Cổng local dự kiến

Đã kiểm tra `Get-NetTCPConnection -State Listen`: các cổng **3000, 4173, 5000, 7860, 8000, 8004, 8080, 8383, 10095, 18180, 18181, 18182 đều trống** → PASS, không có xung đột.

Cổng thực tế upstream sẽ dùng (từ `deploy/docker-compose.yml` của Duix và docs ViMax):

- Duix TTS (fish-speech-ziming): `18180:8080`
- Duix ASR (fun-asr): `10095:10095`
- Duix gen-video (duix.avatar): `8383:8383`
- ViMax Web UI (giai đoạn mở rộng): `4173`

## 4. Khảo sát 3 upstream

### 4.1 Duix-Avatar (`duixcom/Duix-Avatar`)

- **Chức năng**: digital human offline — clone giọng + khẩu hình, lip-sync video từ WAV.
- **License**: cộng đồng riêng, cho phép dùng thương mại miễn phí với tổ chức < 100.000 user hoặc < 10 triệu USD doanh thu/năm → cần đọc kỹ nguyên văn trước khi phát hành sản phẩm.
- **Cài đặt**: Docker Compose, 3 service (`guiji2025/fish-speech-ziming`, `guiji2025/fun-asr`, `guiji2025/duix.avatar`), tổng tải **~70 GB**, yêu cầu ~100 GB trống. Có biến thể `docker-compose-lite.yml` (1 service) và `docker-compose-5090.yml`.
- **API local**: train `POST /train`; TTS `POST http://127.0.0.1:18180/v1/invoke`; synthesis `POST http://127.0.0.1:8383/easy/submit`; tiến độ `GET /easy/query?code={taskCode}`.
- **Vấn đề Windows**: compose hardcode volume `d:/duix_avatar_data/voice/data` và `d:/duix_avatar_data/face2face` — máy không có ổ D → phải dùng bản compose override cục bộ trỏ sang `F:\` (sửa file compose copy riêng, không sửa upstream) hoặc tạo ổ D ảo. Quyết định ở D03.
- **Tích hợp đề xuất**: adapter HTTP gọi endpoint `8383` (submit/query) — khả thi, không cần sửa mã upstream. MVP chỉ cần service gen-video (+ có thể bỏ TTS/ASR của Duix vì đã có VieNeu) → cân nhắc compose-lite để giảm dung lượng tải.

### 4.2 VieNeu-TTS (`pnnbao97/VieNeu-TTS`)

- **Chức năng**: TTS tiếng Việt (kèm song ngữ Việt–Anh), clone giọng từ mẫu 3–8 giây, v3 Turbo chạy **ONNX int8 trên CPU** (48 kHz), không bắt buộc GPU.
- **License**: Apache 2.0 → PASS.
- **Cài đặt**: PyPI `pip install vieneu` (hoặc `uv`); model tải từ Hugging Face (bản ONNX nhẹ, ước tính < 2 GB). Hỗ trợ Windows chính thức.
- **SDK**: `from vieneu import Vieneu; audio = vieneu.infer(text, voice=...)` — voice clone qua `ref_audio=` (cần engine PyTorch cho clone; giọng dựng sẵn chỉ cần ONNX).
- **Tích hợp đề xuất**: **SDK Python trong process** (không cần server) → khớp tiêu chí D02 "ưu tiên CPU/ONNX trước để tránh xung đột GPU với Duix". Đây là bằng chứng mạnh nghiêng về chọn **Python** cho repo điều phối (sẽ chốt bằng ADR ở D01).

### 4.3 ViMax (`HKUDS/ViMax`)

- **Chức năng**: agentic video generation (Idea2Video / Script2Video / Novel2Video), TUI + Web UI.
- **License**: MIT → PASS.
- **Cài đặt**: clone + `uv sync`; chạy qua script Python hoặc `vimax tui`; Web UI Node tại `127.0.0.1:4173`. Hỗ trợ Windows.
- **Phụ thuộc**: yêu cầu **API trả phí** cho cả 3 lớp (LLM, image, video — Veo/Seedance) → đúng định vị trong brief: chỉ là mô-đun mở rộng D05, bắt buộc estimate + hard cap + duyệt rõ ràng, **không** đưa vào MVP.
- **Tích hợp đề xuất**: provider tùy chọn qua CLI/module ở D05, mặc định tắt.

## 5. Ước tính dung lượng tải thêm (chưa tải gì ở D00)

| Hạng mục | Ước tính | Gate |
|---|---|---|
| Python 3.11+/3.12 + uv | ~0,2 GB | D01 (cần duyệt vì là cài phần mềm) |
| FFmpeg (bản build Windows) | ~0,2 GB | D01/D04 |
| VieNeu (`pip install vieneu` + model ONNX từ HF) | ~1–2 GB | D02 |
| Duix Docker images (bản full 3 service) | **~70 GB** (lite ít hơn, cần đo khi pull) | D03 |
| ViMax (`uv sync`, không model local) | ~1 GB | D05 (tùy chọn) |

## 6. Rủi ro còn lại

1. **Ổ C sát ngưỡng (97 GB trống)** trong khi Docker data root đang ở C và Duix cần ~70–100 GB → nếu không chuyển Docker data sang F/H trước khi pull, C có nguy cơ cạn. Việc chuyển cần duyệt riêng ở D03.
2. **Không có ổ D** — compose Duix hardcode `d:/duix_avatar_data` → phải override volume path; nếu quên, container tạo/ghi sai chỗ hoặc fail.
3. **VRAM 12 GB nhưng desktop đang chiếm ~2,5 GB** — khi render Duix nên đóng bớt app GPU; VieNeu chạy CPU/ONNX để né xung đột (đúng chiến lược D02).
4. **Python chưa có thật** — stub Microsoft Store dễ gây nhầm khi setup; cần cài Python chuẩn (python.org hoặc uv-managed) ở D01.
5. **Docker daemon đang tắt** — chưa xác nhận được GPU passthrough (`docker run --gpus`) hoạt động; phải health check ở đầu D03 trước khi pull.
6. **License Duix là license cộng đồng riêng** (không phải OSI chuẩn) — trong ngưỡng miễn phí thì ổn, nhưng cần lưu nguyên văn vào `docs/UPSTREAM-AUDIT.md` ở D01 và ghi nhận khi phát hành.
7. **RAM 32 GB** đạt mức tối thiểu Duix khuyến nghị — chạy đồng thời Duix + trình duyệt + app nặng có thể chật; pipeline nên chạy tuần tự (TTS xong mới render avatar).
8. Video AI công khai phải có tùy chọn gắn nhãn AI; asset giọng/hình phải có ghi nhận đồng ý sử dụng trong `asset-manifest.json` (thiết kế ở D01).

## 7. Phương án kiến trúc đề xuất

- **Ngôn ngữ repo điều phối: Python** (chốt bằng ADR ở D01). Bằng chứng: VieNeu là SDK Python thuần, ViMax là Python/uv, Duix chỉ cần HTTP client — Python phủ cả ba; Node chỉ cần cho Web UI ViMax (ngoài MVP).
- **Tích hợp qua adapter, upstream tách biệt** đúng mục 3 của brief:
  - `providers/vieneu`: gọi SDK `vieneu` in-process, chạy CPU/ONNX.
  - `providers/duix`: HTTP adapter tới `127.0.0.1:8383` (`/easy/submit`, `/easy/query`); Duix chạy bằng Docker Compose override cục bộ (volume trỏ `F:\AI-VIDEO-AGENT-RUNTIME\duix_avatar_data`), pin image digest.
  - `providers/vimax` + `providers/video-api`: interface + mock ở D01, hiện thực thật chỉ ở D05 sau estimate/hard cap/duyệt.
  - `composer`: FFmpeg CLI wrapper, chèn phụ đề/logo/chữ chính xác.
- **Dữ liệu runtime** (model, voice sample, avatar video, renders, Docker volumes) đặt ngoài repo Git, đề xuất `F:\AI-VIDEO-AGENT-RUNTIME\`, được `.gitignore` và loại khỏi CodeGraph index.
- Cấu trúc repo, schema (`project.json`, `storyboard.json`, `asset-manifest.json`, `render-manifest.json`), state machine và CLI (`doctor/plan/estimate/render --dry-run/status`) theo đúng mục 6–7 của brief, dựng ở D01 với mock toàn bộ provider.

## 8. Lệnh dự kiến chạy ở Gate D01 (chưa chạy)

```powershell
# Cài Python + uv (cần duyệt vì là cài phần mềm):
winget install astral-sh.uv          # uv tự quản Python runtime
# hoặc: winget install Python.Python.3.12

# Cài FFmpeg:
winget install Gyan.FFmpeg

# Khởi tạo repo điều phối (trong F:\AI-VIDEO-AGENT):
git init
uv init --package ai-video-agent
uv add pydantic typer pytest
# Tạo skeleton src/, schemas/, tests/, .env.example, .gitignore, docs/ (ADR, ARCHITECTURE, COST-SAFETY, UPSTREAM-AUDIT)
uv run pytest            # toàn bộ test mock, không GPU, không tải model
git diff --check
```

## 9. Việc KHÔNG làm ở D00 và lý do

- Không khởi động Docker Desktop / WSL distro (tránh thay đổi trạng thái dịch vụ ngoài phạm vi khảo sát).
- Không cài Python, uv, FFmpeg (thuộc danh mục phải duyệt).
- Không pull image, không tải model, không clone 3 repo upstream (chỉ đọc docs công khai qua web).
- Không `git init` hay viết code (thuộc D01).
- Không đọc/ghi secret; thư mục hiện chưa có `.env` hay dữ liệu thật.

## 10. Kết luận

Máy đạt yêu cầu phần cứng của cả pipeline (đúng cấu hình brief: i7-14700F, 32 GB RAM, RTX 4070 SUPER 12 GB). Chưa có blocker cứng; các mục WARN (Python/uv/FFmpeg chưa cài, Docker daemon tắt, Docker data trên C, không có ổ D) đều có phương án xử lý ở các Gate sau và đã nêu ở mục 6.

**Chờ duyệt: trả lời đúng câu `D00 = APPROVED` để bắt đầu Gate D01.**
