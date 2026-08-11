"""Sinh ``report.html`` — trang nghiệm thu mở bằng double-click.

Vì sao cần: ``render-manifest.json`` đã ghi đủ model nào, hash file nào, VRAM
đỉnh bao nhiêu, chi phí bao nhiêu — nhưng nó là JSON và không ai đọc. Một bản
ghi không ai đọc thì không khác gì không có.

Ba ràng buộc định hình file này:

* **Không tự tính lại gì.** Mọi số đều đọc từ manifest. Trang này báo cáo, không
  đo đạc; một con số nó tự bịa ra sẽ mâu thuẫn với manifest và phá luôn giá trị
  truy vết của cả hai.
* **Chạy được khi mở bằng ``file://``.** Không CSS/JS ngoài, không gọi mạng.
* **Không rò đường dẫn không cần thiết.** Chỉ đường dẫn **tương đối trong
  project**, không phải đường tuyệt đối của máy — trang này có thể bị gửi đi.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ai_video_agent.domain.render import RenderManifest

#: Cảnh báo bắt buộc hiện trên mọi báo cáo dùng Duix. Không phải lỗi cấu hình —
#: là trần chất lượng đã đo ở bake-off D04-G §10, và người nghiệm thu cần biết
#: trước khi đánh giá khẩu hình.
LIPSYNC_NOTE = (
    "Khẩu hình tiếng Việt có trần chất lượng đã biết: Duix trích đặc trưng tiếng "
    "bằng bộ mã hoá huấn luyện trên tiếng Quan Thoại, nên âm /v/ và phụ âm cuối "
    "-p hay sai hình miệng. Đây là giới hạn của model, không phải lỗi cấu hình."
)

REPORT_FILENAME = "report.html"

#: Cảnh báo **không** đưa vào báo cáo. Lệnh FFmpeg đầy đủ dài vài nghìn ký tự và
#: mang theo đường dẫn tuyệt đối của máy (tên người dùng, cây thư mục). Nó vẫn
#: nằm nguyên trong ``render-manifest.json`` để chẩn đoán; nhưng trang này có thể
#: được gửi cho khách, nên không mang theo thứ đó.
SKIP_WARNING_PREFIXES = ("Lệnh FFmpeg:",)

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem 1.25rem 4rem; font-family: 'Segoe UI', system-ui, sans-serif;
       line-height: 1.55; max-width: 60rem; margin-inline: auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .6rem; text-transform: uppercase;
     letter-spacing: .06em; opacity: .65; }
.sub { opacity: .7; margin: 0 0 1.5rem; font-size: .9rem; }
video { width: 100%; max-height: 70vh; background: #000; border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid rgba(128,128,128,.28);
         vertical-align: top; }
th { font-weight: 600; white-space: nowrap; opacity: .8; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
code, .mono { font-family: ui-monospace, Consolas, monospace; font-size: .85em;
              word-break: break-all; }
.tag { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .78rem;
       font-weight: 600; }
.ok { background: rgba(46,160,67,.18); color: #2ea043; }
.bad { background: rgba(218,54,51,.18); color: #da3633; }
.warn { border-left: 3px solid #d29922; background: rgba(210,153,34,.1); padding: .7rem .9rem;
        margin: .6rem 0; border-radius: 0 6px 6px 0; font-size: .9rem; }
.wrap { overflow-x: auto; }
.miss { opacity: .55; font-style: italic; }
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _fmt(value: object, suffix: str = "") -> str:
    """``None`` là *chưa đo được*, hiện rõ như thế thay vì thành 0 hay ô trống."""
    if value is None:
        return '<span class="miss">chưa đo được</span>'
    return _esc(value) + _esc(suffix)


def _video_block(manifest: RenderManifest) -> str:
    """Video nhúng + đường dẫn dự phòng.

    Đường dẫn tương đối tính từ ``renders/<run>/`` ra ``outputs/`` — báo cáo nằm
    cạnh manifest nên phải lùi hai cấp. Trình duyệt chặn ``file://`` phát video
    thì vẫn còn dòng đường dẫn để copy.
    """
    if not manifest.outputs:
        return '<p class="miss">Run này chưa sinh ra file video nào.</p>'
    ten = manifest.outputs[0].replace("\\", "/").rsplit("/", 1)[-1]
    ref = f"../../outputs/{ten}"
    gia = (
        " (file GIẢ do mock sinh ra, không phải video thật)"
        if manifest.has_placeholder_output
        else ""
    )
    return (
        f'<video controls preload="metadata" src="{_esc(ref)}"></video>'
        f'<p class="sub">Không xem được ở đây thì mở thẳng file:<br>'
        f'<code>outputs/{_esc(ten)}</code>{_esc(gia)}</p>'
    )


def _shot_rows(manifest: RenderManifest) -> str:
    rows: list[str] = []
    for r in manifest.records:
        p = r.avatar_provenance
        res = p.resources if p is not None else None
        rows.append(
            "<tr>"
            f"<td>{_esc(r.stage.value)}</td>"
            f"<td>{_esc(r.shot_id or '—')}</td>"
            f"<td>{_esc(r.provider)}</td>"
            f"<td>{_esc(r.status.value)}</td>"
            f'<td class="num">{_fmt(p.output_duration_sec if p else None, " s")}</td>'
            f'<td class="num">{_fmt(res.render_seconds if res else None, " s")}</td>'
            f'<td class="num">{_fmt(res.peak_vram_mib if res else None, " MiB")}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def _provenance_blocks(manifest: RenderManifest) -> str:
    """Truy vết từng bước avatar: model nào, hash gì vào, hash gì ra."""
    blocks: list[str] = []
    for r in manifest.records:
        p = r.avatar_provenance
        if p is None:
            continue
        hang = [
            ("Model", f"{p.model} @ {p.model_version}"),
            ("Bộ mã hoá tiếng", p.audio_encoder),
            ("Ngôn ngữ đã kiểm chứng", ", ".join(p.languages_verified) or "—"),
            ("fps nguồn → ra", f"{p.source_fps} → {p.output_fps}"),
            ("Kích thước", f"{p.output_width}x{p.output_height}"),
            ("SHA-256 audio vào", p.audio_sha256),
            ("SHA-256 nguồn avatar", p.source_asset_sha256),
            ("SHA-256 video ra", p.output_sha256),
        ]
        if p.image_digest:
            hang.append(("Digest image", p.image_digest))
        body = "\n".join(
            f'<tr><th>{_esc(k)}</th><td class="mono">{_esc(v)}</td></tr>' for k, v in hang
        )
        blocks.append(
            f"<h2>Truy vết — {_esc(r.shot_id or r.stage.value)}</h2>"
            f'<div class="wrap"><table>{body}</table></div>'
        )
    return "\n".join(blocks)


def _subtitle_block(subtitles: str | None) -> str:
    if not subtitles:
        return ""
    return f"<h2>Phụ đề</h2><div class=\"wrap\"><pre class=\"mono\">{_esc(subtitles)}</pre></div>"


def build_report_html(manifest: RenderManifest, *, subtitles: str | None = None) -> str:
    """Dựng trang HTML tự chứa từ **đúng những gì manifest đã ghi**."""
    thanh_cong = manifest.status == "succeeded"
    tong = sum(
        r.avatar_provenance.output_duration_sec
        for r in manifest.records
        if r.avatar_provenance is not None
    )
    dau = [
        ("Project", manifest.project_id),
        ("Run", manifest.run_id),
        ("Chế độ provider", manifest.provider_mode.value),
        ("Bắt đầu", manifest.created_at.isoformat()),
        ("Kết thúc", manifest.finished_at.isoformat() if manifest.finished_at else None),
        ("Tổng thời lượng", f"{tong:.2f} s" if tong else None),
        ("Chi phí thật", f"{manifest.actual_cost_usd:.4f} USD"),
        ("Gắn nhãn AI", "có" if manifest.ai_disclosure_applied else "không"),
        ("Hash storyboard", manifest.storyboard_sha256),
    ]
    meta = "\n".join(
        f"<tr><th>{_esc(k)}</th><td class=\"mono\">{_fmt(v)}</td></tr>" for k, v in dau
    )
    tools = "\n".join(
        f'<tr><th>{_esc(k)}</th><td class="mono">{_esc(v)}</td></tr>'
        for k, v in sorted(manifest.tool_versions.items())
    )
    canh_bao = "\n".join(
        f'<div class="warn">{_esc(w)}</div>'
        for w in manifest.warnings
        if not w.startswith(SKIP_WARNING_PREFIXES)
    )
    nhan = ('<span class="tag ok">THÀNH CÔNG</span>' if thanh_cong
            else f'<span class="tag bad">{_esc(manifest.status.upper())}</span>')

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nghiệm thu {_esc(manifest.project_id)} — {_esc(manifest.run_id)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{_esc(manifest.project_id)} {nhan}</h1>
<p class="sub">Báo cáo nghiệm thu. Sản phẩm là file MP4; trang này chỉ để xem lại
và truy vết. Mọi số liệu đọc từ <code>render-manifest.json</code> cùng thư mục.</p>

{_video_block(manifest)}

<div class="warn">{_esc(LIPSYNC_NOTE)}</div>
{canh_bao}

<h2>Thông tin chung</h2>
<div class="wrap"><table>{meta}</table></div>

<h2>Từng bước</h2>
<div class="wrap"><table>
<tr><th>Bước</th><th>Shot</th><th>Provider</th><th>Kết quả</th>
    <th>Thời lượng</th><th>Thời gian dựng</th><th>VRAM đỉnh</th></tr>
{_shot_rows(manifest)}
</table></div>
<p class="sub">VRAM đỉnh là đỉnh của <strong>cả card</strong> lúc chạy — gồm cả
nền hệ điều hành và ứng dụng khác, không riêng backend. Đừng so thẳng với ước
lượng VRAM của provider: hai số khác gốc.</p>

{_subtitle_block(subtitles)}

<h2>Phiên bản công cụ</h2>
<div class="wrap"><table>{tools}</table></div>

{_provenance_blocks(manifest)}
</body>
</html>
"""


def write_report(
    run_dir: Path, manifest: RenderManifest, *, subtitles_path: Path | None = None
) -> Path:
    """Ghi ``report.html`` cạnh manifest và trả về đường dẫn.

    Đọc phụ đề nếu có; thiếu thì bỏ qua chứ không hỏng — báo cáo thiếu một mục
    vẫn dùng được, còn render thành công mà báo lỗi ở khâu viết báo cáo thì vô lý.
    """
    phu_de: str | None = None
    if subtitles_path is None:
        subtitles_path = run_dir / "subtitles.srt"
    if subtitles_path.is_file():
        try:
            phu_de = subtitles_path.read_text(encoding="utf-8")
        except OSError:
            phu_de = None

    dich = run_dir / REPORT_FILENAME
    dich.write_text(build_report_html(manifest, subtitles=phu_de), encoding="utf-8")
    return dich
