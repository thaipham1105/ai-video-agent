"""Lưu trữ project: ghi/đọc, kiểm tra schema, và ranh giới thư mục runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import ProjectNotFoundError, ValidationError
from ai_video_agent.orchestrator.repository import ProjectRepository


def test_project_di_va_ve_nguyen_ven(repo: ProjectRepository, project: Project) -> None:
    repo.save_project(project)
    loaded = repo.load_project(project.id)

    assert loaded.model_dump(mode="json") == project.model_dump(mode="json")


def test_storyboard_di_va_ve_nguyen_ven(
    repo: ProjectRepository, project: Project, storyboard: Storyboard
) -> None:
    repo.save_storyboard(storyboard)
    loaded = repo.load_storyboard(project.id)

    assert loaded.sha256() == storyboard.sha256()


def test_asset_manifest_di_va_ve_nguyen_ven(
    repo: ProjectRepository, granted_assets: AssetManifest
) -> None:
    repo.save_assets(granted_assets)
    loaded = repo.load_assets(granted_assets.project_id)

    assert [a.id for a in loaded.assets] == [a.id for a in granted_assets.assets]


def test_thieu_manifest_thi_tra_ve_rong_chu_khong_no(repo: ProjectRepository) -> None:
    manifest = repo.load_assets("chua-co-gi")
    assert manifest.assets == []


def test_thieu_project_thi_bao_loi_ro_rang(repo: ProjectRepository) -> None:
    with pytest.raises(ProjectNotFoundError):
        repo.load_project("khong-ton-tai")


def test_file_tren_dia_luon_dung_hop_dong(repo: ProjectRepository, project: Project) -> None:
    """Ghi phải kiểm tra schema trước, nên file trên đĩa không bao giờ sai hợp đồng."""
    path = repo.save_project(project)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["id"] == project.id


def test_du_lieu_hong_bi_tu_choi_khi_doc(repo: ProjectRepository, project: Project) -> None:
    path = repo.save_project(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = "TRANG_THAI_LA"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        repo.load_project(project.id)


def test_ghi_xong_khong_de_lai_file_tam(repo: ProjectRepository, project: Project) -> None:
    repo.save_project(project)
    assert not list(repo.paths(project.id).root.glob("*.tmp"))


def test_luu_tru_nam_ngoai_repo_git(repo: ProjectRepository, project: Project) -> None:
    """Brief §6: dữ liệu thật phải ở thư mục runtime riêng, không nằm trong repo."""
    path = repo.save_project(project)
    repo_git = Path(__file__).resolve().parents[1]

    assert repo.runtime_dir not in repo_git.parents
    assert repo_git not in path.parents


def test_liet_ke_project_va_lan_render(
    repo: ProjectRepository, project: Project, storyboard: Storyboard
) -> None:
    repo.save_project(project)
    repo.save_storyboard(storyboard)

    assert repo.list_project_ids() == [project.id]
    assert repo.list_run_ids(project.id) == []


def test_duong_dan_shot_cache_tach_theo_noi_dung(
    repo: ProjectRepository, project: Project, storyboard: Storyboard
) -> None:
    paths = repo.paths(project.id)
    shot = storyboard.shots[0]

    truoc = paths.shot_cache_dir(shot.id, shot.content_hash())
    shot.narration_vi = "Nội dung khác hẳn"
    sau = paths.shot_cache_dir(shot.id, shot.content_hash())

    assert truoc != sau
