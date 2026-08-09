"""QC tự động cho clip B-roll — chạy local bằng FFmpeg, không gọi API.

Ranh giới quyền hạn, cố định từ D05-C §7.5:

* QC **chỉ có quyền TỪ CHỐI**.
* ``PASS`` chỉ nghĩa là "không phát hiện lỗi máy đo được", **không** phải "đạt
  thẩm mỹ". Chỉ con người mới cấp được ``HUMAN_APPROVED``.

Về ngưỡng: ``scene_score = 0.10`` mới là **PROVISIONAL**, suy ra từ đúng một mẫu
(clip D05-B). Một mẫu không đủ chốt ngưỡng, nên auto-reject theo ngưỡng này
**mặc định TẮT** cho tới khi hiệu chuẩn xong.

``mpdecimate`` chỉ phát hiện khung *gần trùng nhau*. Cảnh quay tĩnh hợp lệ, trời
phẳng, hay chuyển động rất chậm đều tạo ra khung gần trùng mà không có lỗi nào.
Vì vậy nó chỉ sinh **bằng chứng/WARN**, không tự kết luận.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Ngưỡng suy ra từ clip D05-B: nền 0,037 tới 0,053, điểm cắt 0,308.
#: CHƯA hiệu chuẩn trên nhiều mẫu ⇒ chưa được dùng để auto-reject.
PROVISIONAL_SCENE_THRESHOLD = 0.10

#: Golden positive — lỗi có thật đã đo được, dùng làm ca thử của detector.
GOLDEN_POSITIVE = {
    "clip": "d05b_broll_9x16_noaudio.mp4",
    "pts_time": 3.25,
    "frame": 78,
    "total_frames": 120,
    "scene_score": 0.308448,
}


@dataclass
class CheckResult:
    check_id: str
    status: str  # PASS | FAIL | WARN | SKIP
    detail: str = ""
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass
class QcReport:
    clip_path: str
    #: Băm của chính clip. Phê duyệt gắn với **nội dung clip**, không gắn với
    #: đường dẫn: clip đổi thì phê duyệt cũ mất hiệu lực.
    clip_sha256: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    verdict: str = "PASS"
    #: ``None`` cho tới khi có người duyệt. QC không bao giờ tự đặt giá trị này.
    human_approval: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def sha256_of(path: Path) -> str:
    """Băm nội dung clip — mốc để biết phê duyệt cũ còn hiệu lực hay không."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    # argv dựng trong module này, đường dẫn ffmpeg do người gọi giải sẵn
    return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603


