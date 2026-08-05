"""Provider: mock chạy được, adapter thật bị khoá theo gate."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from ai_video_agent import gate_is_open
from ai_video_agent.config import Config
from ai_video_agent.domain.enums import ProviderMode
from ai_video_agent.domain.project import ProviderSelection
from ai_video_agent.errors import (
    ConfigError,
    ConsentMissingError,
    GateNotReachedError,
    ProviderError,
)
from ai_video_agent.providers._placeholder import is_placeholder_video, read_wav_duration
from ai_video_agent.providers.base import (
    AvatarProvider,
    AvatarRequest,
    BrollRequest,
    TtsProvider,
    TtsRequest,
)
from ai_video_agent.providers.duix import DuixAvatarProvider, MockDuixAvatarProvider
from ai_video_agent.providers.registry import build_provider_set
from ai_video_agent.providers.video_api import VideoApiBrollProvider
from ai_video_agent.providers.video_api.adapter import API_KEY_ENV
from ai_video_agent.providers.vieneu import MockVieNeuTtsProvider, VieNeuTtsProvider
from ai_video_agent.providers.vimax import MockBrollProvider, ViMaxBrollProvider

# --- hàng rào gate ------------------------------------------------------------


def test_gate_hien_tai_la_d04() -> None:
    assert gate_is_open("D00")
    assert gate_is_open("D01")
    assert gate_is_open("D02")
    assert gate_is_open("D03")
    assert gate_is_open("D04")
    assert not gate_is_open("D05"), "API tính tiền VẪN PHẢI KHOÁ — D05 là tuỳ chọn"


def test_ten_gate_la_bi_tu_choi() -> None:
    assert not gate_is_open("D99")
    assert not gate_is_open("")


def test_gate_so_sanh_theo_thu_tu_khong_theo_chuoi() -> None:
    assert gate_is_open("D01", current="D03")
    assert not gate_is_open("D03", current="D01")


def test_vieneu_that_bi_chan_khi_gate_chua_toi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hạ gate về D01 thì adapter VieNeu thật phải từ chối chạy."""
    monkeypatch.setattr("ai_video_agent.CURRENT_GATE", "D01")
    with pytest.raises(GateNotReachedError) as info:
        VieNeuTtsProvider().synthesize(
            TtsRequest(shot_id="shot-001", text_vi="Xin chào"), tmp_path / "a.wav"
        )
    assert info.value.gate == "D02"


