# assets-example

Thư mục này **chỉ chứa mô tả bằng chữ**. Không có file media nào ở đây, và
không bao giờ được có.

## Tài sản thật đặt ở đâu

```text
F:\AI-VIDEO-AGENT-RUNTIME\projects\<project-id>\assets\
├── avatar\      <- video/ảnh người đại diện (đã được người đó cho phép)
├── voice\       <- mẫu giọng 3–8 giây (đã được người đó cho phép)
├── brand\       <- logo, font
└── broll\       <- hình/video minh hoạ
```

Thư mục runtime nằm ngoài Git và ngoài index CodeGraph — xem
[ADR-0002](../docs/adr/0002-runtime-data-outside-repo.md).

## Quy tắc bắt buộc

1. **Không dùng hình ảnh hay giọng của người khác khi chưa có sự đồng ý rõ ràng**
   (brief §4). Kể cả để thử.
2. Mọi tài sản phải được khai báo trong `asset-manifest.json` với `owner` và
   `consent`. Xem [consent-template.md](consent-template.md).
3. `consent.evidence_ref` chỉ là **con trỏ** (mã hồ sơ, tên file giấy đồng ý).
   Không bao giờ nhúng nội dung bằng chứng vào manifest.
4. Còn tài sản `pending`/`denied` thì render thật bị cost guard chặn.
5. Mẫu giọng không được sao chép vào repo, không được phát lại, không được ghi
   log (brief §D02.4).

## Thêm một tài sản

```powershell
# 1. Chép file vào thư mục assets của project trong runtime
Copy-Item .\logo.png F:\AI-VIDEO-AGENT-RUNTIME\projects\demo-bds\assets\brand\

# 2. Tính SHA-256 để ghi vào manifest
Get-FileHash F:\AI-VIDEO-AGENT-RUNTIME\projects\demo-bds\assets\brand\logo.png -Algorithm SHA256

# 3. Thêm mục vào asset-manifest.json (xem mẫu ở projects-example/)
# 4. Kiểm tra lại
uv run aiva validate demo-bds
```

`path` trong manifest là **đường dẫn tương đối** so với thư mục `assets` của
project. Đường dẫn tuyệt đối hoặc có `..` bị cả model lẫn JSON Schema từ chối.
