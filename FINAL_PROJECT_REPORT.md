# FINAL_PROJECT_REPORT — AI-VIDEO-AGENT

- Ngày: 2026-08-05
- Máy: Windows 11 Pro, i7-14700F, 31,8 GB RAM, RTX 4070 SUPER 12 GB
- Repo: `F:\AI-VIDEO-AGENT` · Dữ liệu: `F:\AI-VIDEO-AGENT-RUNTIME` (ngoài Git)

---

## 1. Trạng thái từng gate

| Gate | Nội dung | Trạng thái |
|---|---|---|
| **D00** | Khảo sát máy + upstream | ✅ APPROVED — [D00_AUDIT.md](D00_AUDIT.md) |
| **D01** | Repo điều phối + mock pipeline | ✅ APPROVED — [D01_REPORT.md](D01_REPORT.md) |
| **D02** | VieNeu-TTS thật | ✅ APPROVED, PO chấm **8/10** — [D02_REPORT.md](D02_REPORT.md) |
| **D03** | Duix-Avatar thật | ✅ HOÀN THÀNH — [D03_PREFLIGHT.md](D03_PREFLIGHT.md) |
| **D04** | Composer FFmpeg + video hoàn chỉnh | ✅ HOÀN THÀNH |
| **D05** | ViMax / Video API tuỳ chọn | ⏸ **cố ý KHÔNG mở** |

**D05 không mở là quyết định, không phải thiếu sót.** Brief §1.5 và §D05 định vị
nó là *mô-đun mở rộng, không phải phụ thuộc của MVP*, và nó bắt buộc gọi API trả
phí ở cả ba lớp (LLM, ảnh, video). `CURRENT_GATE = "D04"` nên `ViMaxBrollProvider`
và `VideoApiBrollProvider` vẫn ném `GateNotReachedError`; có test canh điều đó.
MVP đã đủ chạy trọn vẹn mà không cần nó.

### Đối chiếu tiêu chí MVP (brief §9)

| Tiêu chí | Kết quả |
|---|---|
| Một lệnh tiếng Việt tạo storyboard có schema hợp lệ | ✅ `aiva plan` |
| Người dùng duyệt trước render | ✅ `aiva approve`, neo vào SHA-256 storyboard |
| VieNeu tạo WAV tiếng Việt | ✅ PO nghiệm thu 8/10 |
| Duix tạo đoạn avatar nói từ WAV | ✅ 228 khung, khớp audio |
| FFmpeg xuất video dọc có logo và phụ đề đúng chữ | ✅ 9:16, SRT UTF-8, nhãn AI |
| Sửa riêng thoại/cảnh, chỉ chạy lại phần phụ thuộc | ✅ `--only-shot`, cache theo hash nội dung |
| Không secret/dữ liệu thật trong Git | ✅ 9 test quét tự động |
| Test mock đạt, hướng dẫn Windows tái lập được | ✅ 258 test, [RERUN-WORKFLOW.md](docs/RERUN-WORKFLOW.md) |
| Không phát sinh chi phí API | ✅ **0,00 USD** — toàn bộ chạy local |

---

## 2. Video thành phẩm

```text
F:\AI-VIDEO-AGENT-RUNTIME\projects\demo-vn\outputs\demo-vn-5232d23403c9.mp4
```

| Thuộc tính | Giá trị |
|---|---|
| **SHA-256** | `10CA5E8CB3C45F6CAE952CAABE963D418F15A1EFAA518ADC5A23C98E0EBB040B` |
| Dung lượng | 6,54 MB (6 855 224 byte) |
| Video | H.264 **High profile**, 1080×1920 (**9:16**), 30 fps, 228 khung, yuv420p |
| Audio | AAC-LC, 48 000 Hz, mono, 357 khung |
| Thời lượng | 7,633 s |
| **Đồng bộ A/V** | video 7,600 s · audio 7,616 s · **lệch 0,016 s** (nửa khung hình) |
| Giải mã toàn bộ | **sạch**, không lỗi |
| Nội dung | Khuôn mặt thật của PO + **golden voice** `giong-toi-A-mo-dau.wav` |

Video dùng **đúng file giọng PO đã nghiệm thu 8/10**, không phải bản sinh lại:
bước TTS ghi `skipped` trong `render-manifest.json` vì shot khai
`narration_audio_asset_id = "golden-a-mo-dau"`.

### Tài sản nguồn — không đổi

| File | SHA-256 | |
|---|---|---|
| `incoming/video_cua_toi.mp4` | `71CF0BAA…1180DA` | ✅ khớp bản đầu |
| `healthcheck/giu-lai/giong-toi-A-mo-dau.wav` | `311471E7…3985C` | ✅ khớp, read-only |
| 7 WAV đối chứng trong `giu-lai/` | | ✅ còn đủ |

Video nguồn **chưa từng bị sửa, chuyển hay ghi đè**. Nó vào pipeline qua
**hardlink** (`assets/avatar/avatar-goc.mp4` — cùng inode, không nhân bản dữ
liệu) và được gắn vào container Duix bằng volume **chỉ đọc** (đã kiểm chứng:
`touch` bên trong bị từ chối "Read-only file system").

