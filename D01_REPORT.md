# D01_REPORT — Repo điều phối và mock pipeline (Gate D01)

- Ngày: 2026-08-04
- Máy: Windows 11 Pro, i7-14700F, 31,8 GB RAM, RTX 4070 SUPER 12 GB
- Phạm vi: **chỉ D01**. Không tải model, không pull Docker image, không chạy
  GPU, không gọi API mất tiền, không commit/push.

---

## 1. Kết quả chính

Repo điều phối đã dựng xong và **chạy được toàn bộ đường ống bằng mock**, từ một
câu tiếng Việt tới file MP4 giả + phụ đề + manifest chi phí.

| Yêu cầu brief §D01 | Trạng thái | Nơi kiểm chứng |
|---|---|---|
| 1. Repo nhẹ, instruction files, schemas, adapter interface | ✅ | `README.md`, `CLAUDE.md`, `AGENTS.md`, `schemas/`, `src/ai_video_agent/providers/` |
| 2. Chọn Python/TypeScript theo bằng chứng + ADR | ✅ **Python** | [docs/adr/0001-language-choice-python.md](docs/adr/0001-language-choice-python.md) |
| 3. CLI `doctor`/`plan`/`estimate`/`render --dry-run`/`status` | ✅ (+ `approve`, `validate`) | `src/ai_video_agent/cli/main.py` |
| 4. State machine `DRAFT→PLANNED→APPROVED→RENDERING→COMPOSED→DONE/FAILED` | ✅ | `src/ai_video_agent/domain/state.py`, 13 test |
| 5. `render` mặc định dry-run; chạy thật cần cờ + APPROVED | ✅ | `orchestrator/costguard.py`, 10 test |
| 6. Mock VieNeu / Duix / ViMax / API video, chạy hết đường mà không tải model | ✅ | `providers/*/mock.py`, 18 test |
| 7. Unit test, typecheck/lint, `git diff --check`, quét secret | ✅ | mục 2 dưới đây |
| 8. Báo cáo file thay đổi rồi dừng | ✅ | file này |

### Ba lớp chặn chi phí (đã kiểm thử, không phải lời hứa)

1. `render` **mặc định dry-run** — phải có `--execute`.
2. Provider **mặc định mock** — phải có `--provider-mode real`.
3. Provider tính tiền còn cần `--allow-paid` **và** project `APPROVED` **và**
   ước tính ≤ `budget.cap_usd` (mặc định **0 USD**).

Ngoài ra phê duyệt được **neo vào SHA-256 của storyboard**: sửa kịch bản sau khi
duyệt là phê duyệt tự hết hiệu lực và render thật bị chặn cho tới khi duyệt lại.

### Hàng rào gate được viết thành mã

`gate_is_open()` + hằng `GATE` trong từng adapter. Gọi tính năng của gate chưa
mở sẽ ném `GateNotReachedError` chứ không âm thầm chạy tiếp
([ADR-0003](docs/adr/0003-gate-guard-in-code.md)):

| Adapter | Gate | Việc bị chặn ở D01 |
|---|---|---|
| `providers/vieneu/adapter.py` | D02 | tải model, sinh giọng |
| `providers/duix/adapter.py` | D03 | pull image ~70 GB, chạy GPU |
| `composer/runner.py::FfmpegComposer` | D04 | chạy FFmpeg thật |
| `providers/vimax/adapter.py` | D05 | gọi API trả phí |
| `providers/video_api/adapter.py` | D05 | gọi API trả phí |

`quote()` **không** bị chặn — nhờ vậy `estimate` và `--dry-run` cho ra con số của
cấu hình thật mà không chạm vào provider nào.

---

## 2. Bằng chứng kiểm tra