def test_duix_that_bi_chan_khi_gate_chua_toi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hạ gate về D02 thì adapter Duix thật phải từ chối chạy."""
    monkeypatch.setattr("ai_video_agent.CURRENT_GATE", "D02")
    with pytest.raises(GateNotReachedError) as info:
        DuixAvatarProvider().generate(
            AvatarRequest(
                shot_id="shot-001",
                audio_path=tmp_path / "a.wav",
                avatar_source=None,
                width=1080,
                height=1920,
            ),
            tmp_path / "a.mp4",
        )
    assert info.value.gate == "D03"


def test_duix_tu_choi_khi_thieu_tai_san_avatar(tmp_path: Path) -> None:
    """Gate mở rồi thì hàng rào consent vẫn phải chặn (brief §4)."""
    with pytest.raises(ConsentMissingError):
        DuixAvatarProvider().generate(
            AvatarRequest(
                shot_id="shot-001",
                audio_path=tmp_path / "a.wav",
                avatar_source=None,
                width=1080,
                height=1920,
            ),
            tmp_path / "a.mp4",
        )


def test_duix_doi_duong_dan_host_sang_duong_dan_container() -> None:
    """Duix nhận đường dẫn local, nhưng là local THEO GÓC NHÌN CONTAINER."""
    provider = DuixAvatarProvider(path_map=(("F:/AI-VIDEO-AGENT-RUNTIME/projects", "/inputs"),))

    got = provider.to_container_path(
        Path("F:/AI-VIDEO-AGENT-RUNTIME/projects/demo-vn/assets/avatar/a.mp4")
    )

    assert got == "/inputs/demo-vn/assets/avatar/a.mp4"


def test_duix_bao_loi_khi_duong_dan_ngoai_volume() -> None:
    """Thà dừng còn hơn gửi đường dẫn mà container không thấy."""
    provider = DuixAvatarProvider(path_map=(("F:/AI-VIDEO-AGENT-RUNTIME/projects", "/inputs"),))

    with pytest.raises(ProviderError, match="volume"):
        provider.to_container_path(Path("C:/noi-khac/a.mp4"))


@pytest.mark.parametrize(
    ("provider", "gate"),
    [(ViMaxBrollProvider(), "D05"), (VideoApiBrollProvider(), "D05")],
)
def test_provider_tinh_tien_bi_chan_o_gate_hien_tai(provider, gate: str, tmp_path: Path) -> None:
    with pytest.raises(GateNotReachedError) as info:
        provider.generate(
            BrollRequest(
                shot_id="shot-001",
                prompt_vi="cảnh khu dân cư",
                duration_sec=4.0,
                width=1080,
                height=1920,
            ),
            tmp_path / "b.mp4",
        )
    assert info.value.gate == gate


# --- VieNeu thật: kiểm tra được mà KHÔNG nạp engine ---------------------------


def test_vieneu_that_bao_gia_ma_khong_nap_model() -> None:
    """``quote()`` phải thuần tính toán — nếu nó nạp engine, test sẽ treo/tải mạng."""
    provider = VieNeuTtsProvider()

    quote = provider.quote(TtsRequest(shot_id="a", text_vi="Xin chào các bạn"))

    assert quote.billable is False
    assert quote.estimated_usd == 0.0
    assert quote.units == len("Xin chào các bạn")


def test_vieneu_that_khai_bao_dung_danh_tinh() -> None:
    info = VieNeuTtsProvider().info()

    assert info.mode is ProviderMode.REAL
    assert info.billable is False, "VieNeu chạy local, không phải hoá đơn API"
    assert info.gate == "D02"
    assert "int8" in info.model


def test_vieneu_that_tu_choi_sample_rate_khac(tmp_path: Path) -> None:
    """v3 Turbo chỉ xuất 48 kHz; yêu cầu khác là cấu hình sai, không im lặng bỏ qua."""
    with pytest.raises(ConfigError, match="48000"):
        VieNeuTtsProvider().synthesize(
            TtsRequest(shot_id="a", text_vi="Xin chào", sample_rate=24_000),
            tmp_path / "a.wav",
        )


def test_vieneu_that_tu_choi_mau_giong_khong_ton_tai(tmp_path: Path) -> None:
    """Brief §4: không nhân bản giọng từ mẫu chưa khai báo."""
    with pytest.raises(ConsentMissingError):
        VieNeuTtsProvider().synthesize(
            TtsRequest(
                shot_id="a",
                text_vi="Xin chào",
                ref_audio=tmp_path / "khong-co-that.wav",
                sample_rate=48_000,
            ),
            tmp_path / "a.wav",
        )


def test_import_vieneu_khong_xay_ra_o_cap_module() -> None:
    """Đường mock phải chạy được khi chưa cài extra 'tts' (AGENTS.md)."""
    import ai_video_agent.providers.vieneu.adapter as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    top_level = [
        line for line in source.splitlines() if line.startswith(("import vieneu", "from vieneu"))
    ]
    assert not top_level, "SDK nặng chỉ được import bên trong hàm"


def test_bao_gia_van_chay_duoc_khi_gate_chua_mo() -> None:
    """``estimate`` phải dùng được ở mọi gate — nó chỉ tính toán, không chạy gì."""
    quote = VideoApiBrollProvider().quote(
        BrollRequest(
            shot_id="shot-001", prompt_vi="cảnh phố", duration_sec=4.0, width=1080, height=1920
        )
    )
    assert quote.billable
    assert quote.estimated_usd > 0


# --- mock TTS -----------------------------------------------------------------


def test_mock_tts_sinh_file_wav_that(tmp_path: Path) -> None:
    """WAV giả vẫn phải là WAV hợp lệ, để kiểm tra thời lượng có ý nghĩa."""
    out = tmp_path / "shot.wav"
    result = MockVieNeuTtsProvider(sample_rate=48_000).synthesize(
        TtsRequest(shot_id="shot-001", text_vi="Xin chào các bạn", target_duration_sec=3.0), out
    )

    assert out.is_file()
    with wave.open(str(out), "rb") as handle:
        assert handle.getframerate() == 48_000
        assert handle.getnchannels() == 1
    assert result.duration_sec == pytest.approx(3.0, abs=0.01)
    assert read_wav_duration(out) == pytest.approx(3.0, abs=0.01)
    assert result.is_placeholder is True


def test_mock_tts_suy_thoi_luong_tu_do_dai_thoai(tmp_path: Path) -> None:
    ngan = MockVieNeuTtsProvider().synthesize(
        TtsRequest(shot_id="a", text_vi="Ngắn"), tmp_path / "a.wav"
    )
    dai = MockVieNeuTtsProvider().synthesize(
        TtsRequest(shot_id="b", text_vi="Một câu dài hơn rất nhiều so với câu trước đó"),
        tmp_path / "b.wav",
    )
    assert dai.duration_sec > ngan.duration_sec


def test_mock_tts_khong_ton_tien(tmp_path: Path) -> None:
    quote = MockVieNeuTtsProvider().quote(TtsRequest(shot_id="a", text_vi="Xin chào"))
    assert quote.billable is False
    assert quote.estimated_usd == 0.0


# --- mock Duix ----------------------------------------------------------------


def test_mock_duix_lay_thoi_luong_tu_wav_that(tmp_path: Path) -> None:
    """Thời lượng video phải bám theo audio thật, không bám theo con số dự kiến."""
    audio = tmp_path / "a.wav"
    MockVieNeuTtsProvider().synthesize(
        TtsRequest(shot_id="a", text_vi="bất kỳ", target_duration_sec=2.5), audio
    )
    video = tmp_path / "a.mp4"

    result = MockDuixAvatarProvider().generate(
        AvatarRequest(
            shot_id="a", audio_path=audio, avatar_source=None, width=1080, height=1920, fps=30
        ),
        video,
    )

    assert result.duration_sec == pytest.approx(2.5, abs=0.01)
    assert result.is_placeholder is True
    assert is_placeholder_video(video), "file giả phải nhận diện được ngay từ nội dung"


# --- mock B-roll --------------------------------------------------------------


def test_mock_broll_van_bao_gia_nhu_hang_tinh_tien(tmp_path: Path) -> None:
    """Mock giữ nguyên cờ billable để cost guard được kiểm thử thật sự."""
    provider = MockBrollProvider()
    request = BrollRequest(
        shot_id="a", prompt_vi="cảnh khu dân cư", duration_sec=5.0, width=1080, height=1920
    )

    quote = provider.quote(request)
    result = provider.generate(request, tmp_path / "b.mp4")

    assert quote.billable is True
    assert quote.estimated_usd > 0
    assert result.actual_cost_usd == 0.0, "mock không được tiêu tiền thật"


# --- API key ------------------------------------------------------------------


def test_khong_bao_gio_doc_gia_tri_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chỉ được biết key có tồn tại hay không (CLAUDE.md §4)."""
    monkeypatch.setenv(API_KEY_ENV, "sk-gia-lap-khong-duoc-doc")
    provider = VideoApiBrollProvider()

    assert provider.api_key_configured() is True
    assert "sk-gia-lap" not in repr(provider)
    assert "sk-gia-lap" not in str(provider.info())