---

## 3. Cấu hình cuối

### VieNeu-TTS (D02) — 8 hằng số `GOLDEN_*` đã ghim

```python
GOLDEN_PRECISION = "int8"          GOLDEN_TEMPERATURE = 0.8
GOLDEN_STYLE = "tu_nhien"          GOLDEN_TOP_K = 25
GOLDEN_DENOISE = True              GOLDEN_TOP_P = 0.95
GOLDEN_USE_REF_CODES = True        GOLDEN_REPETITION_PENALTY = 1.2
```

backend `onnx` · device `cpu` · `torch 2.13.0+cpu` (CUDA build = None) · ra 48 kHz mono 16-bit

### Duix-Avatar (D03)

```text
guiji2025/duix.avatar@sha256:1970424d219cbb6aebc7566f069041f057ccad618a395139dce002e1fb25d5ed
```

Chỉ service `gen-video` (4,66 GB nén). **Không** tải `fish-speech-ziming`
(19,08 GB) và `fun-asr` (14,18 GB). Docker data root **không đổi** — ổ C còn
79,3 GB sau khi tải.

| | |
|---|---|
| API | `POST /easy/submit` · `GET /easy/query` (đọc từ `/code/app_local.py` trong image) |
| Volume dữ liệu | `F:/AI-VIDEO-AGENT-RUNTIME/duix_avatar_data/face2face` → `/code/data` |
| Volume tài sản | `F:/AI-VIDEO-AGENT-RUNTIME/projects` → `/inputs` **:ro** |
| GPU | `runtime: nvidia`, PyTorch 2.2.2+cu118 thấy CUDA trong container |

### FFmpeg (D04)

`ffmpeg 9.0-full_build`. Xuất H.264 High / yuv420p / AAC / `+faststart` — tương
thích Facebook, TikTok, Zalo (brief §D04.4). Font `drawtext` chỉ định tường minh
(`C:/Windows/Fonts/arial.ttf`) vì Windows không có config fontconfig mặc định.

---

## 4. Lệnh chạy lại — một lệnh

```powershell
cd F:\AI-VIDEO-AGENT; uv run aiva render demo-vn --execute --provider-mode real
```

Cần Duix đang chạy:

```powershell
docker compose -f F:\AI-VIDEO-AGENT\deploy\duix\docker-compose.yml up -d
```

Dừng để trả RAM/VRAM:

```powershell
docker compose -f F:\AI-VIDEO-AGENT\deploy\duix\docker-compose.yml down
```

Đã **kiểm chứng thật**: lệnh render ở trên chạy end-to-end và tạo ra chính video
thành phẩm nêu ở mục 2. Chi tiết và các luồng khác:
[docs/RERUN-WORKFLOW.md](docs/RERUN-WORKFLOW.md).

---

## 5. Kiểm thử

| Lệnh | Kết quả |
|---|---|
| `uv run pytest` | **258 passed** in 4,26 s |
| `uv run ruff check .` | All checks passed (14 nhóm luật) |
| `uv run ruff format --check .` | sạch |
| `uv run mypy` | Success, 44 file, **strict** |
| `git diff --check` | exit 0 |
| Quét media/secret trong Git | không có |

### Phân bố (16 file test)

| File | Test | Khoá điều gì |
|---|---|---|
| `test_composer.py` | 25 | mốc phụ đề, escape đường dẫn Windows, cờ xuất bản |
| `test_audio.py` | 24 | `inspect_wav`, `convert_to_wav`, clipping, MP3 |
| `test_providers.py` | 24 | hàng rào gate, ánh xạ đường dẫn Duix, không đọc API key |
| `test_d02_golden_config.py` | 30 | 8 hằng số golden, voice asset, chống clipping, bảo vệ golden |
| `test_d03_d04_pipeline.py` | 17 | đơn vị ms→s, tìm file kết quả, font, audio đã duyệt |
| `test_pipeline.py` | 17 | dry-run, cache từng bước, nhãn AI |
| `test_cli.py` | 16 | đường đi CLI, chặn render khi chưa duyệt |
| `test_textutil.py` | 17 | tách câu, trích số điện thoại/giá/pháp lý |
| `test_schemas.py` | 15 | model ↔ JSON Schema |
| `test_planner.py` · `test_state_machine.py` | 13 + 13 | storyboard, 7 trạng thái |
| `test_examples.py` · `test_repository.py` | 11 + 11 | project mẫu, lưu trữ |
| `test_costguard.py` · `test_no_secrets.py` · `test_estimator.py` | 10 + 9 + 8 | chặn chi phí, quét secret, ước tính |

**Không dùng hash WAV/MP4 đầu ra làm tiêu chí** — cả TTS lẫn Duix đều lấy mẫu
ngẫu nhiên. Test khoá **cấu hình**, **định dạng** và **chỉ số kỹ thuật**.

---

## 6. File đã thay đổi

99 file trong Git, nhánh `main`, **không remote**, **chưa có commit nào**.

### Mã nguồn (44 file `src/`)

