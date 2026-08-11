# Vận hành — dựng một video

Tài liệu dùng hằng ngày. Không giải thích kiến trúc; xem
[ARCHITECTURE.md](ARCHITECTURE.md) nếu cần.

Backend production là **Duix**, chạy local bằng Docker + GPU của máy.
Không tốn tiền API. MuseTalk là ứng viên nghiên cứu và **không chọn được** ở
đường này — xem [D04G_MUSETALK_BAKEOFF_DESIGN.md](../D04G_MUSETALK_BAKEOFF_DESIGN.md) §10.

---

## Cần chuẩn bị

| Thứ | Yêu cầu |
|---|---|
| **Video người đại diện** | MP4, người nói vào camera, **≥ 5 giây**. Đúng tỷ lệ khung hình của video định làm (9:16 thì quay dọc). Duix là mô hình face2face — **ảnh tĩnh không dùng được**. |
| **Mẫu giọng** | WAV/MP3/FLAC…, **8–30 giây**, đọc rõ, ít ồn, không clipping. |
| **Nội dung** | Một đoạn tiếng Việt mô tả điều muốn nói. |
| **Quyền sử dụng** | Chỉ dùng hình/giọng của chính mình hoặc đã có đồng ý rõ ràng. |

Kiểm máy trước lần đầu:

```bash
uv run aiva doctor
```

---

## Ba lệnh

### 1. Tạo project và xem còn thiếu gì

```bash
uv run aiva make --id video-dau-tien --brief "Bán lô đất thổ cư mặt tiền tại Biên Hoà, sổ hồng riêng, giá 1,2 tỷ. Liên hệ 0909123456."
```

Lệnh này lập kịch bản rồi **dừng lại và in đúng những lệnh còn thiếu**.

### 2. Đăng ký tài sản

```bash
uv run aiva avatar-add "D:\quay\toi-noi.mp4" --project video-dau-tien --owner "Tên bạn"
```

```bash
uv run aiva voice-add "D:\quay\giong-toi.wav" --project video-dau-tien --owner "Tên bạn"
```

Hai lệnh này chép file vào runtime, tính SHA-256, và ghi `consent = granted`.
File gốc không bị đụng tới.

### 3. Chạy thử rồi dựng thật

```bash
uv run aiva make --id video-dau-tien --brief "..." --by "Tên bạn" --mock
```

`--mock` dựng bằng file giả — không GPU, không Docker, xong trong vài giây. Dùng
để xem kịch bản chia cảnh có hợp lý không **trước khi** tốn thời gian GPU.

Ưng rồi thì bỏ `--mock`:

```bash
uv run aiva make --id video-dau-tien --brief "..." --by "Tên bạn"
```

`--by` là chữ ký của người duyệt kịch bản. Không có nó thì lệnh dừng sau bước lập
kế hoạch — **duyệt kịch bản là việc của người**, không phải thứ để một lệnh tự làm thay.

---

## Lệnh tự kiểm máy trước khi dựng

Ở lần dựng thật (không `--mock`), `make` hỏi bốn câu **trước khi** duyệt kịch bản:

```text
• Kiểm tra máy trước khi dựng…
  PASS ffprobe   ffprobe có trên PATH
  PASS docker    daemon 29.6.1
  PASS duix      http://127.0.0.1:8383/ trả HTTP 404 — server đang nghe
  WARN vram      card 12282 MiB (đủ), nhưng chỉ còn trống 7651 MiB / đỉnh đã đo 8500 MiB
```

Có `FAIL` thì lệnh dừng ngay, chưa đụng gì tới project — xử xong chạy lại đúng
lệnh cũ là đi tiếp. Vài điều dễ hiểu nhầm:

- **`duix` trả HTTP 404 là ĐÚNG.** `/` không phải route của Duix; 404 nghĩa là
  server đã lên và đang nghe.
- **`vram` so với *sức chứa của card*, không phải phần đang trống.** Con số Duix
  cần (8500 MiB) là đỉnh của **cả card** đo lúc render — đã gồm nền desktop và
  phần container giữ sẵn. Đem nó so với phần trống là trừ hai lần cùng một chỗ.
  Nên: card nhỏ hơn 8500 mới là `FAIL`; card đủ chỗ mà đang bị chiếm chỉ là
  `WARN` — đóng bớt app hoặc `restart` container là xong.
- **`vram` báo `INFO` không phải lỗi.** Máy không hỏi được `nvidia-smi` thì đó là
  *chưa xác minh được*, và lệnh vẫn chạy tiếp. Muốn chặn theo ngưỡng thì khai
  `AIVA_VRAM_BUDGET_MIB` — khai rồi thì con số đó thắng máy dò.
- **Lệnh này chỉ hỏi, không sửa.** Nó không tự bật container, không tự đóng ứng
  dụng đang chiếm GPU.

---

## Output nằm ở đâu

