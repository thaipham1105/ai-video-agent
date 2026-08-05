# Duix-Avatar — triển khai cục bộ (Gate D03)

File `docker-compose.yml` cạnh đây **do dự án này tự viết**, không phải bản sao
của upstream (brief §3 cấm copy mã nguồn upstream vào repo). Nó chỉ tham chiếu
image đã publish và sửa đúng những gì máy này bắt buộc phải sửa.

## Vì sao không dùng compose của upstream

| Vấn đề của upstream | Cách xử lý ở đây |
|---|---|
| Hardcode volume `d:/duix_avatar_data/...` — **máy không có ổ D** | Trỏ sang `F:\AI-VIDEO-AGENT-RUNTIME\duix_avatar_data` (còn 380 GB) |
| Chạy cả 3 service, tải 37,9 GB nén | Chỉ chạy gen-video: **4,66 GB nén** |
| Dùng tag `latest` | Ghim **digest** (brief §D03.2) |

## Vì sao chỉ cần một service

| Service | Dung lượng nén | MVP có cần? |
|---|---|---|
| `guiji2025/duix.avatar` (gen-video) | **4,66 GB** | ✅ Đây là thứ tạo video người nói |
| `guiji2025/fish-speech-ziming` (TTS) | 19,08 GB | ❌ VieNeu-TTS đã lo từ D02 |
| `guiji2025/fun-asr` (ASR) | 14,18 GB | ❌ MVP không nhận dạng tiếng nói |

Con số "~70 GB" trong tài liệu upstream là dung lượng **đã giải nén của cả ba**.
Đo bằng `docker manifest inspect` cho thấy tải nén thực tế thấp hơn nhiều.

## Phiên bản được ghim

```text
guiji2025/duix.avatar@sha256:1970424d219cbb6aebc7566f069041f057ccad618a395139dce002e1fb25d5ed
```

Lấy lại digest bất cứ lúc nào:

```bash
docker manifest inspect --verbose guiji2025/duix.avatar:latest
```

## Lệnh

Khởi động:

```bash
docker compose -f deploy/duix/docker-compose.yml up -d
```

Xem log:

```bash
docker compose -f deploy/duix/docker-compose.yml logs -f
```

Dừng:

```bash
docker compose -f deploy/duix/docker-compose.yml down
```

## Gỡ sạch (rollback)

Brief §D03.2 đòi ghi rõ cách gỡ. Ba bước, theo thứ tự:

```bash
docker compose -f deploy/duix/docker-compose.yml down -v
```

```bash
docker rmi guiji2025/duix.avatar@sha256:1970424d219cbb6aebc7566f069041f057ccad618a395139dce002e1fb25d5ed
```

Rồi xoá thư mục dữ liệu `F:\AI-VIDEO-AGENT-RUNTIME\duix_avatar_data` nếu không
còn cần. Thư mục này chứa **tài sản thật của người dùng** (video nguồn khuôn
mặt), nên xoá là mất — cân nhắc sao lưu trước.

Muốn thu hồi luôn phần đĩa mà Docker đã chiếm:

```bash
docker system prune -a --volumes
```

> ⚠️ Lệnh trên xoá **mọi** image và volume không dùng của toàn máy, không riêng
> Duix. Trên máy này đang có sẵn `mysql:8.4` và `postgres:16-alpine` của việc
> khác — chúng cũng sẽ bị xoá. Chỉ chạy khi chắc chắn.

## Môi trường đã kiểm chứng trước khi cài

| Mục | Kết quả |
|---|---|
| Docker | 29.6.1, daemon đang chạy |
| Runtime `nvidia` | đã đăng ký (`nvidia-container-runtime`) |
| `/dev/dxg` trong container | có |
| `libcuda.so`, `nvidia-smi` trong container | có |
| GPU | RTX 4070 SUPER, 12 282 MiB |
| Ổ C (Docker data) | 93,2 GB trống, `docker_data.vhdx` 18,86 GB |
| Ổ F (dữ liệu Duix) | 380,7 GB trống |

Vì bản lite chỉ thêm ~10–12 GB đã giải nén vào ổ C, **không cần chuyển Docker
data root** — khác với lo ngại nêu ở D00 §6.
