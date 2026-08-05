# Backlog — yêu cầu đã ghi nhận, CHƯA triển khai

Nơi giữ các yêu cầu sản phẩm đã chốt nhưng cố ý để lại sau. Mục ở đây **không
được** làm phình phạm vi của gate đang chạy. Mỗi mục chỉ rời khỏi backlog khi có
một gate riêng được duyệt.

---

## BL-001 — Mô-đun "Tủ đồ AI" (AI Wardrobe)

- Ghi nhận: 2026-08-04, trong lúc đang ở Gate D02
- Trạng thái: **ĐÃ GHI NHẬN — chưa triển khai**
- Điều kiện khởi động: avatar gốc **D03** và pipeline **D04** chạy ổn định, sau
  đó lập **gate riêng**
- Người yêu cầu: chủ máy

### Yêu cầu

Tạo được nhiều phiên bản **trang phục** từ cùng một nhân vật (Phạm Văn Thái), mà
**giữ ổn định**:

- khuôn mặt
- tóc
- nhận diện (identity)
- vóc dáng

Danh sách trang phục ban đầu:

| # | outfit | Ghi chú |
|---|---|---|
| 1 | Vest doanh nhân | |
| 2 | Sơ mi công sở | |
| 3 | Polo thương hiệu TPV | có logo thương hiệu |
| 4 | Áo Hội Doanh nhân trẻ | đồng phục hội |
| 5 | Trang phục đời thường | |
| 6 | Trang phục tuỳ chỉnh theo sự kiện | mở, thêm theo từng dịp |

### Ràng buộc kiến trúc (bắt buộc tôn trọng từ D03 trở đi)

1. **Mỗi video chọn một `outfit_id` riêng.** Trang phục là thuộc tính của *lần
   render*, không phải của nhân vật.
2. **Không gắn cứng trang phục vào hồ sơ khuôn mặt hoặc hồ sơ giọng nói.** Ba
   thứ này phải là ba trục độc lập:

   ```text
   character (mặt + tóc + vóc dáng + identity)
        ×  outfit (trang phục)
        ×  voice (giọng)
        =  một lần render
   ```

3. **Thêm trang phục mới không được đòi tạo lại toàn bộ nhân vật.** Thêm một
   outfit phải là thêm dữ liệu, không phải huấn luyện lại/enroll lại khuôn mặt.

### Điều D03 cần chừa sẵn (chỉ là ghi chú, KHÔNG làm bây giờ)

Để sau này không phải phá đi làm lại, khi thiết kế D03 nên tránh mô hình hoá
avatar như **một khối duy nhất**:

- `AssetKind.AVATAR_SOURCE` hiện đang là một tài sản phẳng. Khi tới D03, cân
  nhắc tách thành hồ sơ nhân vật (character profile) và các biến thể trang phục
  trỏ về hồ sơ đó, thay vì mỗi bộ đồ là một avatar tách rời.
- `project.json` sẽ cần một trường kiểu `character_id` + `outfit_id` ở cấp
  project hoặc cấp render, chứ không phải một đường dẫn video cứng.
- `render-manifest.json` phải ghi lại `outfit_id` đã dùng để truy vết được.
- Mỗi outfit vẫn phải khai báo `consent` riêng trong `asset-manifest.json` nếu
  nó là tài sản quay thật (brief §4).

Những gạch đầu dòng trên **chưa được hiện thực**. Chúng chỉ để người làm D03 đọc
trước khi chốt thiết kế avatar, tránh khoá cứng vào một hình dạng khó mở rộng.

### Không làm ở D02

D02 chỉ lo VieNeu-TTS. Không đụng gì tới avatar, trang phục hay hình ảnh.
