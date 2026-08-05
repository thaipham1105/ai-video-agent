"""Project mẫu trong ``projects-example/`` phải luôn khớp hợp đồng dữ liệu.

Nếu schema hay model đổi mà file mẫu không đổi theo, nhóm test này đỏ — nên tài
liệu ví dụ không thể lỗi thời một cách âm thầm.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import ConsentStatus, OnScreenTextKind, ProjectState
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.jsonschemas import SchemaName, validate

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "projects-example" / "demo-bds-9x16"


def _load(filename: str) -> dict:
    return json.loads((EXAMPLE_DIR / filename).read_text(encoding="utf-8"))


def test_thu_muc_mau_ton_tai() -> None:
    assert EXAMPLE_DIR.is_dir()


@pytest.mark.parametrize(
    ("filename", "schema"),
    [
        ("project.json", SchemaName.PROJECT),
        ("storyboard.json", SchemaName.STORYBOARD),
        ("asset-manifest.json", SchemaName.ASSET_MANIFEST),
    ],
)
def test_file_mau_khop_schema(filename: str, schema: SchemaName) -> None:
    validate(schema, _load(filename))


def test_file_mau_nap_duoc_vao_model() -> None:
    project = Project.model_validate(_load("project.json"))
    storyboard = Storyboard.model_validate(_load("storyboard.json"))
    assets = AssetManifest.model_validate(_load("asset-manifest.json"))

    assert project.id == storyboard.project_id == assets.project_id


def test_phe_duyet_trong_file_mau_con_hieu_luc() -> None:
    """Hash trong ``project.json`` phải khớp ``storyboard.json`` đi kèm."""
    project = Project.model_validate(_load("project.json"))
    storyboard = Storyboard.model_validate(_load("storyboard.json"))

    assert project.state is ProjectState.APPROVED
    assert project.approval_matches(storyboard.sha256())


def test_file_mau_the_hien_du_cac_loai_chu_chinh_xac() -> None:
    storyboard = Storyboard.model_validate(_load("storyboard.json"))
    kinds = {text.kind for shot in storyboard.shots for text in shot.on_screen_text}

    assert {
        OnScreenTextKind.PHONE,
        OnScreenTextKind.PRICE,
        OnScreenTextKind.LEGAL,
        OnScreenTextKind.CTA,
    } <= kinds


def test_so_dien_thoai_trong_file_mau_dung_tung_chu_so() -> None:
    storyboard = Storyboard.model_validate(_load("storyboard.json"))
    phones = [
        text.text
        for shot in storyboard.shots
        for text in shot.on_screen_text
        if text.kind is OnScreenTextKind.PHONE
    ]
    assert phones == ["0909123456"]


def test_moi_tai_san_mau_deu_khai_bao_chu_so_huu_va_dong_y() -> None:
    assets = AssetManifest.model_validate(_load("asset-manifest.json"))

    assert assets.assets
    assert not assets.blocking(), "tài sản mẫu phải ở trạng thái dùng được"
    for asset in assets.assets:
        assert asset.consent.owner
        if asset.consent.status is ConsentStatus.GRANTED:
            assert asset.consent.granted_by
            assert asset.consent.granted_at is not None
            assert asset.consent.scope, "phải ghi rõ phạm vi được phép dùng"


def test_khong_co_media_that_trong_thu_muc_mau() -> None:
    for path in EXAMPLE_DIR.rglob("*"):
        assert path.suffix.lower() in {".json", ".md"}, f"{path.name} không được nằm đây"


def test_tran_ngan_sach_mau_bang_khong() -> None:
    """Ví dụ phải làm gương: MVP không tiêu tiền API."""
    project = Project.model_validate(_load("project.json"))
    assert project.budget.cap_usd == 0.0
    assert project.ai_disclosure.enabled is True
