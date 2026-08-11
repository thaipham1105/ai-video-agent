# D06 — Nghiệm thu giao diện local và render dài

Ngày chạy: **2026-08-11**. Máy: RTX 4070 SUPER 12.282 MiB, Docker 29.6.1,
Duix `sha256:1970424d…`. Mọi lượt dựng đi **trọn qua giao diện web** tại
`http://127.0.0.1:8765/`, không dùng dòng lệnh.

---

## 1. Kết quả

| | 30 giây | 60 giây |
|---|---|---|
| Project | `nghiem-thu-30s` | `nghiem-thu-60s` |
| `run_id` | **`929c4eef5b47`** | **`1a08c5465b52`** |
| Trạng thái | `succeeded` | `succeeded` |
| Số shot | 6 | **12** |
| Thời lượng ra | **36,43 s** | **70,17 s** |
| Tổng thời gian dựng | 175 s | 327 s |
| Giây máy / giây video | **4,80** | **4,66** |
| Lệch A/V | 0,017 s | **0,001 s** |
| Chi phí | 0,00 USD | 0,00 USD |
| Retry / OOM | 0 / 0 | 0 / 0 |
| `report.html` | 15.764 B | 25.527 B |

Ngưỡng vận hành §6.3 đòi ≤ 30 giây máy cho mỗi giây video và lệch A/V ≤ 0,02 s.
Cả hai lượt đều đạt với biên rất rộng.

## 2. VRAM — câu hỏi chính của batch này

Rủi ro cần loại trừ: VRAM tích luỹ qua nhiều shot rồi OOM giữa chừng. Đo bằng
sampler trong tiến trình (nhịp 1 s), ghi vào manifest từng shot.

Lượt 60 giây, 12 shot liên tiếp:

| shot | 001 | 002 | 003 | 004 | 005 | 006 | 007 | 008 | 009 | 010 | 011 | 012 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| đỉnh (MiB) | 8822 | 8255 | 8714 | 8735 | 8808 | 8521 | 8806 | 8794 | 8856 | 8846 | 8937 | 8863 |

Biên độ **682 MiB** quanh ~8.700, **không có xu hướng tăng** theo số shot. Duix
nhả bộ nhớ giữa các job. Kết luận: độ dài video **không** bị chặn bởi VRAM tích
luỹ trên máy này.

Con số này là đỉnh của **cả card** (gồm nền desktop), không riêng Duix — đừng so
thẳng với `est_vram_mib = 8500`.

## 3. Hai lỗi tìm ra và đã sửa

### 3.1 Giao diện báo "thành công" cho một lượt render thất bại

Lượt `09fb9c1e14d3`: TTS hỏng (`No module named 'torch'`), manifest ghi
`failed`, nhưng job của UI vẫn hiện `succeeded`. Nguyên nhân: `JobRunner` coi
"hàm chạy xong" là "việc đã xong" và bỏ qua trường `ok` trong kết quả.

Người dùng sẽ đi tìm một file MP4 không tồn tại. Giao diện nói dối về kết quả là
lỗi nặng hơn cả lỗi render. Đã sửa: `ok=False` ⇒ trạng thái `failed`.

### 3.2 `make` âm thầm bỏ qua nội dung vừa sửa

Sửa brief rồi chạy lại **cùng project ID**: `make` in "đã có — dùng lại kịch bản
hiện tại", dựng lại kịch bản **cũ**, và báo thành công. Bằng chứng: lượt
`741fff8e84db` — brief đổi hẳn 12 câu, video ra vẫn là 6 cảnh của bản trước.

Hành vi dùng-lại vốn là có chủ đích (để "bổ sung tài sản rồi chạy tiếp" không
phải dựng lại từ đầu), nhưng nó không phân biệt được *chạy lại cùng yêu cầu* với
*đổi yêu cầu*. Đã sửa: so `brief`/`duration`/`aspect`/`fps` với bản đã lưu; khác
thì lập lại kịch bản, giống thì giữ nguyên đường resume.

## 4. Điều đã biết, **chưa** sửa

**`--duration` là mục tiêu, không phải cam kết.** Lượt đầu đặt `--duration 30`
cho 6 câu ra video **17,6 s**: planner ước lượng ~5 s/câu còn VieNeu đọc thật
~2,9 s/câu. Muốn 30 giây thì cần lượng chữ gấp đôi ước lượng của planner.

Không sửa trong batch này vì đây là *sai số ước lượng*, không phải lỗi làm hỏng
sản phẩm: phụ đề và mốc thời gian đều bám theo thời lượng TTS thật, nên video ra
vẫn đúng. Sửa nó là đụng `planner.py` — vùng đã nghiệm thu. Cách dùng thực tế:
viết đủ chữ rồi xem thời lượng thật ở `report.html`.

Quy đổi đo được, dùng để ước lượng khi viết brief:

| Muốn video | Cần khoảng |
|---|---|
| 30 giây | 12 câu |
| 60 giây | 24 câu |
| 90 giây | 36 câu |

## 5. Điều chưa được chứng minh

* **Chất lượng khẩu hình chưa được chấm ở độ dài này.** Hai lượt trên nghiệm thu
  *vận hành* (chạy xong, đúng thời lượng, không OOM, có đủ hồ sơ), không phải
  *thẩm mỹ*. Trần chất lượng tiếng Việt của Duix vẫn như bake-off D04-G §10 đã đo.
* **Chưa thử video dài hơn 70 giây.** Không có dấu hiệu nào cho thấy sẽ hỏng —
  VRAM phẳng và thời gian tuyến tính theo số shot — nhưng đó là suy luận, không
  phải phép đo.
* **`report.html` chưa mở bằng double-click.** Nội dung đã kiểm bằng test; chưa
  xác nhận trình duyệt có phát video qua `file://` không. Trang luôn kèm đường
  dẫn dự phòng đúng vì lý do đó.
* **Chưa ai bấm shortcut Desktop thật.** Lõi Python của launcher đã chạy thật
  (bật container từ nguội, chờ, mở UI sau 23 s); phần `.ps1` và việc tạo shortcut
  thì chưa.
