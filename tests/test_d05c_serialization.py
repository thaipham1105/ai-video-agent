"""D05-C — chuẩn hoá usage của SDK.

Hồi quy trực tiếp của lỗi D05-B:
``TypeError: Object of type ModalityTokens is not JSON serializable``.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ai_video_agent.providers.video_api.serialization import (
    normalize,
    to_json_text,
    write_usage_safely,
)


class Modality(enum.Enum):
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"


class ModalityTokens:
    """Bản sao hình dạng của đúng đối tượng đã làm hỏng báo cáo ở D05-B."""

    def __init__(self, modality: Modality, token_count: int) -> None:
        self.modality = modality
        self.token_count = token_count


@dataclass
class UsageDataclass:
    total: int
    detail: list[ModalityTokens]


class PydanticLike:
    """Giả lập object pydantic của google-genai."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        del mode
        return self._payload


class BrokenDump:
    """Object có ``model_dump`` nhưng ném lỗi — phải rơi xuống cách khác."""

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        del mode
        msg = "dump hong"
        raise RuntimeError(msg)

    def __init__(self) -> None:
        self.fallback_field = 7


# --- 12. Serializer xử lý structured objects / enum / ModalityTokens ------


def test_modality_tokens_khong_lam_hong_json() -> None:
    obj = ModalityTokens(Modality.VIDEO, 46336)
    text = to_json_text(obj)
    data = json.loads(text)
    assert data["modality"] == "VIDEO"
    assert data["token_count"] == 46336


def test_enum_duoc_doi_sang_gia_tri() -> None:
    assert normalize(Modality.AUDIO) == "AUDIO"


def test_dataclass_long_nhau_van_serialize_duoc() -> None:
    usage = UsageDataclass(total=2, detail=[ModalityTokens(Modality.VIDEO, 10)])
    data = json.loads(to_json_text(usage))
    assert data["total"] == 2
    assert data["detail"][0]["token_count"] == 10


def test_object_pydantic_dung_model_dump() -> None:
    obj = PydanticLike({"output_tokens": 46336, "modality": Modality.VIDEO})
    data = json.loads(to_json_text(obj))
    assert data["output_tokens"] == 46336
    assert data["modality"] == "VIDEO"


def test_model_dump_hong_thi_roi_xuong_cach_khac() -> None:
    data = json.loads(to_json_text(BrokenDump()))
    assert data["fallback_field"] == 7


def test_decimal_va_path_serialize_duoc() -> None:
    data = json.loads(to_json_text({"gia": Decimal("3.2000"), "duong": Path("a/b.mp4")}))
    assert data["gia"] == "3.2000"
    assert "b.mp4" in data["duong"]


def test_doi_tuong_tu_tham_chieu_khong_lam_treo() -> None:
    node: dict[str, object] = {"ten": "goc"}
    node["chinh_no"] = node
    assert "goc" in to_json_text(node)


def test_to_json_text_khong_bao_gio_nem_loi() -> None:
    class Hostile:
        def __repr__(self) -> str:
            return "<hostile>"

        @property
        def __dict__(self) -> dict[str, object]:  # type: ignore[override]
            msg = "khong doc duoc"
            raise RuntimeError(msg)

    assert to_json_text(Hostile())


# --- 13. Lỗi serialization không làm mất kết quả đã persist ---------------


def test_ghi_raw_truoc_nen_van_con_du_lieu_tinh_tien(tmp_path: Path) -> None:
    usage = ModalityTokens(Modality.VIDEO, 46336)
    report = write_usage_safely(
        raw_usage=usage,
        raw_path=tmp_path / "usage.raw.txt",
        normalized_path=tmp_path / "usage.json",
    )
    assert report["raw_written"] is True
    assert report["normalized_written"] is True
    assert (tmp_path / "usage.raw.txt").is_file()


def test_ghi_usage_khong_nem_loi_ra_ngoai(tmp_path: Path) -> None:
    """Kể cả khi đường ghi hỏng, hàm vẫn trả báo cáo thay vì làm sập tiến trình."""
    blocked = tmp_path / "usage.raw.txt"
    blocked.mkdir()  # thư mục trùng tên file => ghi chắc chắn hỏng
    report = write_usage_safely(
        raw_usage=ModalityTokens(Modality.VIDEO, 1),
        raw_path=blocked,
        normalized_path=tmp_path / "usage.json",
    )
    assert report["raw_written"] is False
    assert report["error"] is not None
    # điều quan trọng: bản chuẩn hoá vẫn ghi được, tiến trình không chết
    assert report["normalized_written"] is True


def test_ket_qua_da_luu_khong_bi_mat_khi_usage_hong(tmp_path: Path) -> None:
    """Mô phỏng đúng kịch bản D05-B: video đã có, usage hỏng."""
    video = tmp_path / "broll.mp4"
    video.write_bytes(b"da tra tien cho file nay")
    write_usage_safely(
        raw_usage=ModalityTokens(Modality.VIDEO, 1),
        raw_path=tmp_path / "sub" / "usage.raw.txt",
        normalized_path=tmp_path / "sub" / "usage.json",
    )
    assert video.is_file()
    assert video.read_bytes() == b"da tra tien cho file nay"
