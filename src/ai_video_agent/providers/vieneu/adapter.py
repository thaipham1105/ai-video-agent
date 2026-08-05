"""Adapter VieNeu-TTS thật — mở từ Gate D02.

Bằng chứng tích hợp (D00 §4.2, xác nhận lại ở D02): VieNeu-TTS là **SDK Python
thuần**. Bản v3 Turbo chạy ONNX Runtime int8 trên CPU ở 48 kHz và **không bao
giờ import torch**, nên không tranh GPU với Duix (brief §D02.1).

Ba lựa chọn được ghim cứng để giữ đúng chiến lược đó::

    backend="onnx"      # không bao giờ rơi sang nhánh PyTorch
    device="cpu"        # kể cả khi máy có GPU rảnh
    precision="int8"    # nhánh onnx_int8/ trên HF, ~158 MB thay vì 490 MB fp32

SDK được import **bên trong hàm** để đường đi mock chạy được mà không cần cài
extra ``tts`` (xem AGENTS.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_video_agent import gate_is_open
from ai_video_agent.composer.audio import inspect_wav
from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.errors import (
    ConfigError,
    ConsentMissingError,
    GateNotReachedError,
    ProviderError,
)
from ai_video_agent.paths import assert_writable
from ai_video_agent.providers.base import (
    CostQuote,
    ProviderInfo,
    TtsRequest,
    TtsResult,
)
from ai_video_agent.providers.pricing import VIENEU_LOCAL

GATE = "D02"

#: v3 Turbo chỉ xuất 48 kHz. Yêu cầu khác đi là cấu hình sai, không phải chuyện im lặng bỏ qua.
NATIVE_SAMPLE_RATE = 48_000

#: Repo model và codec trên Hugging Face (đọc từ mã nguồn vieneu 3.2.4).
MODEL_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
CODEC_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"

#: Giọng dựng sẵn đi kèm trong wheel, không phải tải thêm.
DEFAULT_VOICE = "Minh Đức"

# ---------------------------------------------------------------------------
# CẤU HÌNH GOLDEN — đã được PO nghiệm thu 8/10 ở Gate D02 (2026-08-04).
#
# Đây là bộ tham số đã tạo ra `giong-toi-A-mo-dau.wav`, bản PO chọn chính thức.
# PO ưu tiên ĐỘ GIỐNG GIỌNG hơn độ tự nhiên: N1 (bản thu voice-v2) được chấm là
# tự nhiên nhất nhưng KHÔNG được chọn. fp32 và voice-v2 cũng không được chọn.
#
# Các giá trị dưới đây trùng với mặc định của vieneu 3.2.4, nhưng vẫn được
# truyền TƯỜNG MINH: mặc định của upstream có thể đổi ở bản sau, và khi đó giọng
# sẽ đổi thầm lặng. Ghim ở đây thì `tests/test_d02_golden_config.py` canh được.
#
# Đổi bất kỳ hằng số nào bên dưới = đổi giọng đầu ra. Phải có PO duyệt lại.
# ---------------------------------------------------------------------------

GOLDEN_PRECISION = "int8"
GOLDEN_STYLE = "tu_nhien"
GOLDEN_DENOISE = True
GOLDEN_USE_REF_CODES = True
GOLDEN_TEMPERATURE = 0.8
GOLDEN_TOP_K = 25
GOLDEN_TOP_P = 0.95
GOLDEN_REPETITION_PENALTY = 1.2

#: Model có thể trả về đỉnh > 1,0 (đã quan sát 1,046 ở biến thể N2). Ghi thẳng
#: ra PCM 16-bit sẽ bị cắt phẳng và nghe gắt. Vượt ngưỡng thì hạ về mức an toàn.
MAX_OUTPUT_PEAK = 1.0
SAFE_OUTPUT_PEAK = 0.97


def limit_peak(
    audio: Any,
    *,
    max_peak: float = MAX_OUTPUT_PEAK,
    safe_peak: float = SAFE_OUTPUT_PEAK,
) -> Any:
    """Hạ biên độ nếu vượt thang, để ghi PCM 16-bit không bị cắt phẳng.

    **Không đụng gì** khi đỉnh đã dưới ngưỡng — golden reference có đỉnh 0,974
    nên hàm này không hề làm nó đổi. Nó chỉ là lưới an toàn cho trường hợp model
    trả về đỉnh > 1,0 (đã quan sát thật ở biến thể N2: 1,046 → 7 mẫu bị cắt).
    """
    peak = float(abs(audio).max()) if len(audio) else 0.0
    if peak <= max_peak or peak == 0.0:
        return audio
    return audio * (safe_peak / peak)


class VieNeuTtsProvider:
    """Gọi SDK ``vieneu`` in-process trên CPU/ONNX."""

    def __init__(
        self,
        *,
        device: str = "cpu",
        sample_rate: int = NATIVE_SAMPLE_RATE,
        model: str = MODEL_REPO,
        precision: str = GOLDEN_PRECISION,
        voice: str = DEFAULT_VOICE,
        style: str = GOLDEN_STYLE,
        denoise: bool = GOLDEN_DENOISE,
        use_ref_codes: bool = GOLDEN_USE_REF_CODES,
        temperature: float = GOLDEN_TEMPERATURE,
        top_k: int = GOLDEN_TOP_K,
        top_p: float = GOLDEN_TOP_P,
        repetition_penalty: float = GOLDEN_REPETITION_PENALTY,
        threads: int = 0,
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._model = model
        self._precision = precision
        self._voice = voice
        self._style = style
        self._denoise = denoise
        self._use_ref_codes = use_ref_codes
        self._temperature = temperature
        self._top_k = top_k
        self._top_p = top_p
        self._repetition_penalty = repetition_penalty
        self._threads = threads
        #: Engine nặng, dựng lười và dùng lại cho mọi shot trong một lần render.
        self._engine: Any | None = None

    # ----- danh tính và báo giá -----------------------------------------------

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="vieneu",
            kind=ProviderKind.TTS,
            model=f"{self._model}/{self._precision}",
            version=self._package_version(),
            mode=ProviderMode.REAL,
            billable=False,
            gate=GATE,
        )

    def quote(self, request: TtsRequest) -> CostQuote:
        """Báo giá chạy được ở mọi gate — chỉ tính toán, không nạp model."""
        return CostQuote(
            stage=RenderStage.TTS,
            provider="vieneu",
            model=f"{self._model}/{self._precision}",
            unit=VIENEU_LOCAL.unit,
            units=float(len(request.text_vi)),
            unit_price_usd=VIENEU_LOCAL.unit_price_usd,
            estimated_usd=0.0,
            billable=False,
            assumption=VIENEU_LOCAL.assumption,
        )

    @staticmethod
    def _package_version() -> str:
        try:
            from importlib.metadata import version

            return version("vieneu")
        except Exception:  # noqa: BLE001 - thiếu gói thì báo 'unknown', không làm sập info()
            return "unknown"

    # ----- nạp engine ----------------------------------------------------------

    def engine(self) -> Any:
        """Trả về engine đã nạp; lần gọi đầu sẽ tải model (~312 MB) về cache HF."""
        self._assert_gate_open()
        if self._engine is None:
            try:
                from vieneu import Vieneu
            except ImportError as exc:
                msg = (
                    "Chưa cài VieNeu-TTS. Chạy: uv sync --extra tts\n"
                    "(extra 'tts' được để riêng vì nó kéo theo 63 gói, ~250 MB.)"
                )
                raise ConfigError(msg) from exc

            try:
                self._engine = Vieneu(
                    mode="v3turbo",
                    backend="onnx",
                    device=self._device,
                    precision=self._precision,
                    backbone_repo=self._model,
                    threads=self._threads,
                )
            except Exception as exc:
                msg = f"Không nạp được VieNeu-TTS ({self._model}/{self._precision}): {exc}"
                raise ProviderError(msg) from exc
        return self._engine

    def preset_voices(self) -> list[str]:
        """Tên các giọng dựng sẵn. Đọc từ engine đã nạp."""
        voices = getattr(self.engine(), "_preset_voices", {})
        return sorted(voices)

    # ----- sinh giọng ----------------------------------------------------------

    def synthesize(self, request: TtsRequest, out_path: Path) -> TtsResult:
        self._assert_gate_open()
        self._assert_sample_rate(request)
        ref_audio = self._resolve_ref_audio(request)

        assert_writable(out_path)
        engine = self.engine()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            audio = engine.infer(
                request.text_vi,
                ref_audio=str(ref_audio) if ref_audio is not None else None,
                voice=None if ref_audio is not None else (request.voice or self._voice),
                style=self._style,
                denoise=self._denoise,
                use_ref_codes=self._use_ref_codes,
                temperature=self._temperature,
                top_k=self._top_k,
                top_p=self._top_p,
                repetition_penalty=self._repetition_penalty,
            )
            engine.save(limit_peak(audio), str(out_path))
        except Exception as exc:
            msg = f"VieNeu-TTS thất bại ở shot {request.shot_id}: {exc}"
            raise ProviderError(msg) from exc

        report = inspect_wav(out_path, expected_sample_rate=NATIVE_SAMPLE_RATE)
        if not report.ok:
            detail = "; ".join(report.problems)
            msg = f"WAV sinh ra không đạt ở shot {request.shot_id}: {detail}"
            raise ProviderError(msg)

        return TtsResult(
            path=out_path,
            duration_sec=report.duration_sec,
            sample_rate=report.sample_rate,
            channels=report.channels,
            is_placeholder=False,
            actual_cost_usd=0.0,
        )

    # ----- hàng rào ------------------------------------------------------------

    @staticmethod
    def _assert_gate_open() -> None:
        if not gate_is_open(GATE):
            raise GateNotReachedError(
                "VieNeu-TTS thật (tải model + sinh giọng)",
                GATE,
                hint="Dùng --provider-mode mock cho tới khi D02 được duyệt.",
            )

    @staticmethod
    def _assert_sample_rate(request: TtsRequest) -> None:
        if request.sample_rate and request.sample_rate != NATIVE_SAMPLE_RATE:
            msg = (
                f"VieNeu v3 Turbo chỉ xuất {NATIVE_SAMPLE_RATE} Hz nhưng được yêu cầu "
                f"{request.sample_rate} Hz. Sửa AIVA_VIENEU_SAMPLE_RATE cho khớp."
            )
            raise ConfigError(msg)

    @staticmethod
    def _resolve_ref_audio(request: TtsRequest) -> Path | None:
        """Không bao giờ nhân bản giọng từ mẫu không tồn tại hoặc chưa khai báo (brief §4)."""
        if request.ref_audio is None:
            return None
        ref = Path(request.ref_audio)
        if not ref.is_file():
            msg = (
                f"Mẫu giọng {ref} không tồn tại. Mẫu giọng phải nằm trong thư mục runtime "
                "và được khai báo consent=granted trong asset-manifest.json."
            )
            raise ConsentMissingError(msg)
        return ref
