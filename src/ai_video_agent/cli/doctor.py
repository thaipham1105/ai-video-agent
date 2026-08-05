"""``aiva doctor`` — kiểm tra môi trường, **không sửa gì cả**.

Chỉ đọc: không cài đặt, không khởi động dịch vụ, không tải gì. Với biến môi
trường nhạy cảm, doctor chỉ báo *có/không*, tuyệt đối không in giá trị
(CLAUDE.md §4).
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ai_video_agent import CURRENT_GATE, __version__
from ai_video_agent.config import Config
from ai_video_agent.jsonschemas import SchemaName
from ai_video_agent.paths import repo_root, schemas_dir

#: Cổng local mà pipeline dự kiến dùng (khảo sát ở D00 §3).
EXPECTED_PORTS: dict[int, str] = {
    8383: "Duix gen-video (D03)",
    18180: "Duix TTS (D03, không dùng ở MVP)",
    10095: "Duix ASR (D03, không dùng ở MVP)",
    4173: "ViMax Web UI (D05)",
}

#: Ngưỡng cảnh báo dung lượng trống, dựa trên yêu cầu ~100 GB của Duix (D00 §2).
DISK_WARN_GB = 20.0
DUIX_RECOMMENDED_GB = 100.0


class Status(StrEnum):
    PASS = "PASS"  # noqa: S105 - tên trạng thái kiểm tra, không phải mật khẩu
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def _run_version(executable: str, *args: str) -> str | None:
    """Chạy ``<tool> --version`` và trả về dòng đầu; ``None`` nếu không có."""
    resolved = shutil.which(executable)
    if resolved is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - đường dẫn đã được shutil.which giải, tham số cố định
            [resolved, *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stdout or completed.stderr or "").strip()
    return output.splitlines()[0] if output else None


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _free_gb(path: Path) -> float | None:
    try:
        return shutil.disk_usage(path).free / (1024**3)
    except OSError:
        return None


def _check_tool(label: str, executable: str, *args: str, required: bool) -> CheckResult:
    version = _run_version(executable, *args)
    if version:
        return CheckResult(label, Status.PASS, version)
    status = Status.FAIL if required else Status.WARN
    return CheckResult(label, status, f"Không tìm thấy '{executable}' trên PATH")


def run_checks(config: Config | None = None) -> list[CheckResult]:
    """Chạy toàn bộ kiểm tra và trả về danh sách kết quả."""
    cfg = config or Config.from_env()
    results: list[CheckResult] = [
        CheckResult(
            "ai-video-agent",
            Status.PASS,
            f"v{__version__} — gate đang mở: {CURRENT_GATE}",
        ),
        CheckResult("python", Status.PASS, platform.python_version()),
        CheckResult("os", Status.INFO, f"{platform.system()} {platform.release()}"),
    ]

    # --- schemas ---
    try:
        missing = [
            name.filename for name in SchemaName if not (schemas_dir() / name.filename).is_file()
        ]
        results.append(
            CheckResult("schemas", Status.PASS, f"đủ 4 file tại {schemas_dir()}")
            if not missing
            else CheckResult("schemas", Status.FAIL, f"thiếu: {', '.join(missing)}")
        )
    except Exception as exc:  # noqa: BLE001 - doctor không được sập vì một mục
        results.append(CheckResult("schemas", Status.FAIL, str(exc)))

    # --- công cụ ---
    results.append(_check_tool("git", "git", "--version", required=True))
    results.append(_check_tool("uv", "uv", "--version", required=False))
    results.append(_check_tool("ffmpeg", cfg.ffmpeg_bin, "-version", required=False))
    results.append(_check_tool("ffprobe", cfg.ffprobe_bin, "-version", required=False))
    results.append(_check_tool("docker", "docker", "--version", required=False))

    daemon = _run_version("docker", "info", "--format", "{{.ServerVersion}}")
    results.append(
        CheckResult("docker daemon", Status.PASS, f"server {daemon}")
        if daemon
        else CheckResult("docker daemon", Status.WARN, "không kết nối được (cần cho Duix ở D03)")
    )

    gpu = _run_version(
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,driver_version",
        "--format=csv,noheader",
    )
    results.append(
        CheckResult("gpu", Status.PASS, gpu)
        if gpu
        else CheckResult("gpu", Status.WARN, "không thấy nvidia-smi (cần cho Duix ở D03)")
    )

    # --- đĩa ---
    for label, target in (("đĩa repo", repo_root()), ("đĩa runtime", cfg.runtime_dir)):
        anchor = Path(target).anchor or str(target)
        free = _free_gb(Path(anchor))
        if free is None:
            results.append(CheckResult(label, Status.WARN, f"không đọc được dung lượng {anchor}"))
        elif free < DISK_WARN_GB:
            results.append(
                CheckResult(label, Status.WARN, f"{anchor} còn {free:.1f} GB (dưới ngưỡng)")
            )
        else:
            note = "" if free >= DUIX_RECOMMENDED_GB else " — dưới mức Duix khuyến nghị 100 GB"
            results.append(CheckResult(label, Status.PASS, f"{anchor} còn {free:.1f} GB{note}"))

    # --- runtime dir ---
    runtime = cfg.runtime_dir
    if runtime.is_dir():
        results.append(CheckResult("runtime dir", Status.PASS, str(runtime)))
    else:
        results.append(
            CheckResult(
                "runtime dir", Status.WARN, f"{runtime} chưa tồn tại (sẽ tạo khi chạy 'aiva plan')"
            )
        )

    # --- cổng ---
    busy = [f"{port} ({label})" for port, label in EXPECTED_PORTS.items() if _port_in_use(port)]
    results.append(
        CheckResult("cổng local", Status.PASS, f"trống: {', '.join(map(str, EXPECTED_PORTS))}")
        if not busy
        else CheckResult("cổng local", Status.WARN, f"đang bị chiếm: {', '.join(busy)}")
    )

    # --- an toàn ---
    results.append(_check_gitignore())
    results.append(
        CheckResult(
            "chế độ provider",
            Status.PASS if cfg.provider_mode.value == "mock" else Status.WARN,
            f"{cfg.provider_mode.value}; allow_paid_apis={cfg.allow_paid_apis}",
        )
    )
    present = sorted(name for name, found in cfg.secrets_present.items() if found)
    results.append(
        CheckResult(
            "secret",
            Status.INFO,
            (
                f"biến có mặt (không đọc giá trị): {', '.join(present)}"
                if present
                else "không có biến secret nào trong môi trường"
            ),
        )
    )
    return results


def _check_gitignore() -> CheckResult:
    """``.env`` phải bị Git bỏ qua (brief §4)."""
    try:
        gitignore = repo_root() / ".gitignore"
    except Exception as exc:  # noqa: BLE001
        return CheckResult(".gitignore", Status.WARN, str(exc))
    if not gitignore.is_file():
        return CheckResult(".gitignore", Status.FAIL, "thiếu file .gitignore")
    lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    if ".env" in lines:
        return CheckResult(".gitignore", Status.PASS, ".env đã bị loại khỏi Git")
    return CheckResult(".gitignore", Status.FAIL, ".env CHƯA bị loại khỏi Git")


def worst_status(results: list[CheckResult]) -> Status:
    """Mức nghiêm trọng nhất trong toàn bộ kết quả."""
    if any(r.status is Status.FAIL for r in results):
        return Status.FAIL
    if any(r.status is Status.WARN for r in results):
        return Status.WARN
    return Status.PASS