| Lệnh | Kết quả | Trạng thái |
|---|---|---|
| `uv run pytest` | **180 passed** in 3.36s | PASS |
| `uv run ruff check .` | `All checks passed!` (13 nhóm luật, gồm `S` bandit và `BLE`) | PASS |
| `uv run ruff format --check .` | `73 files already formatted` | PASS |
| `uv run mypy` | `Success: no issues found in 43 source files` (strict) | PASS |
| `git diff --check` | không có lỗi khoảng trắng, exit 0 | PASS |
| Quét secret (`tests/test_no_secrets.py`) | 9 test, không phát hiện gì | PASS |
| `uv run aiva doctor` | 15 PASS / 4 WARN / 0 FAIL | PASS |

### Phân bố test (180)

| File | Số test | Bảo vệ điều gì |
|---|---|---|
| `test_composer.py` | 22 | mốc phụ đề, escape đường dẫn Windows, cờ xuất bản H.264/AAC |
| `test_providers.py` | 18 | hàng rào gate, WAV mock hợp lệ, idempotency, không đọc API key |
| `test_pipeline.py` | 17 | dry-run không sinh file, cache theo shot, nhãn AI |
| `test_textutil.py` | 17 | tách câu có viết tắt, trích số điện thoại/giá/pháp lý |
| `test_cli.py` | 16 | toàn bộ đường đi CLI, chặn render khi chưa duyệt |
| `test_schemas.py` | 15 | model ↔ JSON Schema, chặn đường dẫn tuyệt đối |
| `test_state_machine.py` | 13 | 7 trạng thái, chặn nhảy cóc |
| `test_planner.py` | 13 | storyboard hợp lệ, tất định, chữ chính xác |
| `test_examples.py` | 11 | `projects-example/` không lỗi thời |
| `test_repository.py` | 11 | ghi/đọc, dữ liệu nằm ngoài repo |
| `test_costguard.py` | 10 | 6 luật chặn chi phí và consent |
| `test_no_secrets.py` | 9 | không secret/media trong Git |
| `test_estimator.py` | 8 | làm tròn lên, cảnh báo vượt trần |

### `aiva doctor` trên máy này

| Mục | Trạng thái | Chi tiết |
|---|---|---|
| ai-video-agent | PASS | v0.1.0 — gate đang mở: D01 |
| python | PASS | 3.12.13 (do uv quản lý) |
| schemas | PASS | đủ 4 file |
| git | PASS | 2.54.0.windows.1 |
| uv | PASS | 0.11.32 |
| docker | PASS | 29.6.1 |
| gpu | PASS | RTX 4070 SUPER, 12282 MiB |
| đĩa repo (F:) | PASS | 382,0 GB trống |
| cổng local | PASS | 8383, 18180, 10095, 4173 đều trống |
| `.gitignore` | PASS | `.env` đã bị loại khỏi Git |
| chế độ provider | PASS | `mock`, `allow_paid_apis=False` |
| secret | INFO | không có biến secret nào trong môi trường |
| **ffmpeg / ffprobe** | **WARN** | chưa cài — chỉ cần từ D04 |
| **docker daemon** | **WARN** | không kết nối được — chỉ cần từ D03 |
| **runtime dir** | **WARN** | chưa tồn tại, sẽ tạo khi chạy `aiva plan` |

Bốn WARN đều đúng kế hoạch, không có mục nào FAIL.

### Chạy thử end-to-end (đã thực hiện thật)

Chạy trên thư mục runtime tạm để không tạo dữ liệu ngoài phạm vi:

```powershell
$env:AIVA_RUNTIME_DIR = "<scratch>\demo-runtime"
uv run aiva plan --brief "Bán lô đất thổ cư mặt tiền đường nhựa 8m tại TP. Biên Hoà, Đồng Nai. Diện tích 100m2, sổ hồng riêng, công chứng trong ngày. Giá chỉ 1,2 tỷ, thương lượng cho khách thiện chí. Liên hệ 0909123456 để xem đất ngay hôm nay." --id demo-vn --duration 40
```

**Kết quả:** 4 shot / 40,0 s, 3 scene (hook · body · CTA), và planner trích đúng
chữ phải hiển thị nguyên văn:

