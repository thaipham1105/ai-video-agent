# AI VIDEO PRODUCTION AGENT — BUILD BRIEF

## 1. Mục tiêu

Xây một hệ thống chạy local trên Windows để chủ máy chỉ cần nhập yêu cầu tiếng Việt, hệ thống tự vận hành dây chuyền:

1. Claude Code lập kịch bản và kế hoạch cảnh.
2. VieNeu-TTS tạo lời đọc tiếng Việt bằng giọng đã được người dùng cho phép.
3. Duix-Avatar dùng video/hình ảnh thật đã được người dùng cho phép để tạo người đại diện nói.
4. FFmpeg ghép video, âm thanh, phụ đề, logo và hình minh họa.
5. ViMax là mô-đun mở rộng để tạo B-roll/phim nhiều cảnh; không được làm phụ thuộc bắt buộc của MVP.
6. Google Veo hoặc API video khác chỉ là provider tùy chọn và chỉ được gọi sau khi báo giá, có ngân sách trần và được người dùng duyệt rõ ràng.

Tên dự án: `AI-VIDEO-AGENT`.

## 2. Máy mục tiêu

- Windows 11 Pro.
- CPU Intel Core i7-14700F.
- RAM 32 GB DDR5.
- GPU NVIDIA RTX 4070 SUPER 12 GB.
- Thư mục dự án dự kiến: `F:\AI-VIDEO-AGENT`.

Không được mặc định rằng Docker, WSL2, CUDA, FFmpeg, Python, uv, Node hoặc dung lượng ổ đĩa đã đạt yêu cầu. Phải kiểm tra và báo bằng chứng.

## 3. Nguồn upstream phải khảo sát

- Duix-Avatar: `https://github.com/duixcom/Duix-Avatar`
- VieNeu-TTS: `https://github.com/pnnbao97/VieNeu-TTS`
- ViMax: `https://github.com/HKUDS/ViMax`

Không copy hàng loạt mã nguồn của ba repo vào repo điều phối. Không gộp ba codebase thành một monorepo khi chưa chứng minh sự cần thiết. Ưu tiên adapter/API cục bộ, giữ upstream tách biệt và có phiên bản được ghim.

## 4. Nguyên tắc bắt buộc

Sử dụng quy trình `architecture-code-control` cho toàn bộ công việc.

- Đọc `AGENTS.md`, `CLAUDE.md`, `README`, rules và tài liệu giấy phép trước khi sửa code.
- Chạy `git status` trước mọi thay đổi; không làm mất thay đổi có sẵn.
- Dùng CodeGraph cho luồng nhiều file nếu có và an toàn; nếu không có thì dùng `rg` và đọc code trực tiếp.
- Không đọc, in, ghi log hoặc index `.env`, API key, token, file cấu hình riêng, dữ liệu thật hay mẫu giọng thật.
- Không ghi key vào `CLAUDE.md`, source code, test, history lệnh hoặc `.claude/settings.local.json`.
- Chỉ tạo `.env.example` chứa tên biến giả; `.env` phải nằm trong `.gitignore`.
- Test phải mock provider; test tự động không được gọi API mất tiền.
- Không tự tạo lại cảnh vì lý do thẩm mỹ. Chỉ render lại shot được chỉ định.
- Không commit, push, deploy, mở port Internet, thay firewall, restart dịch vụ khác hoặc đụng dự án khác nếu chưa được yêu cầu.
- Không sử dụng hình ảnh hay giọng của người khác nếu chưa có sự đồng ý rõ ràng. Metadata của dự án phải ghi nhận nguồn và quyền sử dụng tài sản.
- Video AI công khai phải có tùy chọn gắn nhãn nội dung AI.

## 5. Quyền tự động và điểm phải dừng

Được tự làm mà không cần hỏi:

- Kiểm tra phiên bản công cụ, GPU, RAM, dung lượng đĩa và trạng thái Git.
- Đọc tài liệu/repo công khai và lập bản đồ kiến trúc.
- Tạo tài liệu kế hoạch, schema, interface, test mock và bộ khung source nhẹ trong repo mới.
- Chạy test không dùng GPU, không tải model và không gọi API thật.

Phải dừng để xin duyệt trước khi:

