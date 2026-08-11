"""Bật container Duix trước khi mở UI — logic nằm ở Python, không ở PowerShell.

Vì sao không viết thẳng vào ``.ps1``: script shell không test được nếu không có
Docker thật, mà đây lại đúng chỗ dễ sai nhất (Docker chưa mở, container bật
nhưng chưa nghe, chờ vô hạn). Đặt logic ở đây thì mọi nhánh hỏng đều có test,
còn ``.ps1`` chỉ còn là một dòng gọi ``uv run aiva ui``.

**Không tự tắt container khi UI đóng.** Nạp model mất ~17 s và người dùng
thường dựng nhiều video liên tiếp; tắt hộ sẽ bắt họ trả lại khoản đó mỗi lần.
Tắt bằng ``docker compose ... down`` khi thực sự xong.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

COMPOSE_FILE = Path("deploy/duix/docker-compose.yml")

#: Bật nguội mất ~17 s trên máy đã đo. 120 s là dư cho ổ chậm, và **hữu hạn** —
#: yêu cầu số 5 của D06-A: không treo vô hạn.
READY_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 2.0
DOCKER_TIMEOUT_SEC = 30.0
COMPOSE_TIMEOUT_SEC = 180.0


@dataclass(frozen=True)
class LauncherResult:
    """Kết quả cố gắng đưa Duix vào trạng thái sẵn sàng."""

    ready: bool
    #: ``already`` | ``started`` | ``docker_missing`` | ``docker_down``
    #: | ``compose_failed`` | ``timeout``
    reason: str
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return not self.ready


def _http_alive(url: str, timeout: float = 3.0) -> bool:
    """Endpoint có ai nghe không. **Mã HTTP nào cũng tính là sống**, kể cả 404 —
    ``/`` không phải route của Duix."""
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310 - localhost cố định
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv cố định, đường dẫn do shutil.which giải
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )


def ensure_duix_ready(
    base_url: str,
    *,
    compose_file: Path = COMPOSE_FILE,
    timeout_sec: float = READY_TIMEOUT_SEC,
    poll_interval_sec: float = POLL_INTERVAL_SEC,
    http_probe: Callable[[str], bool] | None = None,
    which: Callable[[str], str | None] | None = None,
    runner: Callable[[list[str], float], subprocess.CompletedProcess[str]] | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> LauncherResult:
    """Đưa Duix về trạng thái nghe được, hoặc trả lý do rõ ràng.

    Mọi thứ chạm ra ngoài đều tiêm được — đó là điều kiện để test được nhánh
    "Docker chưa chạy" và nhánh "hết giờ" mà không cần Docker thật.
    """
    probe = http_probe or _http_alive
    tim = which or shutil.which
    chay = runner or _run
    nghi = sleep or time.sleep
    dong_ho = monotonic or time.monotonic

    url = base_url.rstrip("/") + "/"
    if probe(url):
        return LauncherResult(ready=True, reason="already", detail=f"{url} đã sẵn sàng.")

    docker = tim("docker")
    if docker is None:
        return LauncherResult(
            ready=False,
            reason="docker_missing",
            detail="Không thấy 'docker' trên PATH. Cài Docker Desktop rồi mở lại cửa sổ này.",
        )

    thong_tin = chay([docker, "info", "--format", "{{.ServerVersion}}"], DOCKER_TIMEOUT_SEC)
    if thong_tin.returncode != 0:
        dau = (thong_tin.stderr or thong_tin.stdout or "").strip().splitlines()
        return LauncherResult(
            ready=False,
            reason="docker_down",
            detail=(
                "Docker Desktop chưa chạy"
                + (f" ({dau[0][:120]})" if dau else "")
                + ". Mở Docker Desktop, đợi biểu tượng chuyển xanh rồi chạy lại."
            ),
        )

    #: ``--pull never`` là có chủ đích: image đã ghim theo digest và nằm sẵn trên
    #: máy. Cho phép kéo về nghĩa là một lần bấm shortcut có thể thành 15 GB tải.
    len_ket_qua = chay(
        [docker, "compose", "-f", str(compose_file), "up", "-d", "--no-build", "--pull", "never"],
        COMPOSE_TIMEOUT_SEC,
    )
    if len_ket_qua.returncode != 0:
        return LauncherResult(
            ready=False,
            reason="compose_failed",
            detail=(
                "Không bật được container Duix: "
                + (len_ket_qua.stderr or len_ket_qua.stdout or "").strip()[:300]
            ),
        )

    bat_dau = dong_ho()
    while dong_ho() - bat_dau < timeout_sec:
        if probe(url):
            return LauncherResult(
                ready=True, reason="started", detail=f"Container đã lên, {url} sẵn sàng."
            )
        nghi(poll_interval_sec)

    return LauncherResult(
        ready=False,
        reason="timeout",
        detail=(
            f"Container đã bật nhưng {url} không trả lời sau {timeout_sec:.0f}s. "
            "Xem log: docker logs --tail 50 duix-avatar-gen-video"
        ),
    )
