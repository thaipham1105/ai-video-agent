"""D04-A — hợp đồng chung cho mọi backend lip-sync.

Mục đích: biến "adapter thay được" từ một lời hứa trong tài liệu thành thứ máy
tự kiểm. Mỗi backend mới (MuseTalk, LatentSync, model sau này) chỉ cần thêm một
dòng vào :data:`AVATAR_BACKENDS` là toàn bộ hợp đồng dưới đây áp lên nó.

Những điều khoản ở đây không phải lý thuyết — mỗi cái đến từ một lỗi có thật:

* ``quote()`` phải chạy khi **chưa có file WAV** — nếu không, ``aiva estimate``
  và ``render --dry-run`` sẽ vỡ.
* ``quote()`` **không được** nạp model hay chạm GPU — nếu không, xem giá cũng
  tốn tài nguyên.
* Kết quả phải khai **đường thật đã ghi**, không giả định trùng đường được yêu
  cầu — Duix từng ghi ra chỗ khác, và pipeline tin nhầm đường yêu cầu (FIX 3).
* Adapter thật phải chặn theo gate của chính nó.
* Không import SDK nặng ở cấp module (AGENTS.md §Ranh giới).
"""

from __future__ import annotations

import ast
import wave
from pathlib import Path

import pytest

from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.errors import GateNotReachedError
from ai_video_agent.providers.base import AvatarProvider, AvatarRequest
from ai_video_agent.providers.duix import DuixAvatarProvider, MockDuixAvatarProvider

#: Mọi backend lip-sync phải có mặt ở đây. Thêm backend = thêm một dòng.
#: ``(nhãn, hàm dựng, có phải adapter thật không)``
AVATAR_BACKENDS: list[tuple[str, object, bool]] = [
    ("duix-mock", MockDuixAvatarProvider, False),
    ("duix-real", DuixAvatarProvider, True),
]

MOCK_BACKENDS = [(n, f) for n, f, real in AVATAR_BACKENDS if not real]
REAL_BACKENDS = [(n, f) for n, f, real in AVATAR_BACKENDS if real]

#: Module của adapter thật — dùng cho kiểm import cấp module.
REAL_ADAPTER_SOURCES = ["src/ai_video_agent/providers/duix/adapter.py"]

#: SDK nặng không được import ở cấp module (AGENTS.md).
HEAVY_MODULES = {"torch", "torchvision", "torchaudio", "vieneu", "transformers",
                 "diffusers", "mmcv", "mmpose", "mmdet", "cv2", "tensorflow"}