- Cài hoặc cập nhật WSL, Docker Desktop, CUDA, driver NVIDIA hay phần mềm hệ thống.
- Pull Docker image, tải model hoặc tải dữ liệu từ 1 GB trở lên.
- Clone repo vào vị trí ngoài `F:\AI-VIDEO-AGENT` hoặc thay đổi đường dẫn Docker data.
- Chạy model bằng GPU lâu, huấn luyện avatar, clone giọng thật hoặc render video thật.
- Gọi Gemini, Veo hay bất kỳ API tính tiền nào.
- Ghi/đọc khóa bí mật, commit, push, tạo GitHub remote hoặc deploy.

## 6. Kiến trúc mục tiêu

Repo điều phối chỉ nên chứa code do dự án sở hữu:

```text
AI-VIDEO-AGENT/
├── CLAUDE.md
├── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── INSTALL-WINDOWS.md
│   ├── COST-SAFETY.md
│   └── UPSTREAM-AUDIT.md
├── src/
│   ├── domain/
│   ├── orchestrator/
│   ├── providers/
│   │   ├── vieneu/
│   │   ├── duix/
│   │   ├── vimax/
│   │   └── video-api/
│   ├── composer/
│   └── cli/
├── schemas/
├── tests/
├── assets-example/
├── projects-example/
├── .env.example
└── .gitignore
```

Dữ liệu thật, model, Docker volumes, voice samples, avatar videos, cache, renders và outputs phải ở thư mục runtime riêng, bị Git ignore và không bị CodeGraph index.

Luồng MVP:

```text
Brief tiếng Việt
  -> storyboard JSON có schema
  -> duyệt kịch bản
  -> VieNeu tạo WAV
  -> Duix nhận WAV + avatar source
  -> video người nói
  -> FFmpeg chèn phụ đề/logo/B-roll
  -> MP4 + manifest + báo cáo chi phí
```

## 7. Hợp đồng dữ liệu tối thiểu

Mỗi project cần có:

- `project.json`: ID, mục tiêu, tỷ lệ khung hình, thời lượng, ngân sách trần, trạng thái duyệt.
- `storyboard.json`: danh sách scene/shot, thoại, hình minh họa, thời lượng, provider dự kiến.
- `asset-manifest.json`: đường dẫn tương đối, SHA-256, loại tài sản, chủ sở hữu, trạng thái đồng ý sử dụng.
- `render-manifest.json`: provider/model/version, seed nếu có, thời điểm, trạng thái, chi phí dự kiến/thực tế, file đầu vào/đầu ra.
- `subtitles.srt` hoặc `subtitles.ass`.

Không được lưu nội dung key hoặc sao chép mẫu giọng/video thật vào Git.

## 8. Các cổng thực hiện

### Gate D00 — Khảo sát máy và repo, không sửa hệ thống

1. Kiểm tra `git`, `claude`, `nvidia-smi`, driver/CUDA reported, `python`, `uv`, `node`, `npm`, `ffmpeg`, `docker`, `wsl` và PowerShell.
2. Kiểm tra dung lượng trống ổ C, D và F. Duix upstream cảnh báo cần dung lượng lớn; xác định Docker data hiện nằm ở đâu nhưng không tự di chuyển.
3. Kiểm tra xung đột cổng local dự kiến.
4. Đọc README, license, install docs và API entry points của ba upstream.
5. Xác nhận phương thức tích hợp khả thi:
   - VieNeu qua SDK hoặc local API.
   - Duix qua các local endpoints huấn luyện/synthesis.
   - ViMax qua CLI/module/provider, chỉ ở giai đoạn mở rộng.
6. Xuất `D00_AUDIT.md` gồm bảng PASS/WARN/BLOCKED, dung lượng tải ước tính, rủi ro và lệnh sẽ chạy ở Gate kế tiếp.
7. Dừng và chờ đúng câu `D00 = APPROVED`.

### Gate D01 — Dựng repo điều phối và mock pipeline

1. Khởi tạo repo code nhẹ, instruction files, schemas và adapters interface.
2. Chọn Python hay TypeScript dựa trên bằng chứng tích hợp, ghi ADR; không chọn theo sở thích.
3. Tạo CLI tối thiểu:
   - `doctor`
   - `plan`
   - `estimate`
   - `render --dry-run`
   - `status`
4. Xây state machine: `DRAFT -> PLANNED -> APPROVED -> RENDERING -> COMPOSED -> DONE/FAILED`.
5. `render` mặc định là dry-run. Muốn chạy provider thật phải có cờ xác nhận và project đã APPROVED.
6. Tạo mock VieNeu, mock Duix, mock ViMax/API video; test toàn bộ đường đi mà không tải model.
7. Chạy unit tests, typecheck/lint tương ứng, `git diff --check`, quét diff tìm secret.
8. Báo file thay đổi và dừng chờ `D01 = APPROVED`.

