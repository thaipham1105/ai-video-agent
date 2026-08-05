# Kiến trúc

## Ý tưởng chính

Repo này là **bộ điều phối**, không phải nơi chứa AI. Ba upstream (VieNeu-TTS,
Duix-Avatar, ViMax) được giữ tách biệt hoàn toàn và chỉ chạm tới qua adapter
(brief §3). Đổi provider không phải sửa orchestrator; đổi orchestrator không
phải sửa provider.

```text
                    ┌──────────────────────────────────────────┐
   Brief tiếng Việt │              cli/ (typer)                │
        ──────────► │  doctor · plan · approve · estimate      │
                    │  render · status · validate              │
                    └───────────────────┬──────────────────────┘
                                        │
                    ┌───────────────────▼──────────────────────┐
                    │             orchestrator/                │
                    │  planner   → storyboard từ brief         │
                    │  estimator → bảng chi phí                │
                    │  costguard → CHO PHÉP / TỪ CHỐI          │
                    │  pipeline  → chạy từng bước, có cache    │
                    │  repository→ cửa duy nhất ghi đĩa        │
                    └────┬──────────────────────────┬──────────┘
                         │                          │
          ┌──────────────▼────────────┐   ┌─────────▼─────────────┐
          │        providers/         │   │      composer/        │
          │ vieneu  → TTS   (D02)     │   │ subtitles → SRT       │
          │ duix    → avatar(D03)     │   │ ffmpeg    → dựng lệnh │
          │ vimax   → B-roll(D05)     │   │ runner    → chạy (D04)│
          │ video_api → B-roll(D05)   │   └───────────────────────┘
          └───────────────────────────┘
                         │
          ┌──────────────▼─────────────────────────────────────────┐
          │  domain/  — model + state machine, không phụ thuộc I/O │
          └────────────────────────────────────────────────────────┘
```

## Từng lớp

### `domain/`

Model pydantic và state machine. **Không** đọc đĩa, không gọi mạng, không biết
gì về provider. Nhờ vậy các luật nghiệp vụ (chuyển trạng thái hợp lệ, hash
storyboard, tính hợp lệ của consent) kiểm thử được mà không cần dựng gì.

Bốn hợp đồng dữ liệu, mỗi cái có một JSON Schema tương ứng trong `schemas/`:

| Model | File | Vai trò |
|---|---|---|
| `Project` | `project.json` | mục tiêu, tỷ lệ khung hình, ngân sách, trạng thái, phê duyệt |
| `Storyboard` | `storyboard.json` | scene/shot, thoại, chữ chính xác, thời lượng |
| `AssetManifest` | `asset-manifest.json` | đường dẫn, SHA-256, chủ sở hữu, consent |
| `RenderManifest` | `render-manifest.json` | provider/model/version, thời điểm, chi phí, file vào/ra |

Model và schema được viết **độc lập** với nhau. `tests/test_schemas.py` đối
chiếu hai bên, nên sai lệch lộ ra ngay.

### `orchestrator/`

| Module | Việc |
|---|---|
| `planner.py` | brief tiếng Việt → storyboard. D01 dùng `RuleBasedPlanner` (offline, tất định). `Planner` là Protocol nên sau này cắm Claude Code vào chỗ này. |
| `estimator.py` | gộp báo giá của mọi shot. Cộng bằng `Decimal`, **làm tròn lên**. |
| `costguard.py` | nơi duy nhất quyết định "có được chạy thật không". Xem [COST-SAFETY.md](COST-SAFETY.md). |
| `pipeline.py` | TTS → avatar → (B-roll) → phụ đề → ghép, có cache theo shot. |
| `repository.py` | cửa duy nhất ghi đĩa, luôn nằm dưới `AIVA_RUNTIME_DIR`. |
| `textutil.py` | tách câu tiếng Việt, slug, trích số điện thoại/giá/cụm pháp lý. |

### `providers/`

Mỗi provider trả lời ba câu: `info()` (tôi là ai), `quote()` (tốn bao nhiêu),
và hàm chạy. Tách `quote()` khỏi hàm chạy là lý do `estimate` và `--dry-run`
lấy được con số thật mà không chạm vào provider.

Mỗi upstream có hai lớp:

- **mock** — chạy được mọi lúc, không tải model, không GPU, không tiền.
- **adapter thật** — bị `GateNotReachedError` chặn cho tới gate của nó
  (xem [ADR-0003](adr/0003-gate-guard-in-code.md)).

### `composer/`

- `subtitles.py` — SRT UTF-8, mốc thời gian lấy từ **thời lượng WAV thật** chứ
  không phải con số dự kiến trong storyboard.
- `ffmpeg.py` — **chỉ dựng lệnh**, không bao giờ chạy. Nhờ vậy chuỗi tham số
  kiểm thử được đầy đủ trên máy chưa cài FFmpeg.
- `runner.py` — `MockComposer` (ghi lệnh vào manifest) và `FfmpegComposer` (D04).

## Vòng đời một project

```text
DRAFT ──plan──► PLANNED ──approve──► APPROVED ──render --execute──► RENDERING
                   ▲                     │                              │
                   │                     └──sửa storyboard──────────────┘
                   │                                                    ▼
                   └────────────────────────────────────────────── COMPOSED ──► DONE
                                                                        │
                                        render --only-shot ◄────────────┘
```

Phê duyệt được **neo vào SHA-256 của storyboard**. Sửa kịch bản là hash đổi, phê
duyệt hết hiệu lực, phải duyệt lại — đúng brief §9.

## Cache theo shot

Artifact nằm ở `artifacts/<shot-id>/<content-hash>/`. `content_hash` chỉ tính
trên những thứ ảnh hưởng đến kết quả render: thoại, thời lượng, chữ trên màn
hình, kế hoạch B-roll, provider dự kiến.

Nên: sửa thoại một shot → chỉ shot đó chạy lại; đổi tiêu đề project → không shot
nào phải chạy lại. Bước ghép luôn chạy lại vì nó rẻ và vì mốc phụ đề phụ thuộc
vào toàn bộ chuỗi.

Đây là cách hiện thực brief §4 ("không tự tạo lại cảnh vì lý do thẩm mỹ") và
§D04.5 ("sửa một scene/shot và tái ghép mà không render lại toàn bộ").

## Chữ chính xác

Số điện thoại, giá và câu chữ pháp lý được `textutil.extract_exact_texts()`
trích ra, gắn vào shot với `exact = True`, rồi `pipeline._draw_texts()` chuyển
thành lớp `drawtext` của FFmpeg kèm mốc thời gian tuyệt đối.

Những chuỗi này **không bao giờ** được giao cho model sinh video vẽ (brief
§D04.2) — sai một chữ số điện thoại là sai nghiêm trọng.

## Ranh giới không được vượt

- `domain/` không import `providers/`, `composer/` hay `orchestrator/`.
- Không import SDK nặng (`torch`, `vieneu`) ở cấp module — chỉ import bên trong
  hàm của adapter thật, để test mock không phải cài chúng.
- `composer/ffmpeg.py` không thực thi lệnh.
- Chỉ `repository.py` được ghi đĩa.
- Không đọc giá trị biến môi trường chứa secret; chỉ kiểm tra sự tồn tại.