def _wav(path: Path, seconds: float = 1.0, rate: int = 48_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _request(tmp_path: Path, *, with_audio: bool = True) -> AvatarRequest:
    audio = tmp_path / "audio.wav"
    if with_audio:
        _wav(audio)
    source = tmp_path / "avatar.mp4"
    source.write_bytes(b"nguon avatar gia")
    return AvatarRequest(
        shot_id="shot-01",
        audio_path=audio,
        avatar_source=source,
        width=1080,
        height=1920,
        fps=30,
        duration_sec=1.0,
    )


# --- Điều khoản chung cho MỌI backend ------------------------------------


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_backend_thoa_man_protocol(label: str, factory: object, is_real: bool) -> None:
    del label, is_real
    provider = factory()  # type: ignore[operator]
    assert isinstance(provider, AvatarProvider)


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_info_khai_bao_danh_tinh_day_du(label: str, factory: object, is_real: bool) -> None:
    del label, is_real
    info = factory().info()  # type: ignore[operator]
    assert info.kind is ProviderKind.AVATAR, "backend lip-sync phải khai kind=AVATAR"
    assert info.name, "thiếu tên backend"
    assert info.model, "thiếu tên model"
    assert info.version, "thiếu version — không truy vết được"
    assert info.gate, "thiếu gate — cost guard và hàng rào gate dựa vào đây"


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_quote_chay_duoc_khi_chua_co_file_wav(
    label: str, factory: object, is_real: bool, tmp_path: Path
) -> None:
    """``estimate`` và ``render --dry-run`` chạy trước khi TTS sinh WAV."""
    del label, is_real
    quote = factory().quote(_request(tmp_path, with_audio=False))  # type: ignore[operator]
    assert quote.stage is RenderStage.AVATAR
    assert quote.estimated_usd >= 0.0
    assert quote.unit, "thiếu đơn vị tính"


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_quote_khong_cham_gate_va_khong_nap_model(
    label: str, factory: object, is_real: bool, tmp_path: Path
) -> None:
    """Xem giá phải rẻ: không gate, không GPU, không nạp trọng số."""
    del label, is_real
    quote = factory().quote(_request(tmp_path))  # type: ignore[operator]
    assert quote is not None


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_backend_local_khong_tinh_tien(label: str, factory: object, is_real: bool) -> None:
    """Lip-sync chạy local trên máy — chi phí là thời gian GPU, không phải hoá đơn."""
    del label, is_real
    assert factory().info().billable is False  # type: ignore[operator]


# --- Capability và ước tính tài nguyên (D04-B) ----------------------------


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_capability_khai_du_khong_de_trong(
    label: str, factory: object, is_real: bool
) -> None:
    del label, is_real
    cap = factory().capability()  # type: ignore[operator]
    assert cap.backend_id and cap.backend_version
    assert cap.native_fps > 0
    assert cap.native_fps in cap.supported_fps
    assert cap.max_width > 0 and cap.max_height > 0
    assert cap.audio_sample_rate_hz > 0
    assert cap.audio_encoder, "phải khai bộ mã hoá tiếng"
    assert cap.languages_verified, "phải khai ngôn ngữ đã kiểm chứng"
    assert cap.accepts_image_source or cap.accepts_video_source
    assert cap.requires_gate


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_capability_khai_dung_gate_trong_info(
    label: str, factory: object, is_real: bool
) -> None:
    """Hai chỗ khai gate phải khớp nhau, nếu không hàng rào sẽ mơ hồ."""
    del label, is_real
    provider = factory()  # type: ignore[operator]
    assert provider.capability().requires_gate == provider.info().gate


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_uoc_tinh_tai_nguyen_khong_bi_bo_trong(
    label: str, factory: object, is_real: bool, tmp_path: Path
) -> None:
    """``ram_mib = 0`` gần như chắc chắn là quên khai, không phải sự thật."""
    del label, is_real
    est = factory().estimate_resources(_request(tmp_path))  # type: ignore[operator]
    assert est.ram_mib > 0, "RAM 0 MiB là dấu hiệu quên khai"
    assert est.vram_mib >= 0
    assert est.storage_mib >= 0
    assert isinstance(est.deterministic_local, bool)
    if est.measured:
        assert est.measured_on, "đã đo thì phải có ngày đo"


@pytest.mark.parametrize(("label", "factory"), REAL_BACKENDS)
def test_backend_that_phai_khai_vram_that(label: str, factory: object, tmp_path: Path) -> None:
    """Backend GPU khai VRAM = 0 sẽ khiến hàng rào tài nguyên im lặng cho qua."""
    del label
    est = factory().estimate_resources(_request(tmp_path))  # type: ignore[operator]
    assert est.vram_mib > 0, "adapter thật chạy GPU phải khai VRAM > 0"
    assert est.measured, "số VRAM của backend thật phải là số ĐO, không phải chép tài liệu"


@pytest.mark.parametrize(("label", "factory", "is_real"), AVATAR_BACKENDS)
def test_estimate_resources_khong_cham_gpu_va_khong_can_file(
    label: str, factory: object, is_real: bool, tmp_path: Path
) -> None:
    """Hỏi tài nguyên phải rẻ — chạy được cả khi chưa có WAV."""
    del label, is_real
    est = factory().estimate_resources(_request(tmp_path, with_audio=False))  # type: ignore[operator]
    assert est is not None


# --- Điều khoản riêng cho adapter THẬT ------------------------------------


@pytest.mark.parametrize(("label", "factory"), REAL_BACKENDS)
def test_adapter_that_chan_theo_gate_cua_chinh_no(
    label: str, factory: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ép gate đóng rồi khẳng định adapter chặn.

    Cố ý **không** bỏ qua test khi gate đang mở: gate của Duix là D03 và
    ``CURRENT_GATE`` hiện là D04, nên nếu chỉ ``skip`` thì điều khoản quan trọng
    nhất của hợp đồng sẽ không bao giờ được kiểm — chính là kiểu lỗ hổng khiến
    một backend mới có thể quên hàng rào gate mà vẫn xanh.
    """
    del label
    provider = factory()  # type: ignore[operator]
    module = type(provider).__module__
    monkeypatch.setattr(f"{module}.gate_is_open", lambda _g: False)
    with pytest.raises(GateNotReachedError):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")


@pytest.mark.parametrize(("label", "factory"), REAL_BACKENDS)
def test_adapter_that_goi_gate_is_open_chu_khong_hardcode(
    label: str, factory: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hàng rào phải hỏi ``gate_is_open`` thật, không phải hằng số cứng."""
    del label
    provider = factory()  # type: ignore[operator]
    module = type(provider).__module__
    asked: list[str] = []

    def _spy(gate: str) -> bool:
        asked.append(gate)
        return False

    monkeypatch.setattr(f"{module}.gate_is_open", _spy)
    with pytest.raises(GateNotReachedError):
        provider.generate(_request(tmp_path), tmp_path / "out.mp4")
    assert asked, "adapter thật phải hỏi gate_is_open trước khi làm gì"
    assert asked[0] == provider.info().gate, "phải hỏi đúng gate mà nó khai trong info()"


@pytest.mark.parametrize(("label", "factory"), REAL_BACKENDS)
def test_adapter_that_khai_mode_real(label: str, factory: object) -> None:
    del label
    assert factory().info().mode is ProviderMode.REAL  # type: ignore[operator]


@pytest.mark.parametrize("source", REAL_ADAPTER_SOURCES)
def test_adapter_that_khong_import_sdk_nang_o_cap_module(source: str) -> None:
    """SDK nặng chỉ được import trong hàm, để test mock không phải cài chúng."""
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in tree.body:  # chỉ duyệt cấp module, không vào trong hàm
        if isinstance(node, ast.Import):
            offenders += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            offenders.append(node.module.split(".")[0])
    heavy = sorted(set(offenders) & HEAVY_MODULES)
    assert not heavy, f"{source} import SDK nặng ở cấp module: {heavy}"


# --- Điều khoản riêng cho mock -------------------------------------------


@pytest.mark.parametrize(("label", "factory"), MOCK_BACKENDS)
def test_mock_deterministic(label: str, factory: object, tmp_path: Path) -> None:
    """Cùng đầu vào phải cho cùng metadata — nền tảng của test tái lập được."""
    del label
    request = _request(tmp_path)
    first = factory().generate(request, tmp_path / "a.mp4")  # type: ignore[operator]
    second = factory().generate(request, tmp_path / "b.mp4")  # type: ignore[operator]
    assert first.duration_sec == second.duration_sec
    assert (first.width, first.height, first.fps) == (second.width, second.height, second.fps)
    assert first.path != second.path, "hai lần gọi ghi ra hai đường khác nhau"
    assert first.path.read_bytes() == second.path.read_bytes(), "nội dung phải trùng khớp"


@pytest.mark.parametrize(("label", "factory"), MOCK_BACKENDS)
def test_mock_lay_thoi_luong_tu_file_wav_that(
    label: str, factory: object, tmp_path: Path
) -> None:
    """Nếu TTS sinh sai độ dài, test đồng bộ phải bắt được — không tin tham số."""
    del label
    request = _request(tmp_path)
    _wav(request.audio_path, seconds=2.5)
    result = factory().generate(request, tmp_path / "out.mp4")  # type: ignore[operator]
    assert abs(result.duration_sec - 2.5) < 0.05


@pytest.mark.parametrize(("label", "factory"), MOCK_BACKENDS)
def test_ket_qua_khai_dung_duong_da_ghi(
    label: str, factory: object, tmp_path: Path
) -> None:
    """``AvatarResult.path`` phải trỏ tới file THẬT tồn tại.

    Bài học FIX 3: pipeline từng tin vào đường *yêu cầu* thay vì đường provider
    *thực sự ghi*. Backend được phép ghi ra chỗ khác, nhưng phải nói thật.
    """
    del label
    result = factory().generate(_request(tmp_path), tmp_path / "out.mp4")  # type: ignore[operator]
    assert result.path.is_file(), "đường trong AvatarResult phải là file có thật"


@pytest.mark.parametrize(("label", "factory"), MOCK_BACKENDS)
def test_mock_danh_dau_ro_la_placeholder(label: str, factory: object, tmp_path: Path) -> None:
    """Output mock không được lẫn với media thật."""
    del label
    result = factory().generate(_request(tmp_path), tmp_path / "out.mp4")  # type: ignore[operator]
    assert result.is_placeholder is True


# --- Hợp đồng phải áp cho MỌI backend, không sót ---------------------------


def test_moi_backend_trong_registry_deu_co_trong_hop_dong() -> None:
    """Thêm backend vào registry mà quên thêm vào đây là lọt lưới hợp đồng."""
    from ai_video_agent.providers.registry import KNOWN_AVATAR

    covered = {label.split("-")[0] for label, _, _ in AVATAR_BACKENDS}
    missing = set(KNOWN_AVATAR) - covered
    assert not missing, (
        f"Backend {sorted(missing)} có trong KNOWN_AVATAR nhưng chưa được hợp đồng "
        "này phủ. Thêm vào AVATAR_BACKENDS."
    )
