# Mẫu ghi nhận đồng ý sử dụng hình ảnh / giọng nói

Brief §4: *"Không sử dụng hình ảnh hay giọng của người khác nếu chưa có sự đồng ý
rõ ràng. Metadata của dự án phải ghi nhận nguồn và quyền sử dụng tài sản."*

## Cần thu thập những gì

| Trường | Ý nghĩa | Ví dụ |
|---|---|---|
| `owner` | Ai sở hữu hình ảnh/giọng nói đó | `"Nguyễn Văn A"` |
| `granted_by` | Ai ký cho phép (thường trùng `owner`) | `"Nguyễn Văn A"` |
| `granted_at` | Thời điểm cho phép, dạng ISO 8601 | `"2026-08-01T10:00:00+00:00"` |
| `scope` | **Phạm vi được phép dùng** | `"Video marketing bất động sản của công ty X, đăng Facebook/TikTok, đến hết 2027"` |
| `evidence_ref` | Con trỏ tới hồ sơ đồng ý nằm ngoài repo | `"HS-2026-001"` |
| `status` | `granted` / `pending` / `denied` / `not_required` | `"granted"` |

`not_required` chỉ dùng cho tài sản do chính dự án tạo ra (logo công ty, font đã
mua bản quyền) — không cần xin phép ai.

## Ghi vào asset-manifest.json như thế nào

```json
{
  "id": "avatar-anh-a",
  "path": "avatar/anh-a-2026-08.mp4",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "kind": "avatar_source",
  "bytes": 18234567,
  "source": "Quay tại văn phòng ngày 2026-08-01",
  "notes": "Chỉ dùng cho chiến dịch Q3/2026",
  "consent": {
    "status": "granted",
    "owner": "Nguyễn Văn A",
    "granted_by": "Nguyễn Văn A",
    "granted_at": "2026-08-01T10:00:00+00:00",
    "scope": "Video marketing bất động sản của công ty X, đăng Facebook/TikTok/Zalo, đến hết 2027",
    "evidence_ref": "HS-2026-001"
  }
}
```

## Mẫu văn bản đồng ý (bản giấy hoặc email)

> Tôi, **[Họ tên]**, đồng ý cho **[Tên công ty]** sử dụng **[hình ảnh / video /
> giọng nói]** của tôi để tạo nội dung video có sử dụng công nghệ AI, trong phạm
> vi: **[mô tả phạm vi — mục đích, kênh phát hành, thời hạn]**.
>
> Tôi hiểu rằng công nghệ này có thể tạo ra video trong đó tôi nói những câu tôi
> chưa từng nói, và nội dung sẽ được gắn nhãn là có sử dụng AI.
>
> Tôi có thể rút lại sự đồng ý này bằng văn bản bất cứ lúc nào. Khi đó
> **[Tên công ty]** sẽ ngừng tạo nội dung mới từ tài sản của tôi.
>
> Ngày: **[ngày]** — Chữ ký: **[chữ ký]**

Lưu bản gốc **ngoài repo**, chỉ ghi mã hồ sơ vào `evidence_ref`.

## Khi đồng ý bị rút lại

1. Đổi `consent.status` thành `"denied"` trong `asset-manifest.json`.
2. Cost guard sẽ tự chặn mọi lần render thật từ thời điểm đó
   (`ConsentMissingError`).
3. Xoá tài sản khỏi thư mục runtime.
4. Rà lại các video đã phát hành theo cam kết trong `scope`.
