"""Kiểm tra vận hành ngay trước một lượt render thật bằng Duix.

Khác ``cli/doctor.py``: doctor trả lời "máy này cài đủ chưa" và chạy được bất cứ
lúc nào. Module này trả lời câu hẹp hơn và chỉ đúng **tại thời điểm sắp render**:
*bây giờ* bấm nút thì có chạy được không.

Vì sao cần: D05-B cho thấy ba cách hỏng đều chỉ lộ ra sau khi người dùng đã chờ —
container chưa bật thì lỗi kết nối rơi ra giữa chừng, thiếu ``ffprobe`` thì hỏng
ở bước đo, VRAM bị chiếm thì preflight của pipeline mới chặn. Hỏi trước hết vài
giây; hỏng giữa chừng tốn cả lượt chạy.

**Chỉ hỏi, không sửa.** Không tự ``docker compose up``, không tự đóng tiến trình
đang chiếm GPU, không tự cài gì. Mỗi lỗi kèm đúng lệnh người vận hành cần gõ.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from ai_video_agent.cli.doctor import CheckResult, Status
from ai_video_agent.providers import resource_budget
from ai_video_agent.providers.duix.capability import DUIX_RESOURCES

if TYPE_CHECKING:
    from ai_video_agent.config import Config

COMPOSE_UP = "docker compose -f deploy/duix/docker-compose.yml up -d"

#: Đủ để phân biệt "chưa bật" với "đang bận": container bận vẫn trả lời HTTP.
#: Đây là kiểm tra trước khi chạy, không phải health check dài hơi.
ENDPOINT_TIMEOUT_SEC = 5.0
DOCKER_TIMEOUT_SEC = 20.0


def _check_ffprobe(cfg: Config) -> CheckResult:
    """``ffprobe`` phải có: adapter Duix đo fps nguồn **trước khi** gửi job."""
    if shutil.which(cfg.ffprobe_bin) is not None:
        return CheckResult("ffprobe", Status.PASS, f"{cfg.ffprobe_bin} có trên PATH")
    return CheckResult(
        "ffprobe",
        Status.FAIL,
        f"Không thấy {cfg.ffprobe_bin!r} trên PATH. Duix cần nó để đo fps nguồn "
        "và fps đầu ra. Cài FFmpeg rồi mở lại terminal, hoặc khai AIVA_FFPROBE_BIN.",
    )


def _check_docker() -> CheckResult:
    """Docker daemon phải đang chạy — Duix sống trong container."""
    binary = shutil.which("docker")
    if binary is None:
        return CheckResult(
            "docker",
            Status.FAIL,
            "Không thấy 'docker' trên PATH. Cài Docker Desktop rồi mở lại terminal.",
        )
    try:
        completed = subprocess.run(  # noqa: S603 - đường dẫn do shutil.which giải, tham số cố định
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=DOCKER_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return CheckResult("docker", Status.FAIL, "Gọi 'docker info' không xong. Docker còn sống?")
    if completed.returncode != 0:
        chi_tiet = (completed.stderr or completed.stdout or "").strip().splitlines()
        return CheckResult(
            "docker",
            Status.FAIL,
            "Docker daemon chưa chạy"
            + (f" ({chi_tiet[0][:120]})" if chi_tiet else "")
            + ". Mở Docker Desktop rồi chạy lại.",
        )
    return CheckResult("docker", Status.PASS, f"daemon {completed.stdout.strip()}")


def _check_duix_endpoint(cfg: Config) -> CheckResult:
    """Endpoint Duix phải trả lời.

    **Mã HTTP nào cũng tính là sống**, kể cả 404: ``/`` không phải route của
    Duix, nên 404 nghĩa là server đã lên và đang nghe. Chỉ khi nối không được
    mới là chưa bật.
    """
    url = cfg.duix_base_url.rstrip("/") + "/"
    try:
        with urllib.request.urlopen(url, timeout=ENDPOINT_TIMEOUT_SEC) as resp:  # noqa: S310
            return CheckResult("duix", Status.PASS, f"{url} trả HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        return CheckResult("duix", Status.PASS, f"{url} trả HTTP {exc.code} — server đang nghe")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return CheckResult(
            "duix",
            Status.FAIL,
            f"Không gọi được Duix tại {url} ({exc}). Container chưa chạy? Bật bằng:\n"
            f"    {COMPOSE_UP}",
        )


def _check_vram(cfg: Config) -> CheckResult:
    """Đối chiếu **sức chứa** của card với mức Duix cần.

    ``DUIX_RESOURCES.vram_mib`` là đỉnh của *cả card* đo lúc render — đã gồm nền
    desktop và phần container giữ sẵn. So nó với VRAM *trống* là trừ hai lần
    cùng một phần bộ nhớ: máy render xong ở D05-B (đỉnh 11.716 / card 12.282)
    vẫn bị chặn vì lúc kiểm chỉ còn trống 7.651.

    Nên: card không đủ **chỗ** mới là ``FAIL``; card đủ chỗ mà đang bị chiếm là
    ``WARN`` — người vận hành đóng app hay restart container là xong, còn chặn
    thẳng thì khoá luôn cả máy chạy được.

    Không đo được thì nói là không đo được — ``INFO``. Đoán một mặc định sẽ chặn
    nhầm máy tốt hoặc để lọt máy thiếu.
    """
    budget = resource_budget.ResourceBudget.detect(cfg)
    can = DUIX_RESOURCES.vram_mib
    khai_bao = cfg.vram_budget_mib is not None
    if budget.vram_mib is None:
        return CheckResult(
            "vram",
            Status.INFO,
            f"{resource_budget.UNVERIFIED} — Duix cần {can} MiB. "
            "Khai AIVA_VRAM_BUDGET_MIB nếu muốn chặn theo ngưỡng.",
        )
    nhan = "khai AIVA_VRAM_BUDGET_MIB" if khai_bao else "card"
    if budget.vram_mib < can:
        return CheckResult(
            "vram",
            Status.FAIL,
            f"{nhan} {budget.vram_mib} MiB, Duix cần {can} MiB — không đủ chỗ."
            + ("" if khai_bao else " Card này không chạy nổi Duix ở độ phân giải hiện tại."),
        )
    if budget.vram_free_mib is not None and budget.vram_free_mib < can:
        return CheckResult(
            "vram",
            Status.WARN,
            f"card {budget.vram_mib} MiB (đủ), nhưng chỉ còn trống "
            f"{budget.vram_free_mib} MiB / đỉnh đã đo {can} MiB. Vẫn chạy được vì "
            "phần lớn chỗ đó là nền desktop và model container đang giữ. Gặp OOM thì:\n"
            "    docker compose -f deploy/duix/docker-compose.yml restart",
        )
    return CheckResult("vram", Status.PASS, f"{nhan} {budget.vram_mib} MiB / cần {can} MiB")


def check_duix_ready(config: Config) -> list[CheckResult]:
    """Bốn câu hỏi, theo thứ tự từ rẻ tới đắt.

    Rẻ trước để lỗi thường gặp nhất (quên bật container, thiếu ffprobe) lộ ra
    ngay, không phải đợi hết mọi phép đo.
    """
    return [
        _check_ffprobe(config),
        _check_docker(),
        _check_duix_endpoint(config),
        _check_vram(config),
    ]


def blocking(results: list[CheckResult]) -> list[CheckResult]:
    """Chỉ ``FAIL`` mới chặn. ``WARN``/``INFO`` là thông tin, không phải cổng."""
    return [r for r in results if r.status is Status.FAIL]


__all__ = ["COMPOSE_UP", "CheckResult", "Status", "blocking", "check_duix_ready"]