| Shot | Chữ chính xác | Loại |
|---|---|---|
| shot-001 | `thổ cư` | legal |
| shot-002 | `sổ hồng riêng`, `công chứng` | legal |
| shot-003 | `1,2 tỷ` | price |
| shot-004 | `0909123456`, `Liên hệ ngay để được tư vấn` | phone, cta |

Các bước tiếp theo và kết quả quan sát được:

| Lệnh | Kết quả |
|---|---|
| `aiva validate demo-vn` | `project.json` và `storyboard.json` khớp schema |
| `aiva estimate demo-vn --detail` | tổng **0,0000 USD**, 9 dòng, mỗi dòng kèm giả định |
| `aiva render demo-vn --execute` **khi chưa duyệt** | **bị chặn**, exit 1: *"Project đang ở trạng thái PLANNED; chỉ APPROVED, COMPOSED, DONE mới được render"* |
| `aiva approve demo-vn --by "..."` | → APPROVED, neo `sha256 1bb2a7b0df03994f…` |
| `aiva render demo-vn` (mặc định) | DRY-RUN, 10 bản ghi `planned`, **không sinh artifact nào** |
| `aiva render demo-vn --execute` | 10 bản ghi `succeeded`, xuất `demo-vn-<run>.mock.mp4` |
| `aiva render demo-vn --execute --only-shot shot-002` | shot-002 `succeeded`, **6 bản ghi còn lại `reused`** |
| `aiva status demo-vn` | `DONE`, lịch sử `PLANNED → APPROVED → RENDERING → COMPOSED → DONE → RENDERING → COMPOSED → DONE` |

**Phụ đề sinh ra** (`subtitles.srt`, UTF-8, ngắt 2 dòng, mốc thời gian liên tục
lấy từ thời lượng WAV thật):

```srt
1
00:00:00,000 --> 00:00:11,960
Bán lô đất thổ cư mặt tiền đường nhựa 8m
tại TP. Biên Hoà, Đồng Nai.

2
00:00:12,000 --> 00:00:22,290
Diện tích 100m2, sổ hồng riêng, công chứng
trong ngày.
```

**Lệnh FFmpeg được dựng** (ghi vào `render-manifest.json`, **chưa chạy**) — trích
phần cốt lõi:

```text
ffmpeg -hide_banner -nostdin -y -f concat -safe 0 -i <run>/concat.txt
  -filter_complex [0:v]scale=1080:1920:force_original_aspect_ratio=decrease,
    pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,setsar=1,
    subtitles='C\:/.../subtitles.srt':force_style='FontName=Arial\,FontSize=18\,...',
    drawtext=text='sổ hồng riêng':...:enable='between(t,12.000,22.330)',
    drawtext=text='công chứng':...:y=h-text_h-250:enable='between(t,12.000,22.330)',
    drawtext=text='1\,2 tỷ':...:enable='between(t,22.330,31.726)',
    drawtext=text='0909123456':...:enable='between(t,31.726,40.000)',
    drawtext=text='Nội dung có sử dụng AI':...:y=60:fontsize=34[vout]
  -map [vout] -map 0:a?
  -c:v libx264 -profile:v high -preset medium -crf 20 -pix_fmt yuv420p
  -c:a aac -b:a 192k -ar 48000 -movflags +faststart -shortest <output>.mock.mp4
```

Bốn điểm đáng chú ý:

- Số điện thoại `0909123456` giữ **nguyên từng chữ số** và do FFmpeg vẽ, không
  giao cho model sinh video (brief §D04.2).
- Mốc thời gian `enable=` khớp chính xác biên shot; hai chữ cùng shot được xếp
  chồng (`y=…-180` và `y=…-250`) nên không đè nhau.
- Đường dẫn Windows được escape đúng cú pháp filtergraph (`C\:/Users/...`) và
  dấu phẩy trong `1\,2 tỷ` cũng vậy.
- Nhãn "Nội dung có sử dụng AI" hiện suốt video (brief §4).

---

## 3. File đã tạo

**86 file** sẽ vào Git (`git ls-files --cached --others --exclude-standard`),
trong đó **84 file mới do D01 tạo ra**.