### Gate D02 — VieNeu-TTS thật

1. Cài VieNeu theo hướng ít rủi ro nhất đã được duyệt; ưu tiên thử CPU/ONNX trước để tránh xung đột GPU với Duix.
2. Chạy health check với giọng dựng sẵn và câu tiếng Việt không nhạy cảm.
3. Chỉ sau khi health check đạt mới đề nghị người dùng cung cấp mẫu giọng hợp lệ qua thư mục runtime riêng.
4. Không tự phát hoặc lưu lại mẫu giọng trong repo.
5. Xuất WAV và kiểm tra duration, sample rate, clipping, file tồn tại.
6. Dừng chờ `D02 = APPROVED`.

### Gate D03 — Duix-Avatar thật

1. Chỉ cài sau khi xác nhận đủ dung lượng và Docker GPU hoạt động.
2. Ghim version/image digest nếu khả thi; ghi đầy đủ footprint và rollback.
3. Gọi API local bằng adapter, không sửa sâu upstream trong lần đầu.
4. Tạo video thử ngắn bằng tài sản đã được người dùng cho phép.
5. Kiểm tra khẩu hình, duration, audio sync và output; không tự chạy lại nếu hình chưa đẹp.
6. Dừng chờ `D03 = APPROVED`.

### Gate D04 — Composer và video hoàn chỉnh

1. FFmpeg ghép avatar, B-roll có sẵn, logo, chữ Việt và phụ đề.
2. Chữ chính xác như số điện thoại, giá, pháp lý phải do composer chèn; không giao model video tự vẽ chữ.
3. Hỗ trợ 9:16 trước, sau đó 16:9.
4. Xuất MP4 H.264/AAC tương thích Facebook, TikTok, Zalo và manifest kiểm chứng.
5. Thêm khả năng sửa một scene/shot và tái ghép mà không render lại toàn bộ.
6. Dừng chờ `D04 = APPROVED`.

### Gate D05 — ViMax/API video tùy chọn

1. Chỉ bắt đầu sau khi D04 ổn định.
2. Dùng ViMax cho B-roll/phim nhiều cảnh, không thay Duix trong nhiệm vụ avatar nói.
3. Nếu dùng Google Video API, bắt buộc có estimate, hard cap, explicit approval, timeout, retry cap và idempotency.
4. Không cho ViMax tự động gọi API khi người dùng mới đang sửa storyboard.
5. Mỗi lần render phải ghi model, số giây, giá giả định, chi phí dự kiến và chi phí thực tế nếu provider trả về.

## 9. Tiêu chí MVP đạt

MVP chỉ được tuyên bố hoàn thành khi:

- Một lệnh tiếng Việt tạo được storyboard có schema hợp lệ.
- Người dùng có thể duyệt trước render.
- VieNeu tạo được WAV tiếng Việt.
- Duix tạo được một đoạn avatar nói từ WAV.
- FFmpeg xuất video dọc có logo và phụ đề đúng chữ.
- Có thể sửa riêng thoại/cảnh và chỉ chạy lại phần phụ thuộc.
- Không có secret hoặc dữ liệu thật trong Git/diff/log.
- Test mock đạt và có hướng dẫn Windows tái lập được.
- Không phát sinh chi phí API ngoài khoản đã duyệt.

## 10. Báo cáo bắt buộc sau mỗi Gate

- Kết quả chính.
- Bằng chứng/lệnh kiểm tra và trạng thái PASS/WARN/FAIL.
- File đã tạo hoặc sửa.
- Diff summary.
- Dung lượng tải thêm, VRAM/RAM/đĩa quan sát được.
- Việc không làm và lý do.
- Rủi ro còn lại.
- Câu duyệt chính xác cho Gate kế tiếp.

## 11. Lệnh đầu tiên dành cho Claude Code

Đọc toàn bộ file này. Thực hiện duy nhất Gate D00. Không cài đặt, không pull Docker image, không tải model, không đọc secret, không gọi API, không sửa hệ thống và chưa viết implementation. Kết thúc bằng báo cáo `D00_AUDIT.md`, nêu rõ phương án kiến trúc đề xuất và dừng chờ `D00 = APPROVED`.