| Nhóm | Thay đổi chính |
|---|---|
| `providers/vieneu/adapter.py` | 8 hằng số `GOLDEN_*`, `limit_peak()`, chặn ghi golden |
| `providers/duix/adapter.py` | HTTP client thật, `DuixJob`, `to_container_path()`, `duration_seconds()` (ms→s), dò file kết quả |
| `composer/runner.py` | `FfmpegComposer` chạy thật, bắt lỗi, kiểm tra output |
| `composer/ffmpeg.py` | `FONT_CANDIDATES`, `default_font_file()` |
| `composer/audio.py` | `inspect_wav()`, `convert_to_wav()` |
| `orchestrator/pipeline.py` | dùng lại **theo từng bước**, `_approved_audio()`, gom output provider về cache |
| `domain/storyboard.py` | `Shot.narration_audio_asset_id` |
| `domain/project.py` | `ProviderSelection.voice_asset_id` |
| `paths.py` | `assert_writable()` bảo vệ thư mục đối chứng |
| `config.py` | `duix_inputs_mount`, `duix_data_dir`, `duix_image_digest` |
| `cli/main.py` | `tts-check`, `voice-add`, composer theo chế độ provider |

### Cấu hình & schema

`pyproject.toml` (extra `tts`, `clone`; ghim `numpy<2.3`; loại `perth`),
`schemas/project.schema.json`, `schemas/storyboard.schema.json`,
`deploy/duix/docker-compose.yml`.

### Tài liệu

4 ADR, `ARCHITECTURE`, `COST-SAFETY`, `UPSTREAM-AUDIT`, `INSTALL-WINDOWS`,
`VOICE-SAMPLE-GUIDE`, `kich-ban-thu-giong`, `BACKLOG`, `RERUN-WORKFLOW`,
`deploy/duix/README`, và 5 báo cáo gate.

---

## 7. Dung lượng và tài nguyên

| Hạng mục | Dung lượng |
|---|---|
| `.venv` (85 gói, gồm torch CPU) | 1 167 MB |
| Model VieNeu ONNX int8 + codec | 284,9 MB |
| Model VieNeu fp32 (đã thử, PO không chọn) | 480,4 MB |
| Image Duix (giải nén) | 13,84 GB |
| FFmpeg | ~200 MB |
| Ổ C còn trống | 79,3 GB |

Sau khi dừng container: VRAM **6 531 → 1 550 MiB** (trả lại 4 981 MiB), RAM
trống 10,9 GB, **0 container còn chạy**.

**Chi phí API: 0,00 USD.** Không gọi dịch vụ tính tiền nào ở bất kỳ gate nào.

---

## 8. Hạn chế còn lại

1. **Độ giống giọng dừng ở 8/10.** Thu lại với nguồn sạch hơn (clipping 0 %,
   sàn nhiễu −71 dBFS) cho bản *tự nhiên hơn* nhưng **không giống hơn** — PO
   chọn bản cũ. Giới hạn nằm ở mô hình với chất giọng này, không ở tham số.
   Vượt 8/10 có lẽ phải đổi hướng (fine-tune hoặc mô hình khác).
2. **Chưa kiểm chứng cách đọc chữ số.** `giong-toi-B-so.wav` có "1,2 tỷ" và
   "0909123456" nhưng PO chưa chấm riêng. Nếu TTS đọc sai, cách xử lý là viết
   thoại thành chữ còn chữ trên màn hình giữ chữ số — composer đã sẵn sàng.
3. **Video thành phẩm mới có một shot 7,6 s.** Đường nhiều shot đã có test
   (mock) nhưng chưa chạy thật với Duix nhiều lần liên tiếp.
4. **Duix chạy một job tại một thời điểm** (`get_run_flag`). Nhiều shot sẽ render
   tuần tự; video dài sẽ lâu tương ứng.
5. **onnxruntime CUDA EP trong container Duix hỏng** (thiếu `libcublasLt.so.11`)
   nên bộ dò khuôn mặt chạy CPU. Không ảnh hưởng kết quả — nhánh chính dùng
   PyTorch CUDA và hoạt động bình thường.
6. **License Duix là license cộng đồng riêng.** Trong ngưỡng miễn phí thì ổn,
   nhưng phải đọc nguyên văn trước khi phát hành sản phẩm ra công chúng.
7. **Chưa có commit nào.** Toàn bộ đang ở working tree, theo brief §4 (không
   commit khi chưa được yêu cầu).
8. **BL-001 "Tủ đồ AI"** đã ghi nhận trong [docs/BACKLOG.md](docs/BACKLOG.md),
   chờ gate riêng sau khi D03/D04 ổn định.

---

## 9. Kết luận

Toàn bộ roadmap D00→D04 đã hoàn thành. D05 cố ý để nguyên trạng thái khoá đúng
theo định vị "mô-đun mở rộng tuỳ chọn" của brief.

Một lệnh tiếng Việt đi trọn đường: storyboard → duyệt → giọng của PO →
khuôn mặt của PO → phụ đề + chữ chính xác + nhãn AI → MP4 dọc 9:16 phát được
trên Facebook/TikTok/Zalo. Toàn bộ chạy local, không tốn một đồng API.

```text
PROJECT_COMPLETE=true
```
