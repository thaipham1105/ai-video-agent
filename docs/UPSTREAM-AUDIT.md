# Khảo sát upstream

Nguồn: khảo sát Gate D00 (xem [D00_AUDIT.md](../D00_AUDIT.md)) trên tài liệu
công khai của ba dự án. **Chưa clone repo nào, chưa tải model nào.**

Nguyên tắc brief §3: không copy hàng loạt mã nguồn của ba repo vào đây, không
gộp thành monorepo. Giữ upstream tách biệt, tích hợp qua adapter, ghim phiên bản.

---

## 1. Duix-Avatar

- Nguồn: `https://github.com/duixcom/Duix-Avatar`
- Vai trò: sinh video người đại diện nói (lip-sync) từ WAV + tài sản avatar.
- Gate mở: **D03**

### Giấy phép

Giấy phép **cộng đồng riêng**, không phải giấy phép OSI chuẩn. Theo mô tả công
khai: cho dùng thương mại miễn phí với tổ chức dưới 100.000 người dùng hoặc dưới
10 triệu USD doanh thu/năm.

> ⚠️ Phải đọc nguyên văn giấy phép và lưu bản sao vào thư mục runtime **trước
> khi phát hành sản phẩm ra công chúng**. Ngưỡng nêu trên là tóm tắt, không phải
> nguyên văn điều khoản.

### Cài đặt (chưa thực hiện)

- Docker Compose, ba service: `guiji2025/fish-speech-ziming`,
  `guiji2025/fun-asr`, `guiji2025/duix.avatar`.
- Tổng tải ước tính **~70 GB**, khuyến nghị ~100 GB trống.
- Có biến thể `docker-compose-lite.yml` (một service) và `docker-compose-5090.yml`.

### API local

| Việc | Điểm cuối |
|---|---|
| Huấn luyện | `POST /train` |
| TTS của Duix | `POST http://127.0.0.1:18180/v1/invoke` |
| Sinh video | `POST http://127.0.0.1:8383/easy/submit` |
| Hỏi tiến độ | `GET http://127.0.0.1:8383/easy/query?code={taskCode}` |

### Vấn đề đã biết trên máy này

1. **Không có ổ D.** `deploy/docker-compose.yml` của upstream hardcode volume
   `d:/duix_avatar_data/voice/data` và `d:/duix_avatar_data/face2face`. Máy chỉ
   có C, E, F, H.
   → D03 phải dùng **file compose override cục bộ** trỏ sang
   `F:\AI-VIDEO-AGENT-RUNTIME\duix_avatar_data`, **không sửa upstream**.
2. **Docker data đang nằm trên ổ C** (`docker_data.vhdx`, hiện 18,68 GB) trong
   khi C chỉ còn 97 GB. Pull 70 GB vào đó là gần cạn ổ.
   → Cần duyệt riêng việc chuyển Docker data root sang F hoặc H trước khi pull.
3. **Docker daemon đang tắt** — chưa xác nhận được `docker run --gpus` hoạt
   động. Phải health check GPU passthrough ở **đầu** D03, trước khi pull.

### Cách tích hợp đã chọn

HTTP adapter tới `127.0.0.1:8383` (`src/ai_video_agent/providers/duix/adapter.py`).
Không sửa mã upstream. MVP chỉ cần service gen-video vì TTS đã do VieNeu đảm
nhiệm → cân nhắc bản compose-lite để giảm dung lượng tải.

---

## 2. VieNeu-TTS

- Nguồn: `https://github.com/pnnbao97/VieNeu-TTS`
- Vai trò: sinh giọng đọc tiếng Việt.
- Gate mở: **D02**

### Giấy phép

**Apache 2.0** — cho phép dùng thương mại, chỉ cần giữ thông báo bản quyền. Không
có rủi ro pháp lý cho MVP.

### Cài đặt (chưa thực hiện)

- `pip install vieneu` (hoặc qua `uv`).
- Model tải từ Hugging Face; bản ONNX nhẹ ước tính **< 2 GB**.
- Hỗ trợ Windows chính thức.

