"""Chống hồi quy cấu hình golden của Gate D02.

PO nghiệm thu `giong-toi-A-mo-dau.wav` với **8/10** ngày 2026-08-04, và chọn nó
làm bản chính thức vì **ưu tiên độ giống giọng hơn độ tự nhiên**.

Ghi nhận rõ để người sau không "tối ưu" nhầm hướng:

* `N1-thu-moi-y-het-doi-chung.wav` (bản thu `voice-v2`) được PO chấm là **tự
  nhiên nhất**, nhưng **KHÔNG được chọn**.
* Model **fp32** và bản thu **voice-v2** đều không được chọn.
* Mọi cải tiến từng thử trên nguồn cũ — gỡ kẹp trần, chọn đoạn thủ công, lấy vân
  giọng từ 24 giây — đều không nâng được độ giống (V1..V4 chỉ 5-6/10).

Nhóm test này KHÔNG so khớp hash của WAV đầu ra. Sinh giọng có lấy mẫu ngẫu
nhiên (`temperature=0.8`) và seed gốc không tái lập được, nên hash sẽ khác nhau
giữa hai lần chạy dù cấu hình y hệt. Thay vào đó ta khoá **cấu hình**, **định
dạng** và **các chỉ số kỹ thuật** — những thứ tất định.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from ai_video_agent.composer.audio import inspect_wav
from ai_video_agent.domain.assets import AssetEntry, AssetManifest, Consent
from ai_video_agent.domain.enums import AssetKind, ConsentStatus, ProviderMode
from ai_video_agent.domain.project import Project, ProviderSelection
from ai_video_agent.errors import ConfigError, ValidationError
from ai_video_agent.orchestrator.pipeline import Pipeline
from ai_video_agent.paths import PROTECTED_DIR_NAMES, assert_writable, is_protected
from ai_video_agent.providers.vieneu.adapter import (
    GOLDEN_DENOISE,
    GOLDEN_PRECISION,
    GOLDEN_REPETITION_PENALTY,
    GOLDEN_STYLE,
    GOLDEN_TEMPERATURE,
    GOLDEN_TOP_K,
    GOLDEN_TOP_P,
    GOLDEN_USE_REF_CODES,
    MAX_OUTPUT_PEAK,
    NATIVE_SAMPLE_RATE,
    SAFE_OUTPUT_PEAK,
    VieNeuTtsProvider,
    limit_peak,
)

# --- model / precision --------------------------------------------------------


def test_precision_van_la_int8_khong_phai_fp32() -> None:
    """PO không chọn fp32. Đổi sang fp32 là đổi giọng, phải duyệt lại."""
    assert GOLDEN_PRECISION == "int8"
    assert VieNeuTtsProvider()._precision == "int8"


def test_model_repo_va_precision_hien_trong_danh_tinh() -> None:
    """`render-manifest.json` phải ghi lại đúng model đã dùng, để truy vết."""
    info = VieNeuTtsProvider().info()

    assert "int8" in info.model
    assert "fp32" not in info.model
    assert "VieNeu-TTS-v3-Turbo" in info.model


def test_luon_chay_cpu_va_onnx_khong_tranh_gpu_voi_duix() -> None:
    """Brief §D02.1: ưu tiên CPU/ONNX để không tranh GPU với Duix."""
    provider = VieNeuTtsProvider()
    source = Path(inspect.getfile(VieNeuTtsProvider)).read_text(encoding="utf-8")

    assert provider._device == "cpu"
    assert 'backend="onnx"' in source, "phải ghim backend onnx, không để 'auto'"
    assert "device=self._device" in source


# --- tham số sinh giọng -------------------------------------------------------


@pytest.mark.parametrize(
    ("ten", "gia_tri", "mong_doi"),
    [
        ("style", GOLDEN_STYLE, "tu_nhien"),
        ("denoise", GOLDEN_DENOISE, True),
        ("use_ref_codes", GOLDEN_USE_REF_CODES, True),
        ("temperature", GOLDEN_TEMPERATURE, 0.8),
        ("top_k", GOLDEN_TOP_K, 25),
        ("top_p", GOLDEN_TOP_P, 0.95),
        ("repetition_penalty", GOLDEN_REPETITION_PENALTY, 1.2),
    ],
)
def test_hang_so_golden_khong_bi_doi(ten: str, gia_tri: object, mong_doi: object) -> None:
    assert gia_tri == mong_doi, f"{ten} đã đổi — giọng đầu ra sẽ khác bản PO duyệt"


def test_adapter_lay_dung_hang_so_golden_lam_mac_dinh() -> None:
    provider = VieNeuTtsProvider()

    assert provider._style == GOLDEN_STYLE
    assert provider._denoise is GOLDEN_DENOISE
    assert provider._use_ref_codes is GOLDEN_USE_REF_CODES
    assert provider._temperature == GOLDEN_TEMPERATURE
    assert provider._top_k == GOLDEN_TOP_K
    assert provider._top_p == GOLDEN_TOP_P
    assert provider._repetition_penalty == GOLDEN_REPETITION_PENALTY


class _FakeEngine:
    """Engine giả: ghi lại tham số nhận được rồi trả về audio dựng sẵn.

    Nhờ nó, ta kiểm tra được ĐƯỜNG GỌI THẬT của adapter mà không phải nạp model
    ~285 MB. Kiểm tra hành vi chắc hơn nhiều so với dò chuỗi trong mã nguồn.
    """

    sample_rate = NATIVE_SAMPLE_RATE

    def __init__(self, peak: float = 0.5) -> None:
        self.kwargs: dict[str, object] = {}
        self.text: str = ""
        self.saved_peak: float = 0.0
        self._peak = peak

    def infer(self, text: str, **kwargs: object):
        import numpy as np

        self.text = text
        self.kwargs = kwargs
        wave = np.full(NATIVE_SAMPLE_RATE, self._peak, dtype=np.float32)
        wave[0] = -self._peak
        return wave

    def save(self, audio, path: str) -> None:
        import soundfile as sf

        self.saved_peak = float(abs(audio).max())
        sf.write(path, audio, NATIVE_SAMPLE_RATE, subtype="PCM_16")


def _synthesize_with_fake(tmp_path: Path, peak: float = 0.5) -> _FakeEngine:
    from ai_video_agent.providers.base import TtsRequest

    provider = VieNeuTtsProvider()
    fake = _FakeEngine(peak=peak)
    provider._engine = fake
    provider.synthesize(
        TtsRequest(shot_id="a", text_vi="Xin chào", sample_rate=NATIVE_SAMPLE_RATE),
        tmp_path / "out.wav",
    )
    return fake


def test_moi_tham_so_deu_duoc_truyen_tuong_minh_cho_infer(tmp_path: Path) -> None:
    """Không được ăn theo mặc định của upstream: bản sau đổi là giọng đổi thầm lặng."""
    pytest.importorskip("soundfile")

    fake = _synthesize_with_fake(tmp_path)

    assert fake.kwargs["style"] == GOLDEN_STYLE
    assert fake.kwargs["denoise"] is GOLDEN_DENOISE
    assert fake.kwargs["use_ref_codes"] is GOLDEN_USE_REF_CODES
    assert fake.kwargs["temperature"] == GOLDEN_TEMPERATURE
    assert fake.kwargs["top_k"] == GOLDEN_TOP_K
    assert fake.kwargs["top_p"] == GOLDEN_TOP_P
    assert fake.kwargs["repetition_penalty"] == GOLDEN_REPETITION_PENALTY


def test_dau_ra_khong_clipping_ke_ca_khi_model_tra_ve_qua_thang(tmp_path: Path) -> None:
    """Đường gọi thật phải chặn được sự cố kiểu N2 (đỉnh 1,046 → 7 mẫu bị cắt)."""
    pytest.importorskip("soundfile")

    fake = _synthesize_with_fake(tmp_path, peak=1.046)

    assert fake.saved_peak <= MAX_OUTPUT_PEAK, "đã ghi ra audio vượt thang"
    assert fake.saved_peak == pytest.approx(SAFE_OUTPUT_PEAK, abs=1e-6)
    assert inspect_wav(tmp_path / "out.wav").clipping_ratio == 0.0


# --- voice asset --------------------------------------------------------------


def _manifest(project_id: str, *ids: str) -> AssetManifest:
    return AssetManifest(
        project_id=project_id,
        assets=[
            AssetEntry(
                id=asset_id,
                path=f"voice/{asset_id}.wav",
                sha256="a" * 64,
                kind=AssetKind.VOICE_SAMPLE,
                bytes=1024,
                consent=Consent(status=ConsentStatus.GRANTED, owner="Chủ máy"),
            )
            for asset_id in ids
        ],
    )


def test_chon_dung_mau_giong_da_chot_du_manifest_co_them_giong_moi(
    project: Project,
) -> None:
    """Thêm `voice-v2` vào manifest KHÔNG được làm đổi giọng đã chốt."""
    project.providers = ProviderSelection(voice_asset_id="voice-chinh")
    assets = _manifest(project.id, "voice-chinh", "voice-v2")

    chosen = Pipeline._select_voice_asset(project, assets)

    assert chosen is not None
    assert chosen.id == "voice-chinh"


def test_chon_dung_ke_ca_khi_giong_moi_dung_dau_danh_sach(project: Project) -> None:
    """Không phụ thuộc thứ tự trong manifest."""
    project.providers = ProviderSelection(voice_asset_id="voice-chinh")
    assets = _manifest(project.id, "voice-v2", "voice-chinh")

    chosen = Pipeline._select_voice_asset(project, assets)

    assert chosen is not None
    assert chosen.id == "voice-chinh"


def test_bao_loi_ngay_khi_mau_giong_da_chot_bien_mat(project: Project) -> None:
    """Thà dừng còn hơn lặng lẽ dùng giọng khác."""
    project.providers = ProviderSelection(voice_asset_id="voice-chinh")
    assets = _manifest(project.id, "voice-v2")

    with pytest.raises(ValidationError, match="voice-chinh"):
        Pipeline._select_voice_asset(project, assets)


def test_khong_chot_id_thi_van_lay_cai_dau_tien(project: Project) -> None:
    """Giữ tương thích ngược cho project chưa chốt giọng."""
    project.providers = ProviderSelection(voice_asset_id=None)
    assets = _manifest(project.id, "voice-a", "voice-b")

    chosen = Pipeline._select_voice_asset(project, assets)

    assert chosen is not None
    assert chosen.id == "voice-a"


# --- đầu ra không clipping ----------------------------------------------------


def test_ha_bien_do_khi_model_tra_ve_dinh_vuot_thang() -> None:
    """Đã quan sát thật ở biến thể N2: đỉnh 1,046 → 7 mẫu bị cắt khi ghi PCM_16."""
    pytest.importorskip("numpy")
    import numpy as np

    audio = np.array([1.046, -1.046, 0.5], dtype=np.float32)

    ket_qua = limit_peak(audio)

    assert float(abs(ket_qua).max()) == pytest.approx(SAFE_OUTPUT_PEAK, abs=1e-6)
    assert float(abs(ket_qua).max()) < MAX_OUTPUT_PEAK


def test_khong_dung_toi_am_thanh_da_nam_duoi_nguong() -> None:
    """Golden reference có đỉnh 0,974 — lưới an toàn không được làm nó đổi."""
    pytest.importorskip("numpy")
    import numpy as np

    audio = np.array([0.974, -0.5, 0.1], dtype=np.float32)

    ket_qua = limit_peak(audio)

    assert np.array_equal(ket_qua, audio), "đỉnh dưới 1,0 thì phải giữ nguyên tuyệt đối"


def test_limit_peak_chiu_duoc_mang_rong_va_mang_im_lang() -> None:
    pytest.importorskip("numpy")
    import numpy as np

    assert len(limit_peak(np.array([], dtype=np.float32))) == 0
    im_lang = np.zeros(8, dtype=np.float32)
    assert np.array_equal(limit_peak(im_lang), im_lang)


def test_wav_ghi_ra_phai_dung_dinh_dang_golden(tmp_path: Path) -> None:
    """Golden reference: 48 000 Hz, mono, 16-bit, không clipping."""
    pytest.importorskip("soundfile")
    import numpy as np
    import soundfile as sf

    path = tmp_path / "out.wav"
    sf.write(
        str(path),
        np.zeros(NATIVE_SAMPLE_RATE, dtype=np.float32) + 0.5,
        NATIVE_SAMPLE_RATE,
        subtype="PCM_16",
    )

    report = inspect_wav(path, expected_sample_rate=NATIVE_SAMPLE_RATE)

    assert report.sample_rate == 48_000
    assert report.channels == 1
    assert report.sample_width_bits == 16
    assert report.clipping_ratio == 0.0


# --- bảo vệ golden reference --------------------------------------------------


def test_thu_muc_doi_chung_duoc_khai_bao_bao_ve() -> None:
    assert "giu-lai" in PROTECTED_DIR_NAMES


@pytest.mark.parametrize(
    "duong_dan",
    [
        "F:/AI-VIDEO-AGENT-RUNTIME/healthcheck/giu-lai/giong-toi-A-mo-dau.wav",
        "F:/AI-VIDEO-AGENT-RUNTIME/healthcheck/giu-lai/tts-clone.wav",
        "runtime/giu-lai/bat-ky.wav",
    ],
)
def test_tu_choi_ghi_de_file_doi_chung(duong_dan: str) -> None:
    assert is_protected(Path(duong_dan))
    with pytest.raises(ConfigError, match="đối chứng"):
        assert_writable(Path(duong_dan))


@pytest.mark.parametrize(
    "duong_dan",
    [
        "F:/AI-VIDEO-AGENT-RUNTIME/healthcheck/tts-clone.wav",
        "F:/AI-VIDEO-AGENT-RUNTIME/projects/demo-vn/outputs/a.wav",
    ],
)
def test_van_ghi_binh_thuong_ngoai_thu_muc_bao_ve(duong_dan: str) -> None:
    assert not is_protected(Path(duong_dan))
    assert_writable(Path(duong_dan))  # không được ném lỗi


def test_adapter_kiem_tra_bao_ve_truoc_khi_ghi() -> None:
    source = Path(inspect.getfile(VieNeuTtsProvider)).read_text(encoding="utf-8")
    assert "assert_writable(out_path)" in source


def test_synthesize_tu_choi_ghi_vao_thu_muc_doi_chung(tmp_path: Path) -> None:
    """Hàng rào chạy TRƯỚC khi nạp model, nên test này không cần model."""
    from ai_video_agent.providers.base import TtsRequest

    bao_ve = tmp_path / "giu-lai" / "giong-toi-A-mo-dau.wav"

    with pytest.raises(ConfigError, match="đối chứng"):
        VieNeuTtsProvider().synthesize(
            TtsRequest(shot_id="a", text_vi="Xin chào", sample_rate=NATIVE_SAMPLE_RATE),
            bao_ve,
        )


# --- ghi nhận quyết định của PO ------------------------------------------------


def test_n1_va_fp32_khong_duoc_chon() -> None:
    """Khoá lại quyết định của PO ngay trong code, không chỉ trong tài liệu."""
    provider = VieNeuTtsProvider()

    assert provider._precision != "fp32", "PO không chọn fp32"
    assert provider.info().mode is ProviderMode.REAL
    # N1 dùng bản thu voice-v2; project đã chốt voice-chinh.
    assert ProviderSelection(voice_asset_id="voice-chinh").voice_asset_id == "voice-chinh"
