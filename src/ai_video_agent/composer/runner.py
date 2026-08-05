"""Thực thi bước ghép video.

Ở D01 chỉ có :class:`MockComposer`: nó **dựng lệnh FFmpeg thật** và ghi lệnh đó
vào ``render-manifest.json``, nhưng không chạy. Nhờ vậy chuỗi tham số được kiểm
thử và soi bằng mắt ngay từ bây giờ, trước khi máy có FFmpeg.

:class:`FfmpegComposer` là chỗ dành sẵn cho D04.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ai_video_agent import gate_is_open
from ai_video_agent.composer.ffmpeg import ComposeSpec, build_compose_command
from ai_video_agent.domain.enums import ProviderKind, ProviderMode
from ai_video_agent.errors import ComposeError, ConfigError, GateNotReachedError
from ai_video_agent.paths import assert_writable
from ai_video_agent.providers._placeholder import write_placeholder_video
from ai_video_agent.providers.base import ProviderInfo

GATE = "D04"


@dataclass(frozen=True)
class ComposeOutcome:
    """Kết quả bước ghép."""

    output: Path
    command: list[str] = field(default_factory=list)
    executed: bool = False
    is_placeholder: bool = True
    message: str = ""


class Composer(Protocol):
    """Bất cứ thứ gì biến chuỗi clip + audio + phụ đề thành một MP4."""

    def info(self) -> ProviderInfo: ...

    def compose(self, spec: ComposeSpec) -> ComposeOutcome: ...


class MockComposer:
    """Ghi file đánh dấu kèm đúng lệnh FFmpeg sẽ chạy ở D04."""

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="ffmpeg",
            kind=ProviderKind.COMPOSER,
            model="ffmpeg-mock",
            version="0.1.0",
            mode=ProviderMode.MOCK,
            billable=False,
            gate="D01",
        )

    def compose(self, spec: ComposeSpec) -> ComposeOutcome:
        command = build_compose_command(spec)
        write_placeholder_video(
            spec.output,
            {
                "provider": "ffmpeg",
                "mode": "mock",
                "width": spec.width,
                "height": spec.height,
                "fps": spec.fps,
                "subtitles": str(spec.subtitles) if spec.subtitles else None,
                "logo": str(spec.logo) if spec.logo else None,
                "draw_texts": [draw.text for draw in spec.draw_texts],
                "ffmpeg_command": command,
                "warning": "File giả. Lệnh FFmpeg ở trên chưa được chạy (mở ở D04).",
            },
        )
        return ComposeOutcome(
            output=spec.output,
            command=command,
            executed=False,
            is_placeholder=True,
            message="Mock: đã dựng lệnh FFmpeg nhưng chưa thực thi (mở ở D04).",
        )


class FfmpegComposer:
    """Chạy FFmpeg thật — mở từ Gate D04.

    Lệnh vẫn do :func:`build_compose_command` dựng, nên chuỗi tham số được kiểm
    thử tách rời với việc thực thi. Ở đây chỉ thêm phần chạy và bắt lỗi.
    """

    def __init__(self, *, ffmpeg_bin: str = "ffmpeg", timeout_sec: int = 3600) -> None:
        self._ffmpeg_bin = ffmpeg_bin
        self._timeout_sec = timeout_sec

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="ffmpeg",
            kind=ProviderKind.COMPOSER,
            model="ffmpeg",
            version=self._version(),
            mode=ProviderMode.REAL,
            billable=False,
            gate=GATE,
        )

    def _version(self) -> str:
        resolved = shutil.which(self._ffmpeg_bin)
        if resolved is None:
            return "not-installed"
        try:
            out = subprocess.run(  # noqa: S603 - đường dẫn đã giải, tham số cố định
                [resolved, "-version"], capture_output=True, text=True, timeout=20, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        first = (out.stdout or "").splitlines()
        return first[0].split(" Copyright")[0].strip() if first else "unknown"

    def compose(self, spec: ComposeSpec) -> ComposeOutcome:
        if not gate_is_open(GATE):
            raise GateNotReachedError(
                "Chạy FFmpeg thật để xuất MP4",
                GATE,
                hint="Dùng MockComposer cho tới khi D04 được duyệt.",
            )

        assert_writable(spec.output)
        resolved = shutil.which(self._ffmpeg_bin)
        if resolved is None:
            msg = (
                f"Không tìm thấy {self._ffmpeg_bin!r} trên PATH. "
                "Cài bằng: winget install --id Gyan.FFmpeg -e"
            )
            raise ConfigError(msg)

        command = build_compose_command(spec)
        command[0] = resolved
        spec.output.parent.mkdir(parents=True, exist_ok=True)

        try:
            completed = subprocess.run(  # noqa: S603 - argv do build_compose_command dựng
                command, capture_output=True, text=True, timeout=self._timeout_sec, check=False
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"FFmpeg quá {self._timeout_sec}s chưa xong khi ghép {spec.output.name}."
            raise ComposeError(msg) from exc
        except OSError as exc:
            msg = f"Không chạy được FFmpeg: {exc}"
            raise ComposeError(msg) from exc

        if completed.returncode != 0:
            tail = "\n".join((completed.stderr or "").strip().splitlines()[-15:])
            msg = f"FFmpeg lỗi (exit {completed.returncode}) khi ghép {spec.output.name}:\n{tail}"
            raise ComposeError(msg)

        if not spec.output.is_file() or spec.output.stat().st_size == 0:
            msg = f"FFmpeg báo thành công nhưng {spec.output} rỗng hoặc không tồn tại."
            raise ComposeError(msg)

        return ComposeOutcome(
            output=spec.output,
            command=command,
            executed=True,
            is_placeholder=False,
            message=f"FFmpeg xuất {spec.output.stat().st_size / 1024 / 1024:.2f} MB.",
        )