def _probe(ffprobe: str, clip: Path, entries: str, stream: str | None = "v:0") -> str:
    cmd = [ffprobe, "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "csv=p=0", str(clip)]
    return _run(cmd).stdout.strip()


def check_decode(ffmpeg: str, clip: Path) -> CheckResult:
    proc = _run([ffmpeg, "-v", "error", "-i", str(clip), "-f", "null", "-"])
    if proc.returncode != 0 or proc.stderr.strip():
        return CheckResult(
            "decode",
            "FAIL",
            "Giải mã không sạch.",
            {"stderr": proc.stderr.strip()[:500]},
        )
    return CheckResult("decode", "PASS", "Giải mã sạch toàn bộ.")


def check_resolution(ffprobe: str, clip: Path, want_w: int, want_h: int) -> CheckResult:
    raw = _probe(ffprobe, clip, "stream=width,height")
    parts = [p for p in raw.replace("\n", ",").split(",") if p]
    if len(parts) < 2:
        return CheckResult("resolution", "FAIL", f"Không đọc được kích thước ({raw!r}).")
    got_w, got_h = int(parts[0]), int(parts[1])
    if (got_w, got_h) != (want_w, want_h):
        return CheckResult(
            "resolution",
            "FAIL",
            f"Cần {want_w}x{want_h}, nhận {got_w}x{got_h}.",
            {"want": [want_w, want_h], "got": [got_w, got_h]},
        )
    return CheckResult("resolution", "PASS", f"{got_w}x{got_h}")


def check_source_fps(ffprobe: str, clip: Path, want_fps: int) -> CheckResult:
    raw = _probe(ffprobe, clip, "stream=r_frame_rate").split("\n")[0]
    if "/" not in raw:
        return CheckResult("source_fps", "FAIL", f"Không đọc được fps ({raw!r}).")
    num, den = raw.split("/")
    got = float(num) / float(den) if float(den) else 0.0
    if abs(got - want_fps) > 0.01:
        return CheckResult(
            "source_fps",
            "FAIL",
            f"Cần {want_fps} fps ở nguồn, nhận {got:g}.",
            {"want": want_fps, "got": got},
        )
    return CheckResult("source_fps", "PASS", f"{got:g} fps")


def check_duration(ffprobe: str, clip: Path, want_sec: float, tol: float = 0.10) -> CheckResult:
    raw = _probe(ffprobe, clip, "format=duration", stream=None)
    try:
        got = float(raw)
    except ValueError:
        return CheckResult("duration", "FAIL", f"Không đọc được thời lượng ({raw!r}).")
    delta = abs(got - want_sec)
    if delta > tol:
        return CheckResult(
            "duration",
            "FAIL",
            f"Cần {want_sec:g}s (dung sai {tol:g}s), nhận {got:.3f}s (lệch {delta:.3f}s).",
            {"want": want_sec, "got": got, "delta": delta},
        )
    return CheckResult("duration", "PASS", f"{got:.3f}s (lệch {delta:.3f}s)")


def detect_scene_cuts(
    ffmpeg: str, clip: Path, threshold: float = PROVISIONAL_SCENE_THRESHOLD
) -> list[dict[str, float]]:
    """Trả về danh sách khung vượt ngưỡng, kèm ``pts_time`` và điểm số."""
    proc = _run(
        [
            ffmpeg, "-v", "error", "-i", str(clip),
            "-filter_complex", f"select='gt(scene,{threshold})',metadata=print:file=-",
            "-f", "null", "-",
        ]
    )
    text = proc.stdout + proc.stderr
    cuts: list[dict[str, float]] = []
    pending: float | None = None
    for line in text.splitlines():
        m_time = re.search(r"pts_time:([0-9.]+)", line)
        if m_time:
            pending = float(m_time.group(1))
        m_score = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if m_score and pending is not None:
            cuts.append({"pts_time": pending, "scene_score": float(m_score.group(1))})
            pending = None
    return cuts


def check_scene_cut(
    ffmpeg: str,
    clip: Path,
    *,
    threshold: float = PROVISIONAL_SCENE_THRESHOLD,
    calibrated: bool = False,
) -> CheckResult:
    """Bắt cắt cảnh.

    ``calibrated=False`` (mặc định) ⇒ chỉ **WARN**, vì ngưỡng chưa hiệu chuẩn
    trên nhiều mẫu. Chỉ khi PO xác nhận đã hiệu chuẩn mới được auto-reject.
    """
    cuts = detect_scene_cuts(ffmpeg, clip, threshold)
    if not cuts:
        return CheckResult(
            "scene_cut", "PASS", f"Không thấy cắt cảnh nào vượt {threshold:g}.",
            {"threshold": threshold, "calibrated": calibrated},
        )
    where = ", ".join(f"{c['pts_time']:.3f}s (score {c['scene_score']:.3f})" for c in cuts)
    status = "FAIL" if calibrated else "WARN"
    suffix = "" if calibrated else " — ngưỡng CHƯA hiệu chuẩn nên chỉ cảnh báo."
    return CheckResult(
        "scene_cut",
        status,
        f"Phát hiện {len(cuts)} điểm cắt: {where}.{suffix}",
        {"threshold": threshold, "calibrated": calibrated, "cuts": cuts},
    )


def count_near_duplicate_frames(ffmpeg: str, clip: Path) -> dict[str, object]:
    """Đếm khung bị ``mpdecimate`` loại — **bằng chứng**, không phải kết luận."""
    proc = _run(
        [ffmpeg, "-v", "info", "-i", str(clip), "-vf", "mpdecimate", "-f", "null", "-"]
    )
    text = proc.stdout + proc.stderr
    dropped = len(re.findall(r"drop_count:\s*\d+", text))
    total = 0
    m = re.search(r"frame=\s*(\d+)", text)
    if m:
        total = int(m.group(1))
    return {"near_duplicate_events": dropped, "frames_reported": total}


def check_freeze_evidence(ffmpeg: str, clip: Path) -> CheckResult:
    """Thu bằng chứng khung gần trùng. **Không có ngưỡng, không tự kết luận.**"""
    evidence = count_near_duplicate_frames(ffmpeg, clip)
    return CheckResult(
        "freeze_evidence",
        "WARN" if evidence["near_duplicate_events"] else "PASS",
        (
            "mpdecimate chỉ phát hiện khung GẦN TRÙNG, không tự chứng minh lỗi freeze. "
            "Chưa có ngưỡng đã hiệu chuẩn nên đây chỉ là bằng chứng để người xem."
        ),
        evidence,
    )


def run_qc(
    *,
    clip: Path,
    ffmpeg: str,
    ffprobe: str,
    want_width: int,
    want_height: int,
    want_fps: int,
    want_duration_sec: float,
    scene_threshold: float = PROVISIONAL_SCENE_THRESHOLD,
    scene_threshold_calibrated: bool = False,
) -> QcReport:
    """Chạy đủ bộ kiểm và tổng hợp phán quyết."""
    report = QcReport(clip_path=str(clip), clip_sha256=sha256_of(clip))
    report.checks = [
        check_decode(ffmpeg, clip),
        check_resolution(ffprobe, clip, want_width, want_height),
        check_source_fps(ffprobe, clip, want_fps),
        check_duration(ffprobe, clip, want_duration_sec),
        check_scene_cut(
            ffmpeg, clip, threshold=scene_threshold, calibrated=scene_threshold_calibrated
        ),
        check_freeze_evidence(ffmpeg, clip),
    ]
    report.verdict = "FAIL" if any(c.status == "FAIL" for c in report.checks) else "PASS"
    report.notes.append(
        "QC tự động chỉ có quyền TỪ CHỐI. PASS không phải là duyệt thẩm mỹ; "
        "shot vẫn cần HUMAN_APPROVED trước khi vào composer."
    )
    if not scene_threshold_calibrated:
        report.notes.append(
            f"Ngưỡng scene_score={scene_threshold:g} là PROVISIONAL (suy từ 1 mẫu D05-B). "
            "Auto-reject theo ngưỡng này đang TẮT."
        )
    return report