| Nhóm | Số file | Nội dung |
|---|---|---|
| Cấu hình gốc | 6 | `pyproject.toml`, `uv.lock`, `.gitignore`, `.gitattributes`, `.codegraphignore`, `.env.example` |
| Instruction | 3 | `README.md`, `CLAUDE.md`, `AGENTS.md` |
| Tài liệu | 7 | `docs/ARCHITECTURE.md`, `INSTALL-WINDOWS.md`, `COST-SAFETY.md`, `UPSTREAM-AUDIT.md` + 3 ADR |
| Schemas | 4 | 4 JSON Schema draft 2020-12 (341 dòng) |
| Source | 43 | `src/ai_video_agent/**` (4 080 dòng Python) |
| Test | 14 | `tests/**` (1 612 dòng, 180 test) |
| Ví dụ | 6 | `assets-example/` (2), `projects-example/demo-bds-9x16/` (4) |
| Báo cáo | 1 | `D01_REPORT.md` (file này) |
| *Có sẵn từ trước, **không bị sửa*** | *2* | *`AI_VIDEO_AGENT_BUILD_BRIEF.md`, `D00_AUDIT.md`* |

Cấu trúc source:

```text
src/ai_video_agent/
├── __init__.py          gate_is_open() — hàng rào gate
├── clock.py             thời gian/ID thay thế được trong test
├── config.py            đọc env; KHÔNG đọc giá trị secret
├── errors.py            13 lớp lỗi nghiệp vụ
├── jsonschemas.py       đối chiếu với schemas/
├── paths.py             định vị gốc repo
├── domain/              7 file — model + state machine, không I/O
├── orchestrator/        7 file — planner, estimator, costguard, pipeline, repository, textutil
├── providers/          16 file — base, pricing, registry + vieneu/duix/vimax/video_api
├── composer/            4 file — subtitles, ffmpeg (chỉ dựng lệnh), runner
└── cli/                 3 file — main, doctor
```

**Không sửa file nào của người dùng ngoài `F:\AI-VIDEO-AGENT`.**

---

## 4. Diff summary

Repo được `git init` mới (nhánh `main`, không remote). Toàn bộ 86 file đang là
**file mới chưa track**, chưa có commit nào — brief §4 cấm commit khi chưa được
yêu cầu.

```text
git status --short  →  86 mục, tất cả là file mới
git diff --check    →  sạch, exit 0
```

Ước lượng: **+8 000 dòng** (4 080 src + 1 612 test + 341 schema + ~2 000 tài liệu),
**0 dòng bị xoá**, **0 file bị sửa** trong số file có sẵn.

---

## 5. Dung lượng tải thêm và tài nguyên quan sát được

### Đã tải ở D01

