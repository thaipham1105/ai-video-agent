"""Chọn bộ provider cho một lần chạy.

Quy tắc: mặc định của toàn hệ thống là ``mock``. Muốn có adapter thật phải nói
rõ ``--provider-mode real``, và ngay cả khi đó adapter vẫn tự chặn nếu gate của
nó chưa được duyệt.
"""

from __future__ import annotations

from ai_video_agent.config import Config
from ai_video_agent.domain.enums import ProviderMode
from ai_video_agent.domain.project import ProviderSelection
from ai_video_agent.errors import ConfigError
from ai_video_agent.providers.base import (
    AvatarProvider,
    BrollProvider,
    ProviderSet,
    TtsProvider,
)
from ai_video_agent.providers.duix import DuixAvatarProvider, MockDuixAvatarProvider
from ai_video_agent.providers.pricing import VIDEO_API_GENERIC, VIMAX_ORCHESTRATED
from ai_video_agent.providers.video_api import VideoApiBrollProvider
from ai_video_agent.providers.video_api.adapter import CallPolicy
from ai_video_agent.providers.vieneu import MockVieNeuTtsProvider, VieNeuTtsProvider
from ai_video_agent.providers.vimax import MockBrollProvider, ViMaxBrollProvider

KNOWN_TTS = frozenset({"vieneu"})
KNOWN_AVATAR = frozenset({"duix"})
KNOWN_BROLL = frozenset({"none", "vimax", "video_api"})


def _build_tts(name: str, mode: ProviderMode, config: Config) -> TtsProvider:
    if name not in KNOWN_TTS:
        msg = f"Provider TTS không hợp lệ: {name!r}. Hợp lệ: {sorted(KNOWN_TTS)}"
        raise ConfigError(msg)
    if mode is ProviderMode.MOCK:
        return MockVieNeuTtsProvider(sample_rate=config.vieneu_sample_rate)
    return VieNeuTtsProvider(
        device=config.vieneu_device,
        sample_rate=config.vieneu_sample_rate,
    )


def _build_avatar(name: str, mode: ProviderMode, config: Config) -> AvatarProvider:
    if name not in KNOWN_AVATAR:
        msg = f"Provider avatar không hợp lệ: {name!r}. Hợp lệ: {sorted(KNOWN_AVATAR)}"
        raise ConfigError(msg)
    if mode is ProviderMode.MOCK:
        return MockDuixAvatarProvider()
    # Duix nhận đường dẫn local THEO GÓC NHÌN CONTAINER, và ghi kết quả vào thư
    # mục dữ liệu của riêng nó. Cả hai đều lấy từ Config để adapter không phải
    # đoán, và để đổi bố cục volume chỉ cần sửa một chỗ.
    return DuixAvatarProvider(
        base_url=config.duix_base_url,
        timeout_sec=config.duix_timeout_sec,
        image_digest=config.duix_image_digest,
        path_map=((str(config.runtime_dir / "projects"), config.duix_inputs_mount),),
        result_dir_host=config.duix_data_dir,
    )


def _build_broll(name: str, mode: ProviderMode, config: Config) -> BrollProvider | None:
    if name not in KNOWN_BROLL:
        msg = f"Provider B-roll không hợp lệ: {name!r}. Hợp lệ: {sorted(KNOWN_BROLL)}"
        raise ConfigError(msg)
    if name == "none":
        return None
    if mode is ProviderMode.MOCK:
        price = VIMAX_ORCHESTRATED if name == "vimax" else VIDEO_API_GENERIC
        return MockBrollProvider(name=name, model=f"{name}-mock", price=price)
    if name == "vimax":
        return ViMaxBrollProvider()
    return VideoApiBrollProvider(
        provider_name=config.video_api_provider or "video-api",
        policy=CallPolicy(max_usd_per_run=config.video_api_max_usd_per_run),
    )


def build_provider_set(
    selection: ProviderSelection,
    *,
    mode: ProviderMode | None = None,
    config: Config | None = None,
) -> ProviderSet:
    """Dựng bộ provider theo lựa chọn của project.

    ``mode`` (từ dòng lệnh) được ưu tiên hơn ``selection.mode`` (lưu trong
    project.json) để người dùng lúc nào cũng ép được về mock.
    """
    cfg = config or Config.from_env()
    effective_mode = mode or selection.mode

    notes: list[str] = []
    if effective_mode is ProviderMode.MOCK:
        notes.append("Chế độ mock: không tải model, không dùng GPU, không gọi API.")

    return ProviderSet(
        tts=_build_tts(selection.tts, effective_mode, cfg),
        avatar=_build_avatar(selection.avatar, effective_mode, cfg),
        broll=_build_broll(selection.broll, effective_mode, cfg),
        notes=notes,
    )
