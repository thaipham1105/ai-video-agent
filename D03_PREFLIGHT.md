# D03_PREFLIGHT — Duix-Avatar đã cài và chạy được

- Ngày: 2026-08-05
- Trạng thái: **preflight ĐẠT — dừng chờ duyệt bước sinh video thử**
- Chưa tạo video nào. Chưa đụng `video_cua_toi.mp4`.

---

## 1. Kiểm tra trước khi tải

| Mục | Kết quả |
|---|---|
| Ổ C trống | 93,18 GB |
| `docker_data.vhdx` | 18,86 GB (trên ổ C) |
| Git: nhánh / remote / commit | `main` / không có / **chưa có commit nào** |
| Git: số file, `diff --check` | 96 file, exit 0 |
| `video_cua_toi.mp4` | 84 MB, sửa lần cuối 2026-08-04 21:05:58, sha256 `71CF0BAA2F4506F9…` |
| Golden voice | read-only, sha256 khớp `311471E7…6253985C` |
| Thư mục `giu-lai` | đủ 7 WAV |

---

## 2. Quyết định phạm vi tải

Đo bằng `docker manifest inspect`, **không pull**:

| Image | Nén | MVP cần? |
|---|---|---|
| `guiji2025/duix.avatar` (gen-video) | **4,66 GB** | ✅ |
| `guiji2025/fish-speech-ziming` (TTS) | 19,08 GB | ❌ VieNeu đã lo từ D02 |
| `guiji2025/fun-asr` (ASR) | 14,18 GB | ❌ MVP không dùng |

Con số "~70 GB" trong tài liệu upstream là dung lượng **đã giải nén của cả ba**.
PO chọn phương án 1: **chỉ gen-video**.

Hệ quả quan trọng: **không cần chuyển Docker data root** sang F/H. Đây là rủi ro
số 1 của D00 §6, nay đã tự tiêu vì bản lite nhẹ hơn nhiều so với dự đoán.

---

## 3. Đã tải gì

```text
guiji2025/duix.avatar@sha256:1970424d219cbb6aebc7566f069041f057ccad618a395139dce002e1fb25d5ed
```

| Mục | Giá trị |
|---|---|
| Digest sau khi tải | **khớp** digest đã ghim trước khi tải |
| Kiến trúc | amd64/linux, 2 layer |
| Thời gian tải | 7 phút |
| Ổ C sau khi tải | **79,34 GB** (giảm 13,84 GB) |
| `docker_data.vhdx` | 18,86 → **32,46 GB** |

Image được ghim bằng **digest** chứ không phải tag `latest` (brief §D03.2), nên
upstream đẩy đè tag cũng không làm đổi thứ đang chạy trên máy.

---

## 4. Container health

| Kiểm tra | Kết quả | |
|---|---|---|
| Trạng thái | `Up`, cổng `0.0.0.0:8383->8383/tcp` | PASS |
| GPU trong container | RTX 4070 SUPER, 12 282 MiB | PASS |
| PyTorch thấy CUDA | `torch 2.2.2+cu118`, `cuda available: True` | PASS |
| Thiết bị nhận diện | `NVIDIA GeForce RTX 4070 SUPER` | PASS |
| Volume | `F:\` → `/code/data`, 381 GB trống, đã tạo `log/ result/ temp/` | PASS |
| Model nạp | `get_aud_feat1` 0,712 s · `av_transfer` 9,246 s | PASS |
| Flask | `TransDhServer服务启动`, chạy trên `0.0.0.0:8383` | PASS |
| API từ host | `GET /easy/query?code=...` → HTTP 200, `{"code":10004,"msg":"任务不存在"}` | PASS |

Endpoint mà D00 khảo sát trên giấy nay đã **xác nhận bằng thực tế**: server phản
hồi đúng khi hỏi một mã công việc không tồn tại.

### Ba vấn đề D00 nêu — đã xử lý xong

| Vấn đề D00 | Trạng thái |
|---|---|
| Docker daemon tắt, chưa rõ GPU passthrough | Daemon chạy; runtime `nvidia` đã đăng ký; `/dev/dxg`, `libcuda.so`, `nvidia-smi` đều có trong container |
| Máy không có ổ D, compose hardcode `d:/duix_avatar_data` | Compose override cục bộ trỏ sang `F:\AI-VIDEO-AGENT-RUNTIME\duix_avatar_data`. **Không sửa upstream.** |
| Ổ C sát ngưỡng, có thể phải chuyển Docker data root | Không cần nữa — bản lite chỉ thêm 13,84 GB, C còn 79,34 GB |

---

## 5. Tài nguyên đang chiếm (container để không)

| | |
|---|---|
| VRAM | 4 707 / 12 282 MiB dùng — **còn trống 7 291 MiB** |
| RAM container | 1,83 GiB |
| CPU container | 0,15 % |
| RAM toàn máy còn trống | **5,1 / 31,8 GB** |

> ⚠️ RAM còn trống 5,1 GB là hơi chật, đúng như rủi ro số 7 của D00. Trước khi
> render thật nên đóng bớt trình duyệt và ứng dụng nặng.

---

## 6. File đã tạo ở bước này

| File | Nội dung |
|---|---|
| `deploy/duix/docker-compose.yml` | Compose override tự viết: một service, digest ghim, volume trỏ F |
| `deploy/duix/README.md` | Lý do từng thay đổi, lệnh chạy, **cách gỡ sạch** |
| `D03_PREFLIGHT.md` | Báo cáo này |
| `README.md`, `CLAUDE.md` | Bảng gate: D02 APPROVED, D03 đang chạy |

Chưa sửa dòng mã Python nào. `CURRENT_GATE` vẫn là `"D02"` — adapter Duix thật
vẫn đang bị `GateNotReachedError` chặn, cố ý, cho tới khi PO duyệt bước sinh
video.

---

## 7. Việc CHƯA làm

| | |
|---|---|
| Sinh video thử | Chờ PO duyệt |
| Đụng `video_cua_toi.mp4` | Chưa. File còn nguyên, sha256 không đổi |
| Hiện thực `DuixAvatarProvider.generate()` | Chưa. Sẽ làm sau khi PO duyệt |
| Mở `CURRENT_GATE` sang `"D03"` | Chưa |
| Tải TTS/ASR của Duix | Không tải, và không định tải |

---

## 8. Bước kế tiếp cần PO duyệt

Theo điều kiện nghiệm thu PO đã bổ sung: *"Sau khi Duix hoạt động, hãy dừng và
hướng dẫn chính xác cách quay video nguồn của tôi. Chỉ hoàn thành D03 sau khi
tạo video thử bằng video thật và giọng thật của tôi."*

Duix đã hoạt động. Việc tiếp theo:

1. Kiểm tra kỹ thuật `video_cua_toi.mp4` (độ phân giải, fps, codec, thời lượng,
   khuôn mặt có ổn định không) — **chỉ đọc, không sửa file gốc**.
2. Nếu chưa đạt: hướng dẫn quay lại, nêu rõ thông số cần sửa.
3. Nếu đạt: đăng ký thành asset kèm `consent`, hiện thực adapter, rồi tạo **một**
   video thử ngắn bằng video thật + giọng golden.
4. Kiểm tra khẩu hình, thời lượng, đồng bộ audio/video.

**Không tự chạy lại nếu hình chưa đẹp** (brief §D03.5) — sẽ báo cáo và chờ PO.
