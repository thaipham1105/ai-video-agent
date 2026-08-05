# AGENTS.md

Mọi agent (Claude Code hoặc công cụ khác) làm việc trên repo này phải đọc
[CLAUDE.md](CLAUDE.md) trước, rồi mới đến file này.

## Đọc trước khi sửa code

1. [AI_VIDEO_AGENT_BUILD_BRIEF.md](AI_VIDEO_AGENT_BUILD_BRIEF.md) — nguồn sự thật.
2. [CLAUDE.md](CLAUDE.md) — quy tắc bắt buộc và ranh giới gate.
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — ranh giới module.
4. [docs/COST-SAFETY.md](docs/COST-SAFETY.md) — cơ chế chặn chi phí.
5. [docs/UPSTREAM-AUDIT.md](docs/UPSTREAM-AUDIT.md) — license và API upstream.

## Lệnh chuẩn

| Việc | Lệnh |
|---|---|
| Cài môi trường | `uv sync` |
| Test | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Typecheck | `uv run mypy` |
| CLI | `uv run aiva --help` |

## Ranh giới không được vượt

- Không thêm dependency gọi mạng vào đường đi mặc định của test.
- Không import SDK nặng (`torch`, `vieneu`, …) ở top-level module — chỉ import
  bên trong hàm của adapter thật, để test mock không phải cài chúng.
- Không thực thi `ffmpeg` trong `composer/ffmpeg.py`; module đó chỉ **dựng lệnh**.
  Việc thực thi mở ở D04.
- Không đọc giá trị biến môi trường chứa secret; chỉ kiểm tra sự tồn tại.
- Không viết dữ liệu project vào trong repo. Mọi ghi đĩa đi qua
  `orchestrator/repository.py` và nằm dưới `AIVA_RUNTIME_DIR`.

## Khi thêm provider mới

1. Hiện thực Protocol trong `providers/base.py` (`info`, `quote`, và hàm chạy).
2. Viết mock deterministic trước, test đường đi qua mock.
3. Adapter thật phải khai báo `gate` của nó và ném `GateNotReachedError`
   cho tới khi gate đó được duyệt.
4. Nếu provider tính tiền: `ProviderInfo.billable = True` để cost guard chặn.
