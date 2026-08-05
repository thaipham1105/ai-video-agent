# D02_REPORT — VieNeu-TTS thật (Gate D02)

- Ngày: 2026-08-04
- Máy: Windows 11 Pro, i7-14700F, 31,8 GB RAM, RTX 4070 SUPER 12 GB
- Phạm vi: **chỉ D02**. Không đụng Duix, không FFmpeg, không API tính tiền,
  không xử lý `video_cua_toi.mp4`, không commit/push.

---

## 1. Kết quả chính

VieNeu-TTS chạy thật trên CPU/ONNX, nhân bản được giọng của chủ máy.

### Nghiệm thu của PO

| | |
|---|---|
| **File được chọn chính thức** | `giong-toi-A-mo-dau.wav` |
| **Điểm tổng thể** | **8/10** |
| Bản giống giọng nhất | `giong-toi-A-mo-dau.wav` |
| Bản tự nhiên nhất | `N1-thu-moi-y-het-doi-chung.wav` |
| Quyết định | **ưu tiên độ giống giọng hơn độ tự nhiên** |

> **`N1` là phương án tự nhiên nhất nhưng KHÔNG được PO chọn.** Nó dùng bản thu
> mới `voice-v2`. Model **fp32** và bản thu **voice-v2** cũng không được chọn.
> Ghi rõ ở đây để người sau không "tối ưu" ngược lại quyết định này.

Golden reference:

```text
F:\AI-VIDEO-AGENT-RUNTIME\healthcheck\giu-lai\giong-toi-A-mo-dau.wav
sha256 311471E7D059BA11245586E18D5FF2B6A5EDA5B81F1A48A2AF4D7D2E6253985C
7,68 s · 48 000 Hz · mono · 16-bit · peak 0,9740 · clipping 0,000 %
```

### Đối chiếu với brief §D02

| Yêu cầu | Trạng thái |
|---|---|
| 1. Cài VieNeu ít rủi ro nhất, ưu tiên CPU/ONNX tránh xung đột GPU với Duix | ✅ ONNX int8 trên CPU; `torch 2.13.0+cpu`, `CUDA build = None` |
| 2. Health check bằng giọng dựng sẵn, câu tiếng Việt không nhạy cảm | ✅ `tts-preset.wav` — 4,64 s, 48 kHz, clipping 0 % |
| 3. Chỉ xin mẫu giọng **sau khi** health check đạt | ✅ đúng thứ tự |
| 4. Không tự phát/lưu mẫu giọng trong repo | ✅ toàn bộ ở runtime, test quét Git canh |
| 5. Xuất WAV, kiểm tra duration/sample rate/clipping/tồn tại | ✅ `inspect_wav`, 4 mục |
| 6. Dừng chờ duyệt | ✅ báo cáo này |

---

## 2. Cấu hình cuối cùng

Đã ghim vào `src/ai_video_agent/providers/vieneu/adapter.py`:

```python
GOLDEN_PRECISION = "int8"
GOLDEN_STYLE = "tu_nhien"
GOLDEN_DENOISE = True
GOLDEN_USE_REF_CODES = True
GOLDEN_TEMPERATURE = 0.8
GOLDEN_TOP_K = 25
GOLDEN_TOP_P = 0.95
GOLDEN_REPETITION_PENALTY = 1.2
```

| Mục | Giá trị |
|---|---|
| Engine | VieNeu-TTS v3 Turbo, backend **onnx**, device **cpu** |
| Model | `pnnbao-ump/VieNeu-TTS-v3-Turbo`, thư mục `onnx_int8/` |
| Codec | `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX` |
| Mẫu giọng | asset `voice-chinh` (bản thu gốc 66,62 s), VieNeu lấy 8 giây đầu sau khi cắt lặng |
| Đầu ra | 48 000 Hz, mono, 16-bit PCM |
| Chống clipping | `limit_peak()` — chỉ can thiệp khi đỉnh > 1,0 |

Ba lựa chọn được ghim cứng để giữ chiến lược brief §D02.1: `backend="onnx"`,
`device="cpu"`, `precision="int8"`. Chi tiết:
[ADR-0004](docs/adr/0004-vieneu-dependencies.md).

### Bốn điểm đã sửa để adapter khớp golden

Cấu hình cũ cho ra **cùng kết quả** nhưng theo cách không an toàn:

