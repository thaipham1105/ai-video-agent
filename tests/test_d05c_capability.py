"""D05-C — năng lực model và hàng rào trước provider boundary.

Điều các test này bảo vệ: một cấu hình sai phải chết **trước** khi biến thành
một lần gọi có thể bị tính tiền.
"""

from __future__ import annotations

import pytest

from ai_video_agent.errors import CapabilityError
from ai_video_agent.providers.video_api.capability import (
    CAPABILITIES,
    VEO_FAST,
    VEO_LITE,
    VEO_STANDARD,
    VideoRequestConfig,
    build_provider_payload,
    check_config,
    get_capability,
)


def _cfg(model_id: str, **kw: object) -> VideoRequestConfig:
    base: dict[str, object] = {
        "model_id": model_id,
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "duration_seconds": 8,
    }
    base.update(kw)
    return VideoRequestConfig(**base)  # type: ignore[arg-type]


# --- 1. Ma trận năng lực của ba model -------------------------------------


def test_dung_ba_model_duoc_khai_bao() -> None:
    assert set(CAPABILITIES) == {VEO_STANDARD, VEO_FAST, VEO_LITE}


@pytest.mark.parametrize("model_id", [VEO_STANDARD, VEO_FAST, VEO_LITE])
def test_moi_model_deu_always_on_va_24fps(model_id: str) -> None:
    """Audio luôn bật và 24 fps là năng lực model, không phải tuỳ chọn."""
    cap = get_capability(model_id)
    assert cap.audio_mode == "always_on"
    assert cap.source_fps == 24


@pytest.mark.parametrize("model_id", [VEO_STANDARD, VEO_FAST, VEO_LITE])
def test_1080p_bat_buoc_dung_8_giay(model_id: str) -> None:
    assert get_capability(model_id).duration_constraint["1080p"] == frozenset({8})


def test_standard_va_fast_toi_da_3_reference_images() -> None:
    for model_id in (VEO_STANDARD, VEO_FAST):
        cap = get_capability(model_id)
        assert cap.supports_reference_images is True
        assert cap.max_reference_images == 3


def test_lite_khong_ho_tro_reference_images_nhung_van_co_initial_image() -> None:
    cap = get_capability(VEO_LITE)
    assert cap.supports_reference_images is False
    assert cap.max_reference_images == 0
    assert cap.supports_initial_image is True


def test_model_la_khong_co_ban_ghi_thi_bao_loi() -> None:
    with pytest.raises(CapabilityError, match="Không có bản ghi năng lực"):
        get_capability("veo-9.9-khong-ton-tai")


# --- 2. Lite + reference_images phải fail trước provider ------------------


def test_lite_kem_reference_images_bi_chan() -> None:
    with pytest.raises(CapabilityError, match="KHÔNG hỗ trợ reference_images"):
        check_config(_cfg(VEO_LITE, reference_image_count=1))


def test_qua_3_reference_images_bi_chan() -> None:
    with pytest.raises(CapabilityError, match="tối đa 3 reference_images"):
        check_config(_cfg(VEO_STANDARD, reference_image_count=4))


def test_lite_van_nhan_anh_khoi_tao() -> None:
    cap = check_config(_cfg(VEO_LITE, has_initial_image=True))
    assert cap.model_id == VEO_LITE


# --- 3. Yêu cầu video câm phải fail trước provider ------------------------


@pytest.mark.parametrize("model_id", [VEO_STANDARD, VEO_FAST, VEO_LITE])
def test_yeu_cau_video_cam_bi_chan(model_id: str) -> None:
    with pytest.raises(CapabilityError, match="luôn xuất video kèm audio"):
        check_config(_cfg(model_id, want_silent=True))


def test_payload_khong_bao_gio_chua_generate_audio() -> None:
    """SDK có field này nhưng Veo không hỗ trợ — không được gửi đi."""
    payload = build_provider_payload(_cfg(VEO_STANDARD))
    assert "generate_audio" not in payload


def test_payload_khong_bao_gio_chua_fps() -> None:
    """fps là năng lực cố định của model, không phải tham số gọi được."""
    payload = build_provider_payload(_cfg(VEO_STANDARD))
    assert "fps" not in payload


def test_yeu_cau_fps_khac_24_bi_chan() -> None:
    with pytest.raises(CapabilityError, match="xuất cố định 24 fps"):
        check_config(_cfg(VEO_STANDARD, requested_fps=30))


# --- 4. 1080p + duration khác 8 phải fail trước provider ------------------


@pytest.mark.parametrize("bad", [4, 5, 6, 7, 9, 10, 16])
def test_1080p_duration_khac_8_bi_chan(bad: int) -> None:
    with pytest.raises(CapabilityError, match="chỉ nhận thời lượng"):
        check_config(_cfg(VEO_STANDARD, duration_seconds=bad))


def test_do_phan_giai_la_bi_chan() -> None:
    with pytest.raises(CapabilityError, match="không hỗ trợ độ phân giải"):
        check_config(_cfg(VEO_STANDARD, resolution="4k"))


def test_ti_le_khung_hinh_la_bi_chan() -> None:
    with pytest.raises(CapabilityError, match="không hỗ trợ tỉ lệ"):
        check_config(_cfg(VEO_STANDARD, aspect_ratio="21:9"))


def test_pipeline_chi_sinh_dung_mot_video() -> None:
    with pytest.raises(CapabilityError, match="chỉ sinh đúng 1 video"):
        check_config(_cfg(VEO_STANDARD, number_of_videos=2))


def test_cau_hinh_hop_le_thi_qua() -> None:
    payload = build_provider_payload(_cfg(VEO_STANDARD))
    assert payload == {
        "model": VEO_STANDARD,
        "aspect_ratio": "9:16",
        "resolution": "1080p",
        "duration_seconds": 8,
        "number_of_videos": 1,
    }
