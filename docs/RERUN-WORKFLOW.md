# Chạy lại toàn bộ — một lệnh

Tài liệu này mô tả cách tái lập **đúng** video thành phẩm, và cách dựng video mới.

## Chuẩn bị một lần

```powershell
winget install --id astral-sh.uv -e --scope user
```

```powershell
winget install --id Gyan.FFmpeg -e
```

```powershell
cd F:\AI-VIDEO-AGENT; uv sync --extra tts --extra clone
```

## Bật Duix

```powershell
docker compose -f F:\AI-VIDEO-AGENT\deploy\duix\docker-compose.yml up -d
```

Chờ khoảng 40 giây rồi kiểm tra:

```powershell
curl.exe "http://127.0.0.1:8383/easy/query?code=ping"
```

Trả về `{"code": 10004, "msg": "任务不存在"}` là container đã sẵn sàng.

## Chạy lại video thành phẩm

```powershell
cd F:\AI-VIDEO-AGENT; uv run aiva render demo-vn --execute --provider-mode real
```

Lệnh này:

1. Đọc `storyboard.json` — shot đã chốt `narration_audio_asset_id = golden-a-mo-dau`,
   nên **bỏ qua TTS** và dùng đúng file giọng PO đã nghiệm thu 8/10.
2. Gửi một job tới Duix với video khuôn mặt thật + WAV golden.
3. Sinh phụ đề SRT theo thời lượng audio thật.
4. Ghép bằng FFmpeg: khung 9:16, phụ đề, chữ chính xác, nhãn "Nội dung có sử dụng AI".

Kết quả nằm ở `F:\AI-VIDEO-AGENT-RUNTIME\projects\demo-vn\outputs\demo-vn-<run-id>.mp4`.

> Mỗi lần chạy sinh một `run_id` mới nên **không ghi đè** bản cũ. Nội dung có thể
> khác nhau chút ít giữa hai lần: Duix lấy mẫu ngẫu nhiên. Giọng thì luôn giống
> hệt vì lấy thẳng từ file golden.

## Dựng video mới từ brief tiếng Việt

```powershell
uv run aiva plan --brief "Nội dung cần nói..." --id du-an-moi --duration 40
```

```powershell
uv run aiva approve du-an-moi --by "Tên bạn"
```

```powershell
uv run aiva render du-an-moi --execute --provider-mode real
```

Đường này **có** chạy TTS: giọng được nhân bản từ tài sản mà
`providers.voice_asset_id` trỏ tới.

## Chỉ dựng lại một cảnh

```powershell
uv run aiva render demo-vn --execute --provider-mode real --only-shot shot-golden
```

Các shot khác dùng lại artifact đã có; chỉ shot được chỉ định mới chạy lại. Bước
ghép luôn chạy lại vì mốc phụ đề phụ thuộc toàn bộ chuỗi.

## Kiểm tra trước khi chạy

```powershell
uv run aiva doctor
```

```powershell
cd F:\AI-VIDEO-AGENT; uv run pytest -q
```

## Tắt Duix để trả RAM/VRAM

```powershell
docker compose -f F:\AI-VIDEO-AGENT\deploy\duix\docker-compose.yml down
```

## Ba lớp chặn chi phí vẫn còn nguyên

| | |
|---|---|
| Không cờ nào | dry-run, không provider nào được gọi |
| `--execute` | chạy, nhưng provider vẫn là **mock** |
| `--execute --provider-mode real` | chạy thật bằng VieNeu + Duix + FFmpeg, **toàn bộ local, 0 USD** |
| API tính tiền | vẫn khoá ở D05, cần thêm `--allow-paid` và `budget.cap_usd > 0` |