| Hạng mục | Dung lượng | Vị trí |
|---|---|---|
| `uv` 0.11.32 (winget, user-scope) | ~35 MB | `%LOCALAPPDATA%\Microsoft\WinGet\Packages\` |
| CPython 3.12.13 (do uv quản lý) | **61,1 MB** | `%APPDATA%\uv\python\` |
| 29 gói Python vào `.venv` | **89,5 MB** | `F:\AI-VIDEO-AGENT\.venv\` |
| Mã nguồn + tài liệu do dự án tạo | 0,96 MB | `F:\AI-VIDEO-AGENT\` |
| **Tổng** | **≈ 186 MB** | |

Toàn bộ dưới ngưỡng 1 GB của brief §5. **Không** tải model, **không** pull Docker
image. Python hệ thống không bị đụng tới — uv dùng runtime riêng.

Gói đã cài: `pydantic 2.13.4`, `typer 0.27.1`, `jsonschema 4.26.0`, `rich 15.0.0`,
`pytest 9.1.1`, `ruff 0.16.1`, `mypy 2.3.0` + phụ thuộc.

### Tài nguyên quan sát được

| Chỉ số | Giá trị | So với D00 |
|---|---|---|
| VRAM | 2 736 / 12 282 MiB dùng bởi app desktop | ~như cũ (D00: 2,5 GB) |
| VRAM do dự án dùng | **0 MiB** | không chạy GPU |
| RAM trống | 9,1 / 31,8 GB | — |
| Ổ C trống | 96,1 GB | −0,9 GB (uv python + winget) |
| Ổ F trống | 382,0 GB | −0,1 GB (repo + venv) |
| Ổ E / H | 362,5 / 1 447,8 GB | không đổi |
| CPU cho test | 180 test trong **3,36 s** | không GPU |

---

## 6. Việc KHÔNG làm và lý do

| Không làm | Lý do |
|---|---|
| `git commit` / `git push` / tạo remote | Brief §4–5 cấm khi chưa được yêu cầu. Repo đã `git init` local, chưa có commit nào. |
| Cài FFmpeg | Chỉ cần từ D04. `doctor` đã báo WARN đúng chỗ. Giữ dấu chân hệ thống nhỏ nhất. |
| Bật Docker Desktop / WSL distro | Thuộc D03. D00 đã ghi nhận daemon đang tắt. |
| Tải model VieNeu, pull image Duix | Thuộc D02/D03, cần duyệt riêng (≥1 GB). |
| Clone ba repo upstream | Brief §3: giữ upstream tách biệt. Adapter chỉ cần API contract đã khảo sát ở D00. |
| Gọi bất kỳ API tính tiền nào | `AIVA_ALLOW_PAID_APIS=0`, adapter bị chặn bởi gate D05. |
| Tạo `F:\AI-VIDEO-AGENT-RUNTIME` | Demo chạy trên thư mục tạm để không tạo dữ liệu ngoài repo trước khi được duyệt. Thư mục thật sẽ tự tạo khi người dùng chạy `aiva plan` lần đầu. |
| Đọc/ghi secret | `config.py` chỉ kiểm tra *sự tồn tại* biến môi trường; có test chặn hồi quy. |
| Dùng LLM để lập kịch bản | D01 dùng `RuleBasedPlanner` offline, tất định. `Planner` là Protocol để cắm Claude Code vào khi vận hành thật. |
| Thực thi FFmpeg | `composer/ffmpeg.py` chỉ **dựng lệnh**; thực thi mở ở D04. |

### Điểm lệch so với brief, đã ghi rõ

1. **Cấu trúc thư mục** — brief §6 vẽ `src/domain/`; Python theo bố cục `src/`
   cần thư mục gốc cho package nên thành `src/ai_video_agent/domain/`. Ranh giới
   module giữ nguyên 1:1. `providers/video-api` → `providers/video_api` vì tên
   module Python không được có dấu gạch ngang.
   Lý do đầy đủ: [ADR-0001](docs/adr/0001-language-choice-python.md).
2. **Thêm 2 lệnh CLI ngoài danh sách tối thiểu** — `approve` (brief §9 đòi người
   dùng duyệt trước render, phải có lệnh để làm việc đó) và `validate` (kiểm tra
   file theo `schemas/`).
3. **Cài `uv` + CPython 3.12** — thuộc danh mục "cài phần mềm". Đây chính là hai
   lệnh đã ghi sẵn trong kế hoạch D01 ở `D00_AUDIT.md` §8 và đã được duyệt cùng
   D00; không có chúng thì không chạy được test, tức là không hoàn thành được
   §D01.7. Cả hai đều là user-scope, không đụng Python hệ thống, tổng ~96 MB.

---

## 7. Rủi ro còn lại

### Chuyển tiếp từ D00 (chưa thay đổi)

1. **Ổ C sát ngưỡng** — còn 96,1 GB, Docker data root vẫn ở C, Duix cần ~70–100 GB.
   → Phải quyết định chuyển Docker data sang F/H **trước** khi pull ở D03.
2. **Không có ổ D** — compose của Duix hardcode `d:/duix_avatar_data/…`.
   → D03 phải dùng compose override cục bộ trỏ sang F, không sửa upstream.
3. **Docker daemon đang tắt** — chưa xác nhận `docker run --gpus` hoạt động.
   → Health check GPU passthrough ở **đầu** D03, trước khi pull.
4. **License Duix là license cộng đồng riêng** — đã tóm tắt trong
   `docs/UPSTREAM-AUDIT.md` kèm cảnh báo phải đọc nguyên văn trước khi phát hành.
5. **VRAM 12 GB nhưng desktop đang chiếm 2,7 GB** — khi render Duix nên đóng bớt
   app GPU; VieNeu chạy CPU/ONNX để né xung đột.

### Phát sinh ở D01

6. **Giá của provider tính tiền là giả định chưa kiểm chứng** (0,40 và 0,50
   USD/giây). Đã ghi rõ ngay trong chuỗi `assumption` và đặt cố ý cao để thà chặn
   nhầm còn hơn cho qua nhầm. **Phải đối chiếu bảng giá thật trước khi mở D05.**
7. **Output của mock là file đánh dấu, không phải MP4 hợp lệ.** Chưa có FFmpeg
   nên không thể tạo video thật. Đã giảm nhẹ bằng ba lớp: đuôi `.mock.mp4`, cờ
   `is_placeholder=true` trong manifest, và chữ ký `AIVA-MOCK-VIDEO-v1` ở đầu file.
8. **Lệnh FFmpeg chưa từng được chạy thật.** Nó được kiểm thử ở mức chuỗi tham số
   (22 test), nhưng chỉ D04 mới xác nhận nó chạy được. Rủi ro thực tế nằm ở font
   tiếng Việt cho `drawtext` — máy có thể thiếu font hiển thị đủ dấu; `DrawTextSpec`
   đã có sẵn trường `font_file` để chỉ định.
9. **Planner theo luật, không phải LLM.** Nó chia câu và trích chữ chính xác tốt,
   nhưng không "hiểu" nội dung — không tự viết được hook hấp dẫn. Đúng phạm vi
   D01; vận hành thật sẽ do Claude Code lập kịch bản qua cùng interface `Planner`.
10. **Trích cụm pháp lý cần tiếng Việt có dấu.** Brief viết "so hong rieng" (không
    dấu) sẽ không khớp danh sách `LEGAL_PHRASES`. Số điện thoại và giá không bị
    ảnh hưởng. Đã xác nhận bằng thực nghiệm ở mục 2. Nếu người dùng thường gõ
    không dấu, đây là điểm cần mở rộng ở gate sau.
11. **Chưa có commit nào.** Mọi thứ đang ở working tree. Nếu thư mục bị xoá là mất
    hết. Có thể commit ngay khi được yêu cầu.

---

## 8. Đề xuất cho D02

Theo brief §D02, thứ tự ít rủi ro nhất:

1. `uv add vieneu` + tải model **ONNX/CPU** (~1–2 GB, cần duyệt vì ≥1 GB).
2. Đổi `CURRENT_GATE` thành `"D02"` để mở `VieNeuTtsProvider`.
3. Health check bằng **giọng dựng sẵn** và một câu tiếng Việt không nhạy cảm.
4. Kiểm tra WAV xuất ra: tồn tại, duration, sample rate, không clipping.
5. **Chỉ sau khi health check đạt** mới đề nghị người dùng cung cấp mẫu giọng, đưa
   vào thư mục runtime và khai báo `consent = granted` trong `asset-manifest.json`.

Điều D02 **không** làm: không đụng Docker, không pull image Duix, không chạy GPU.

---

## 9. Kết luận

D01 hoàn thành đầy đủ 8 mục của brief §D01. Đường ống chạy được từ đầu đến cuối
bằng mock; ba lớp chặn chi phí, hàng rào gate và luật đồng ý sử dụng tài sản đều
đã được viết thành mã và có test bảo vệ. Không có blocker mới. Bốn WARN của
`doctor` (ffmpeg, ffprobe, docker daemon, runtime dir) đều đúng kế hoạch và sẽ
được xử lý ở đúng gate của chúng.

**Chờ duyệt: trả lời đúng câu `D01 = APPROVED` để bắt đầu Gate D02.**