| # | Vấn đề | Cách sửa |
|---|---|---|
| 1 | `use_ref_codes`, `temperature`, `top_k`, `top_p`, `repetition_penalty` **không được truyền** — ăn theo mặc định của `vieneu` | Truyền tường minh từ hằng số `GOLDEN_*`. Bản `vieneu` sau đổi mặc định thì giọng không đổi theo. |
| 2 | **Không chống clipping đầu ra.** Model có thể trả đỉnh > 1,0 — đã xảy ra thật ở biến thể N2 (1,046 → 7 mẫu bị cắt) | `limit_peak()` hạ về 0,97 khi vượt thang. Đỉnh dưới 1,0 **giữ nguyên tuyệt đối**, nên golden (0,974) không đổi. |
| 3 | Chọn mẫu giọng bằng "lấy cái đầu tiên trong manifest" — thêm `voice-v2` là giọng đổi thầm lặng | Thêm `providers.voice_asset_id`, project chốt `voice-chinh`. Sai ID thì báo lỗi ngay. |
| 4 | Không có gì chặn ghi đè golden reference | `paths.assert_writable()` từ chối mọi lệnh ghi vào thư mục `giu-lai/`; file cũng đặt read-only trên đĩa. |

Không đổi: precision, style, denoise, model repo, sample rate — vốn đã khớp.

---

## 3. Bằng chứng

### Kiểm tra tự động

| Lệnh | Kết quả | |
|---|---|---|
| `uv run pytest` | **238 passed** in 3,79 s | PASS |
| `uv run ruff check .` | All checks passed | PASS |
| `uv run ruff format --check .` | 80 files already formatted | PASS |
| `uv run mypy` | Success, 44 file, strict | PASS |
| `git diff --check` | sạch, exit 0 | PASS |
| Quét media/secret trong Git | không có file `.wav/.mp3/.mp4` nào | PASS |

Tăng từ 208 → **238 test** (thêm 30 test chống hồi quy D02).

### Nhóm test chống hồi quy — `tests/test_d02_golden_config.py`

| Nhóm | Số test | Khoá điều gì |
|---|---|---|
| model / precision | 3 | `int8` chứ không phải fp32; danh tính ghi vào manifest; luôn CPU/ONNX |
| tham số sinh giọng | 9 | 7 hằng số `GOLDEN_*`; adapter lấy đúng mặc định; **mọi tham số được truyền tường minh tới `infer()`** |
| voice asset | 4 | chọn đúng `voice-chinh` dù manifest thêm `voice-v2` hay đảo thứ tự; thiếu ID thì báo lỗi; tương thích ngược |
| đầu ra không clipping | 5 | hạ biên độ khi > 1,0; **không đụng khi ≤ 1,0**; mảng rỗng/im lặng; định dạng 48 kHz mono 16-bit |
| bảo vệ golden | 6 | từ chối ghi vào `giu-lai/`; vẫn ghi bình thường ngoài đó; `synthesize()` chặn trước khi nạp model |
| ghi nhận quyết định PO | 1 | fp32 và voice-v2 không được chọn |

**Không dùng so khớp hash WAV đầu ra làm tiêu chí.** Sinh giọng có lấy mẫu ngẫu
nhiên (`temperature=0.8`) và seed gốc không tái lập được, nên hai lần chạy cùng
cấu hình vẫn cho hash khác nhau. Nhóm test khoá **cấu hình**, **định dạng** và
**chỉ số kỹ thuật** — những thứ tất định.

Hai test đáng chú ý dùng **engine giả** bơm vào adapter: chúng kiểm tra đường
gọi thật (`infer()` nhận đúng 7 tham số; đỉnh 1,046 vào thì file ghi ra clipping
0 %) mà không phải nạp model 285 MB.

### Kiểm tra thủ công — nghe bằng tai

PO nghe và chấm 11 file. Bảng điểm bốn biến thể cải tiến trên nguồn cũ:

| | giống | tự nhiên | rõ |
|---|---|---|---|
| V1 (fp32, tham chiếu gốc) | 5/10 | 6/10 | 8/10 |
| V2 (fp32 + tham chiếu đã làm sạch) | 5/10 | 6/10 | 8/10 |
| V3 (bỏ `ref_codes`) | 6/10 | 7/10 | 8/10 |
| V4 (temperature 0,95) | 5/10 | 7/10 | 8/10 |

**Kết luận quan trọng: mọi giả thuyết cải tiến đều sai.** Gỡ kẹp trần (nội suy
4 317 mẫu), chọn đoạn nói liên tục nhất (30,6→38,6 s, 87,5 % tiếng nói), lấy vân
giọng từ 24 giây, và nâng int8 → fp32 — **không cái nào nâng được độ giống**.
V1 và V2 bằng điểm nhau đúng 5/10 dù tham chiếu khác hẳn.

Vòng thu lại (`voice-v2`: 82,4 s, clipping 0 %, sàn nhiễu −71 dBFS) cho N1 tự
nhiên hơn thật, nhưng PO vẫn chọn bản cũ vì **giống hơn**. Đây là đánh đổi có
thật giữa "giống" và "tự nhiên", và PO đã chọn phía "giống".

### Health check giọng dựng sẵn (brief §D02.2)

