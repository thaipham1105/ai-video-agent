"""Xử lý văn bản tiếng Việt: slug, tách câu, trích chuỗi chính xác."""

from __future__ import annotations

import pytest

from ai_video_agent.domain.enums import OnScreenTextKind
from ai_video_agent.orchestrator.textutil import (
    extract_exact_texts,
    slugify,
    split_sentences,
    strip_diacritics,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Đất thổ cư Biên Hoà", "dat-tho-cu-bien-hoa"),
        ("  Nhà PHỐ 2 tầng!!  ", "nha-pho-2-tang"),
        ("Đồng Nai — Bình Phước", "dong-nai-binh-phuoc"),
    ],
)
def test_slugify_bo_dau_va_hop_le(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


def test_slugify_co_du_phong_khi_khong_con_ky_tu_nao() -> None:
    assert slugify("!!!") == "project"


def test_strip_diacritics_xu_ly_chu_d_gach() -> None:
    assert strip_diacritics("Đường Đồng Đen") == "Duong Dong Den"


def test_tach_cau_bo_qua_dau_cham_cua_viet_tat() -> None:
    """``TP.`` không phải hết câu."""
    text = "Nhà ở TP. Biên Hoà. Giá tốt."
    assert split_sentences(text) == ["Nhà ở TP. Biên Hoà.", "Giá tốt."]


def test_tach_cau_khong_cat_giua_so_thap_phan() -> None:
    assert split_sentences("Giá 1.250.000 đồng mỗi m2.") == ["Giá 1.250.000 đồng mỗi m2."]


def test_tach_cau_theo_dong_moi() -> None:
    assert split_sentences("Dòng một\nDòng hai") == ["Dòng một", "Dòng hai"]


def test_trich_so_dien_thoai_chuan_hoa_thanh_chu_so() -> None:
    found = extract_exact_texts("Liên hệ 0909 123 456 hoặc 0909123456 nhé")
    phones = [item.text for item in found if item.kind is OnScreenTextKind.PHONE]
    assert phones == ["0909123456"], "hai cách viết cùng một số phải gộp làm một"


def test_khong_nham_so_thuong_thanh_so_dien_thoai() -> None:
    found = extract_exact_texts("Diện tích 100m2, xây năm 2019, cách chợ 0.5 km")
    assert not [item for item in found if item.kind is OnScreenTextKind.PHONE]


@pytest.mark.parametrize(
    "text",
    ["Giá 1,2 tỷ", "Chỉ 850 triệu", "2.500.000 đồng", "35tr/m2"],
)
def test_trich_gia_tien(text: str) -> None:
    found = extract_exact_texts(text)
    assert [item for item in found if item.kind is OnScreenTextKind.PRICE]


def test_khong_nham_don_vi_khac_thanh_gia() -> None:
    """ "5 kg" không được trở thành "5 k"."""
    found = extract_exact_texts("Bao gạo 5 kg")
    assert not [item for item in found if item.kind is OnScreenTextKind.PRICE]


def test_cum_phap_ly_lay_ban_dai_nhat() -> None:
    """ "sổ hồng riêng" không được kéo theo "sổ hồng" thành hai dòng trùng ý."""
    found = extract_exact_texts("Đất có sổ hồng riêng, công chứng ngay")
    legal = [item.text.casefold() for item in found if item.kind is OnScreenTextKind.LEGAL]
    assert "sổ hồng riêng" in legal
    assert "sổ hồng" not in legal
    assert "công chứng" in legal


def test_trich_giu_nguyen_van_khong_doi_chu() -> None:
    """Chuỗi trả về phải nguyên văn để composer chèn đúng từng ký tự."""
    text = "Sổ Hồng Riêng, giá 1,2 tỷ"
    found = extract_exact_texts(text)
    assert any(item.text == "Sổ Hồng Riêng" for item in found)
    assert any(item.text == "1,2 tỷ" for item in found)