Mọi thứ nằm dưới `F:\AI-VIDEO-AGENT-RUNTIME\projects\<id>\` — **không bao giờ**
trong repo Git.

| Thứ | Đường dẫn |
|---|---|
| **Video hoàn chỉnh** | `outputs\<id>-<run>.mp4` |
| Nhật ký kiểm chứng | `renders\<run>\render-manifest.json` |
| Phụ đề | `renders\<run>\subtitles.srt` |
| Video avatar thô | `artifacts\<shot>\<hash>\avatar.mp4` |
| Giọng đã sinh | `artifacts\<shot>\<hash>\audio.wav` |
| Tài sản đã đăng ký | `assets\avatar\`, `assets\voice\` |

`render-manifest.json` ghi model nào, phiên bản nào, băm của từng file vào/ra,
chi phí, **và VRAM đỉnh đo được trong lúc chạy** (`records[].avatar_provenance
.resources.peak_vram_mib`). Đây là thứ để sau này nhìn một video bất kỳ và biết
nó từ đâu ra — và để biết ước lượng VRAM đang sát hay lệch thực tế.

`peak_vram_mib` là đỉnh của **cả card**, không riêng Duix: adapter đứng ngoài
container nên chỉ đo được tới đó. `null` nghĩa là *chưa đo được* (máy không có
`nvidia-smi`), khác hẳn 0.

> **Đừng so thẳng `peak_vram_mib` với `est_vram_mib` cạnh nó.** Hai số khác gốc:
> `peak_vram_mib` gồm cả nền desktop và mọi ứng dụng khác đang dùng GPU, còn
> `est_vram_mib` (8500) là phần *riêng Duix* cộng biên an toàn. Thấy 11958 > 8500
> **không** có nghĩa là vượt ngưỡng.

Xem lại các lần chạy:

```bash
uv run aiva status
```

---

## Lỗi thường gặp

| Thông báo | Nguyên nhân | Cách xử |
|---|---|---|
| `Còn thiếu tài sản` | Chưa chạy `avatar-add` / `voice-add` | Chạy đúng lệnh nó in ra, rồi lặp lại `make` |
| `chỉ có 1 khung hình — đây là ảnh tĩnh` | Đưa ảnh vào `avatar-add` | Quay một đoạn video ngắn người nói |
| `Không gọi được Duix tại http://127.0.0.1:8383` | Container chưa chạy | `docker compose -f deploy/duix/docker-compose.yml up -d` |
| `Thiếu tài sản avatar hợp lệ` | Chưa có `consent = granted` | Đăng ký lại bằng `avatar-add` với `--owner` |
| `Project đang ở trạng thái PLANNED` | Chưa duyệt kịch bản | Thêm `--by "Tên bạn"` |
| `duix không đủ tài nguyên` | VRAM đang bị chiếm | Đóng bớt trình duyệt/ứng dụng đồ hoạ rồi chạy lại |
| `WARN vram — chỉ còn trống N MiB` | Container Duix còn giữ model của lượt trước | Chạy tiếp được; gặp OOM thì `docker compose -f deploy/duix/docker-compose.yml restart` |
| `FAIL vram — không đủ chỗ` | Card nhỏ hơn đỉnh Duix cần | Đóng app không cứu được — cần card lớn hơn hoặc giảm độ phân giải |
| `FAIL docker — Docker daemon chưa chạy` | Chưa mở Docker Desktop | Mở Docker Desktop, đợi nó xanh rồi chạy lại |
| `FAIL ffprobe` | FFmpeg chưa cài, hoặc terminal mở trước khi cài | Mở lại terminal; còn thiếu thì cài FFmpeg |
| `MuseTalk là research candidate` | Project chốt `avatar: musetalk` | Sửa `providers.avatar` về `"duix"` trong `project.json` |
| `Phê duyệt đã hết hiệu lực` | Sửa kịch bản sau khi duyệt | Duyệt lại — phê duyệt neo vào hash storyboard |
| Chữ tiếng Việt lỗi trong `--help` | Codepage console | Đặt `PYTHONIOENCODING=utf-8` |

---

## Điều cần biết

- **Chạy lại chỉ dựng phần đã đổi.** Sửa thoại một cảnh thì chỉ cảnh đó chạy lại.
  Ép làm lại tất cả: thêm `--force` vào `aiva render`.
- **Số điện thoại, giá, câu pháp lý** do FFmpeg chèn, không giao cho model vẽ —
  sai một chữ số là sai nghiêm trọng.
- **Khẩu hình tiếng Việt có trần chất lượng đã biết.** Duix trích đặc trưng tiếng
  bằng bộ mã hoá huấn luyện trên tiếng Quan Thoại, nên các âm `/v/` và phụ âm cuối
  `-p` hay sai hình miệng. CLI cảnh báo điều này ở mỗi lần chạy. Đây là giới hạn
  của model, không phải lỗi cấu hình.
- **Không tốn tiền.** Toàn bộ đường production chạy local; `billable = false` và
  `actual_cost_usd = 0` trong mọi manifest.
