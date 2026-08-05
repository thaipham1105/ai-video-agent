# ADR-0002 — Dữ liệu runtime nằm ngoài repo Git

- Trạng thái: **Chấp nhận** (Gate D01)
- Ngày: 2026-08-04
- Bối cảnh: brief §6 — "Dữ liệu thật, model, Docker volumes, voice samples,
  avatar videos, cache, renders và outputs phải ở thư mục runtime riêng, bị Git
  ignore và không bị CodeGraph index."

## Quyết định

Toàn bộ dữ liệu vận hành nằm dưới `AIVA_RUNTIME_DIR`, mặc định
`F:\AI-VIDEO-AGENT-RUNTIME`:

```text
F:\AI-VIDEO-AGENT-RUNTIME\
└── projects\<project-id>\
    ├── project.json
    ├── storyboard.json
    ├── asset-manifest.json
    ├── assets\           <- giọng mẫu, video avatar, logo (do người dùng đưa vào)
    ├── artifacts\<shot-id>\<content-hash>\   <- cache theo shot
    ├── renders\<run-id>\ <- render-manifest.json, subtitles.srt, concat.txt
    └── outputs\          <- MP4 cuối
```

Ổ F được chọn theo khảo sát D00 §2: còn 382 GB trống, trong khi ổ C chỉ còn
97 GB và đang phải gánh Docker data.

## Vì sao không để trong repo

1. **Rủi ro rò rỉ.** Giọng mẫu và video của người thật mà lọt vào Git thì gần
   như không gỡ sạch được khỏi lịch sử.
2. **Kích thước.** Model và render nặng hàng GB; Git không hợp với dạng dữ liệu
   này.
3. **Ranh giới rõ ràng.** Repo = mã nguồn dự án sở hữu. Runtime = dữ liệu người
   dùng. Không có vùng xám.

## Thực thi bằng gì

- `orchestrator/repository.py` là **cửa duy nhất** ghi đĩa; nó luôn ghi dưới
  `runtime_dir`. Muốn kiểm chứng chỉ cần đọc một file.
- `.gitignore` chặn `runtime/`, `projects/`, `outputs/`, `renders/`, `models/`,
  cùng mọi đuôi media và model.
- `.codegraphignore` giữ dữ liệu runtime ra khỏi index CodeGraph.
- `tests/test_no_secrets.py` quét danh sách file Git đang theo dõi và **fail**
  nếu thấy media, model hay chuỗi giống secret.
- `tests/conftest.py` ép `AIVA_RUNTIME_DIR` về `tmp_path`, nên test không bao
  giờ đụng dữ liệu thật.

## Hệ quả

- Sao lưu repo **không** kèm sản phẩm. Người dùng phải tự sao lưu thư mục
  runtime — đã ghi trong `docs/INSTALL-WINDOWS.md`.
- Chuyển máy phải mang theo thư mục runtime hoặc chạy lại pipeline.
- `projects-example/` trong repo chỉ là **ví dụ đọc hiểu schema**, tuyệt đối
  không phải nơi chứa dữ liệu thật.