### SDK

```python
from vieneu import Vieneu

audio = vieneu.infer(text, voice=...)  # giọng dựng sẵn — chỉ cần ONNX
audio = vieneu.infer(text, ref_audio=path)  # nhân bản giọng — cần engine PyTorch
```

Bản v3 Turbo chạy **ONNX int8 trên CPU** ở 48 kHz.

### Cách tích hợp đã chọn

SDK Python **in-process**, mặc định CPU/ONNX
(`src/ai_video_agent/providers/vieneu/adapter.py`). Chạy CPU để không tranh GPU
với Duix — đúng chiến lược brief §D02.1.

Đây cũng là bằng chứng mạnh nhất dẫn tới việc chọn Python
(xem [ADR-0001](adr/0001-language-choice-python.md)).

### Lưu ý về mẫu giọng

Nhân bản giọng chỉ cần mẫu 3–8 giây, nên rủi ro lạm dụng là có thật. Adapter từ
chối chạy nếu `ref_audio` không tồn tại, và cost guard chặn nếu tài sản chưa có
`consent = granted`. Mẫu giọng **không bao giờ** được lưu trong repo (brief §D02.4).

---

## 3. ViMax

- Nguồn: `https://github.com/HKUDS/ViMax`
- Vai trò: sinh B-roll / phim nhiều cảnh (Idea2Video / Script2Video / Novel2Video).
- Gate mở: **D05** — mô-đun mở rộng, **không** phải phụ thuộc của MVP.

### Giấy phép

**MIT** — thoáng nhất trong ba upstream.

### Cài đặt (chưa thực hiện)

- `git clone` + `uv sync`; chạy qua script Python hoặc `vimax tui`.
- Web UI Node tại `127.0.0.1:4173`.
- Hỗ trợ Windows. Ước tính ~1 GB, không có model chạy local.

### Vì sao nằm ngoài MVP

ViMax **bắt buộc API trả phí** ở cả ba lớp: LLM, sinh ảnh, sinh video
(Veo/Seedance). Đúng định vị brief §1.5 và §D05: mô-đun mở rộng, mặc định tắt,
bắt buộc estimate + hard cap + phê duyệt rõ ràng.

Brief §D05.2 còn quy định: ViMax **không thay Duix** ở nhiệm vụ avatar nói.

---

## Tổng hợp

| | Duix-Avatar | VieNeu-TTS | ViMax |
|---|---|---|---|
| Giấy phép | cộng đồng riêng ⚠️ | Apache 2.0 ✅ | MIT ✅ |
| Tải thêm | ~70 GB | ~1–2 GB | ~1 GB |
| Cần GPU | có | không (CPU/ONNX) | không (dùng API) |
| Tốn tiền API | không | không | **có** |
| Cách tích hợp | HTTP local | SDK Python | CLI/module |
| Trong MVP | có | có | không |
| Gate | D03 | D02 | D05 |

## Việc phải làm trước khi mở từng gate

**Trước D02 (VieNeu):**
- [ ] Xác nhận dung lượng model thực tế sau khi tải.
- [ ] Health check bằng giọng dựng sẵn + câu tiếng Việt không nhạy cảm.
- [ ] Chỉ xin mẫu giọng của người dùng **sau khi** health check đạt.

**Trước D03 (Duix):**
- [ ] Đọc và lưu nguyên văn giấy phép.
- [ ] Bật Docker Desktop, xác nhận `docker run --gpus` hoạt động.
- [ ] Quyết định chuyển Docker data root sang F/H (cần duyệt riêng).
- [ ] Viết compose override cục bộ cho volume path (vì không có ổ D).
- [ ] Ghim image digest, ghi lại footprint và cách gỡ.

**Trước D05 (ViMax / Video API):**
- [ ] Đối chiếu bảng giá thật, thay số giả định trong `providers/pricing.py`.
- [ ] Đặt `budget.cap_usd` và `AIVA_VIDEO_API_MAX_USD_PER_RUN` khác 0.
- [ ] Xác nhận D04 đã ổn định (brief §D05.1).