def test_idempotency_key_on_dinh_va_khac_nhau_theo_yeu_cau() -> None:
    """Cùng yêu cầu -> cùng khoá, để không bị tính tiền hai lần (brief §D05.3)."""
    provider = VideoApiBrollProvider()
    base = BrollRequest(
        shot_id="shot-001", prompt_vi="cảnh phố", duration_sec=4.0, width=1080, height=1920
    )
    khac = BrollRequest(
        shot_id="shot-001", prompt_vi="cảnh biển", duration_sec=4.0, width=1080, height=1920
    )

    assert provider.idempotency_key(base, "p1") == provider.idempotency_key(base, "p1")
    assert provider.idempotency_key(base, "p1") != provider.idempotency_key(base, "p2")
    assert provider.idempotency_key(base, "p1") != provider.idempotency_key(khac, "p1")


def test_chinh_sach_goi_api_mac_dinh_la_khoa_chat() -> None:
    policy = VideoApiBrollProvider().policy
    assert policy.max_usd_per_run == 0.0
    assert policy.require_explicit_approval is True
    assert policy.max_retries <= 1


# --- registry -----------------------------------------------------------------


def test_registry_mac_dinh_tra_ve_mock(config: Config) -> None:
    providers = build_provider_set(ProviderSelection(), config=config)

    assert isinstance(providers.tts, TtsProvider)
    assert isinstance(providers.avatar, AvatarProvider)
    assert providers.tts.info().mode is ProviderMode.MOCK
    assert providers.avatar.info().mode is ProviderMode.MOCK
    assert providers.broll is None, "MVP không dùng B-roll"
    assert providers.any_billable is False


def test_registry_ep_duoc_ve_mock_du_project_chon_real(config: Config) -> None:
    """Người dùng lúc nào cũng ép được về mock từ dòng lệnh."""
    selection = ProviderSelection(mode=ProviderMode.REAL)

    providers = build_provider_set(selection, mode=ProviderMode.MOCK, config=config)

    assert providers.tts.info().mode is ProviderMode.MOCK


def test_registry_tu_choi_provider_la(config: Config) -> None:
    with pytest.raises(ConfigError):
        build_provider_set(ProviderSelection(tts="khong-ton-tai"), config=config)
    with pytest.raises(ConfigError):
        build_provider_set(ProviderSelection(broll="khong-ton-tai"), config=config)
