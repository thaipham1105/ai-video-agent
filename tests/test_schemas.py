"""Đối chiếu model pydantic với 4 JSON Schema trong ``schemas/``.

Model và schema được viết độc lập, nên nhóm test này là thứ bắt được sai lệch
giữa hợp đồng đối ngoại và hiện thực bên trong.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ai_video_agent.clock import now_utc
from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import ProviderMode, RenderStage, StageStatus
from ai_video_agent.domain.project import Approval, Project
from ai_video_agent.domain.render import RenderManifest, RenderRecord
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import ValidationError
from ai_video_agent.jsonschemas import SchemaName, iter_errors, load_schema, validate
from ai_video_agent.paths import schemas_dir


def test_du_bon_schema_theo_brief() -> None:
    """Brief §7 quy định đúng bốn hợp đồng dữ liệu."""
    for name in SchemaName:
        assert (schemas_dir() / name.filename).is_file(), f"thiếu {name.filename}"
    assert len(list(SchemaName)) == 4


@pytest.mark.parametrize("name", list(SchemaName))
def test_moi_schema_hop_le_theo_draft_2020_12(name: SchemaName) -> None:
    Draft202012Validator.check_schema(load_schema(name))


def test_project_dump_khop_schema(project: Project) -> None:
    validate(SchemaName.PROJECT, project.model_dump(mode="json"))


def test_project_co_phe_duyet_khop_schema(project: Project, storyboard: Storyboard) -> None:
    project.approval = Approval(
        approved_by="Chủ máy",
        approved_at=now_utc(),
        storyboard_sha256=storyboard.sha256(),
    )
    validate(SchemaName.PROJECT, project.model_dump(mode="json"))


def test_storyboard_dump_khop_schema(storyboard: Storyboard) -> None:
    validate(SchemaName.STORYBOARD, storyboard.model_dump(mode="json"))


def test_asset_manifest_dump_khop_schema(granted_assets: AssetManifest) -> None:
    validate(SchemaName.ASSET_MANIFEST, granted_assets.model_dump(mode="json"))


def test_render_manifest_dump_khop_schema(storyboard: Storyboard) -> None:
    manifest = RenderManifest(
        project_id=storyboard.project_id,
        run_id="run0001",
        storyboard_sha256=storyboard.sha256(),
        records=[
            RenderRecord(
                stage=RenderStage.TTS,
                shot_id="shot-001",
                provider="vieneu",
                model="vieneu-mock",
                version="0.1.0",
                mode=ProviderMode.MOCK,
                status=StageStatus.PLANNED,
            )
        ],
    )
    validate(SchemaName.RENDER_MANIFEST, manifest.model_dump(mode="json"))


def test_schema_bat_truong_la(project: Project) -> None:
    """``additionalProperties: false`` phải chặn trường không có trong hợp đồng."""
    payload: dict[str, Any] = project.model_dump(mode="json")
    payload["truong_khong_ton_tai"] = 1
    assert iter_errors(SchemaName.PROJECT, payload)


def test_schema_bat_trang_thai_khong_hop_le(project: Project) -> None:
    payload = project.model_dump(mode="json")
    payload["state"] = "SUPER_APPROVED"
    with pytest.raises(ValidationError):
        validate(SchemaName.PROJECT, payload)


def test_schema_bat_sha256_sai_dinh_dang(project: Project) -> None:
    payload = project.model_dump(mode="json")
    payload["approval"] = {
        "approved_by": "ai đó",
        "approved_at": "2026-08-04T09:30:00+00:00",
        "storyboard_sha256": "khong-phai-sha256",
    }
    assert iter_errors(SchemaName.PROJECT, payload)


def test_asset_manifest_chan_duong_dan_tuyet_doi(granted_assets: AssetManifest) -> None:
    """Brief §7 đòi đường dẫn tương đối; schema phải tự chặn được, không chỉ model."""
    payload = granted_assets.model_dump(mode="json")
    payload["assets"][0]["path"] = "C:/du-lieu-that/avatar.mp4"
    assert iter_errors(SchemaName.ASSET_MANIFEST, payload)

    payload["assets"][0]["path"] = "../../thoat-ra-ngoai.mp4"
    assert iter_errors(SchemaName.ASSET_MANIFEST, payload)


def test_asset_manifest_bat_buoc_khai_bao_consent(granted_assets: AssetManifest) -> None:
    payload = granted_assets.model_dump(mode="json")
    del payload["assets"][0]["consent"]
    assert iter_errors(SchemaName.ASSET_MANIFEST, payload)