| Mục | Giá trị | |
|---|---|---|
| file tồn tại | 435 KB | PASS |
| thời lượng | 4,64 s | PASS |
| sample rate | 48 000 Hz | PASS |
| clipping | 0,000 % | PASS |
| RMS | 0,1099 (không câm) | PASS |

Chạy 8,2 s trên CPU, **VRAM dự án dùng 0 MiB**. Kiểm chứng model thật sự tổng
hợp: cùng câu, giọng "Minh Đức" ra 4,64 s còn "Trúc Ly" ra 4,08 s, hash khác nhau.

---

## 4. File đã tạo hoặc sửa ở D02

### Sửa

| File | Nội dung |
|---|---|
| `pyproject.toml` | thêm extra `tts` và `clone`; ghim `numpy<2.3`; loại `perth`; mypy override cho `vieneu`/`soundfile` |
| `src/ai_video_agent/__init__.py` | `CURRENT_GATE` D01 → **D02** |
| `src/ai_video_agent/providers/vieneu/adapter.py` | hiện thực thật; 8 hằng số `GOLDEN_*`; `limit_peak()`; `assert_writable()` |
| `src/ai_video_agent/paths.py` | `PROTECTED_DIR_NAMES`, `is_protected()`, `assert_writable()` |
| `src/ai_video_agent/composer/audio.py` | **mới ở D02** — `inspect_wav()`, `convert_to_wav()`, `READABLE_SUFFIXES` |
| `src/ai_video_agent/composer/__init__.py` | xuất `inspect_wav`, `WavReport` |
| `src/ai_video_agent/domain/project.py` | `ProviderSelection.voice_asset_id` |
| `src/ai_video_agent/orchestrator/pipeline.py` | `_select_voice_asset()` chọn theo ID đã chốt |
| `src/ai_video_agent/cli/main.py` | lệnh `tts-check`, `voice-add`; chặn ghi đè golden |
| `schemas/project.schema.json` | thêm `providers.voice_asset_id` |
| `tests/conftest.py` | `HF_HUB_OFFLINE=1` — chốt chặn test không chạm mạng |
| `tests/test_providers.py` | cập nhật cho gate D02; thêm 6 test adapter thật |
| `README.md`, `CLAUDE.md` | bảng gate D01 APPROVED, D02 đang chạy |

### Tạo mới

| File | Nội dung |
|---|---|
| `src/ai_video_agent/composer/audio.py` | kiểm tra và chuyển đổi audio |
| `tests/test_audio.py` | 24 test cho `inspect_wav`/`convert_to_wav` |
| `tests/test_d02_golden_config.py` | **30 test chống hồi quy cấu hình golden** |
| `docs/adr/0004-vieneu-dependencies.md` | ADR: extra riêng, ghim numpy, loại perth, torch cho cloning |
| `docs/VOICE-SAMPLE-GUIDE.md` | hướng dẫn thu mẫu giọng, mức âm lượng, chuẩn WAV |
| `docs/kich-ban-thu-giong.md` | kịch bản thu 60–90 giây |
| `docs/BACKLOG.md` | BL-001 Tủ đồ AI (chỉ ghi nhận) |
| `D02_REPORT.md` | báo cáo này |

Repo: **94 file** sẽ vào Git, nhánh `main`, không remote, vẫn **chưa có commit nào**.

---

## 5. Dung lượng tải thêm và tài nguyên

| Hạng mục | Dung lượng |
|---|---|
| 63 gói cho extra `tts` (vieneu, onnxruntime, librosa, gradio…) | ~250 MB nén / 551 MB đĩa |
| `torch 2.13.0+cpu` + `torchaudio` cho extra `clone` | ~150 MB nén / 484 MB đĩa |
| Model ONNX **int8** + codec (cache Hugging Face) | **284,9 MB** |
| Model ONNX **fp32** (đã thử, PO không chọn) | thêm 480,4 MB |
| **Tổng cache HF** | **765,3 MB** |
| `.venv` | 89,5 MB → **1 167,1 MB** |

Không hạng mục đơn lẻ nào chạm ngưỡng 1 GB của brief §5.

D00 ước tính model "1–2 GB"; thực tế **284,9 MB** vì thư viện dùng
`hf_hub_download` theo từng file trong `onnx_int8/`, không bao giờ gọi
`snapshot_download` trên repo 7,6 GB.

| Tài nguyên | Giá trị |
|---|---|
| VRAM do dự án dùng | **0 MiB** (`torch.cuda.is_available() = False`) |
| Thời gian sinh giọng | 8,2 s lần đầu (kèm nạp model), 2–5 s các lần sau |
| Ổ C trống | 96,1 → ~94,5 GB |

---

## 6. Việc KHÔNG làm và lý do

| Không làm | Lý do |
|---|---|
| Chuyển sang **fp32** | PO không chọn. Có test canh `precision == "int8"`. |
| Chuyển sang bản thu **voice-v2** | PO không chọn. Project chốt `voice_asset_id = voice-chinh`. |
| Áp cấu hình **N1** | Tự nhiên hơn nhưng PO ưu tiên độ giống. |
| Hạ âm lượng bản thu v2 −2,07 dB | PO bác bỏ có lý: peak 0,8253 an toàn, clipping 0 %, RMS đã sát mép dưới. Hệ số đỉnh/RMS 22 dB khiến không thể ép cả hai vào dải cùng lúc — **ngưỡng của tôi sai, không phải bản thu sai**. |
| Xử lý `video_cua_toi.mp4` | Thuộc D03. File 84 MB còn nguyên trong `incoming\`. |
| Cài FFmpeg | Thuộc D04. `libsndfile 1.2.2` đã đọc được MP3 nên D02 không cần. |
| Đóng dấu ẩn trong audio (`perth`) | Gói `perth` trên PyPI là dự án khác hoàn toàn; gói đúng tên `resemble-perth` và mới hỗ trợ tới Python 3.11. Nhãn AI của dự án là nhãn nhìn thấy được do FFmpeg khắc lên hình. |
| So khớp hash WAV đầu ra trong test | Sinh giọng có ngẫu nhiên, seed gốc không tái lập được. |
| `git commit` | Brief §4 cấm khi chưa được yêu cầu. |

---

## 7. Rủi ro còn lại

1. **Độ giống dừng ở 8/10.** Thu lại với nguồn sạch hơn (v2: clipping 0 %, sàn
   nhiễu −71 dBFS) cho ra bản *tự nhiên hơn* nhưng **không giống hơn**. Giới hạn
   nằm ở chính mô hình với chất giọng này, không ở tham số hay chất lượng thu.
   Muốn vượt 8/10 có lẽ phải đổi hướng (fine-tune, hoặc mô hình khác), không
   phải chỉnh tiếp tham số.
2. **Chưa kiểm chứng cách đọc số.** File `giong-toi-B-so.wav` có "1,2 tỷ" và
   "0909123456" nhưng PO chưa chấm riêng mục này. Nếu TTS đọc sai chữ số, cách
   xử lý là viết thoại thành chữ còn chữ trên màn hình giữ chữ số — composer đã
   sẵn sàng. **Phải kiểm tra ở D04.**
3. **`resemble-perth` chưa hỗ trợ Python 3.12**, nên nếu sau này muốn đóng dấu
   ẩn trong audio thì phải chờ upstream hoặc hạ phiên bản Python.
4. **Model fp32 đã nằm trong cache (480 MB)** dù không dùng. Xoá được bằng cách
   dọn cache Hugging Face nếu cần chỗ.
5. Các rủi ro D00 về **ổ C**, **không có ổ D**, **Docker daemon tắt** giữ
   nguyên, sẽ xử lý ở D03.
6. **Chưa có commit nào.** Toàn bộ đang ở working tree.

---

## 8. Đề xuất cho D03

Theo brief §D03, và **chỉ sau khi PO duyệt D02**:

1. Bật Docker Desktop, xác nhận `docker run --gpus` hoạt động — **trước** khi pull.
2. Quyết định chuyển Docker data root sang F/H (ổ C chỉ còn ~94 GB, Duix cần ~70 GB).
3. Viết compose override cục bộ vì máy **không có ổ D** (upstream hardcode
   `d:/duix_avatar_data/...`).
4. Đọc và lưu nguyên văn giấy phép Duix.
5. Ghim image digest, ghi footprint và cách gỡ.
6. **Dừng, hướng dẫn PO quay video nguồn**, rồi mới tạo video thử bằng video
   thật + giọng thật — theo đúng điều kiện nghiệm thu PO đã bổ sung.

Khi thiết kế avatar ở D03, đọc trước [BL-001 trong BACKLOG.md](docs/BACKLOG.md)
để không khoá cứng mô hình dữ liệu, tránh phải làm lại khi mở tính năng Tủ đồ AI.

---

## 9. Kết luận

D02 hoàn thành đủ 6 mục của brief §D02. VieNeu-TTS chạy thật trên CPU/ONNX,
không chạm GPU, nhân bản được giọng chủ máy, và PO nghiệm thu **8/10** với
`giong-toi-A-mo-dau.wav`.

Cấu hình tạo ra file đó đã được ghim vào adapter bằng 8 hằng số `GOLDEN_*` và
khoá lại bằng **30 test chống hồi quy**. Golden reference được bảo vệ ở hai lớp:
hàng rào trong mã (`assert_writable`) và thuộc tính read-only trên đĩa.

**Chờ duyệt: trả lời đúng câu `D02 = APPROVED` để bắt đầu Gate D03.**
