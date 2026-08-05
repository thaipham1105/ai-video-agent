"""Đọc/ghi dữ liệu project trên đĩa.

Mọi thứ nằm dưới ``AIVA_RUNTIME_DIR`` — **ngoài** repo Git (brief §6). Đây là
cửa duy nhất ghi đĩa, nên chỉ cần kiểm tra file này là biết chắc không có dữ
liệu thật nào rơi vào repo.

Mỗi lần ghi đều kiểm tra JSON Schema trước, nên file trên đĩa luôn đúng hợp
đồng; ghi theo kiểu tạm-rồi-đổi-tên để không để lại file JSON dở dang khi lệnh
bị ngắt giữa chừng.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.render import RenderManifest
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import ProjectNotFoundError
from ai_video_agent.jsonschemas import SchemaName, validate

PROJECT_FILE = "project.json"
STORYBOARD_FILE = "storyboard.json"
ASSET_MANIFEST_FILE = "asset-manifest.json"
RENDER_MANIFEST_FILE = "render-manifest.json"
SUBTITLE_FILE = "subtitles.srt"


@dataclass(frozen=True)
class ProjectPaths:
    """Bố cục thư mục của một project trong runtime."""

    root: Path

    @property
    def project_json(self) -> Path:
        return self.root / PROJECT_FILE

    @property
    def storyboard_json(self) -> Path:
        return self.root / STORYBOARD_FILE

    @property
    def asset_manifest_json(self) -> Path:
        return self.root / ASSET_MANIFEST_FILE

    @property
    def assets_dir(self) -> Path:
        """Tài sản do người dùng cung cấp (giọng mẫu, video avatar, logo…)."""
        return self.root / "assets"

    @property
    def artifacts_dir(self) -> Path:
        """Kết quả trung gian theo shot, có cache để render lại từng phần."""
        return self.root / "artifacts"

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    @property
    def outputs_dir(self) -> Path:
        return self.root / "outputs"

    def run_dir(self, run_id: str) -> Path:
        return self.renders_dir / run_id

    def shot_cache_dir(self, shot_id: str, content_hash: str) -> Path:
        return self.artifacts_dir / shot_id / content_hash[:16]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        msg = f"Không tìm thấy file: {path}"
        raise ProjectNotFoundError(msg)
    return json.loads(path.read_text(encoding="utf-8"))


class ProjectRepository:
    """Lưu trữ project theo thư mục, mỗi project một folder."""

    def __init__(self, runtime_dir: Path) -> None:
        self._runtime_dir = Path(runtime_dir)

    @property
    def runtime_dir(self) -> Path:
        return self._runtime_dir

    @property
    def projects_dir(self) -> Path:
        return self._runtime_dir / "projects"

    def paths(self, project_id: str) -> ProjectPaths:
        return ProjectPaths(root=self.projects_dir / project_id)

    def exists(self, project_id: str) -> bool:
        return self.paths(project_id).project_json.is_file()

    def list_project_ids(self) -> list[str]:
        if not self.projects_dir.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.projects_dir.iterdir()
            if entry.is_dir() and (entry / PROJECT_FILE).is_file()
        )

    # ----- project -------------------------------------------------------------

    def save_project(self, project: Project) -> Path:
        payload = project.model_dump(mode="json")
        validate(SchemaName.PROJECT, payload)
        path = self.paths(project.id).project_json
        _write_json(path, payload)
        return path

    def load_project(self, project_id: str) -> Project:
        payload = _read_json(self.paths(project_id).project_json)
        validate(SchemaName.PROJECT, payload)
        return Project.model_validate(payload)

    # ----- storyboard ----------------------------------------------------------

    def save_storyboard(self, storyboard: Storyboard) -> Path:
        payload = storyboard.model_dump(mode="json")
        validate(SchemaName.STORYBOARD, payload)
        path = self.paths(storyboard.project_id).storyboard_json
        _write_json(path, payload)
        return path

    def load_storyboard(self, project_id: str) -> Storyboard:
        payload = _read_json(self.paths(project_id).storyboard_json)
        validate(SchemaName.STORYBOARD, payload)
        return Storyboard.model_validate(payload)

    # ----- asset manifest ------------------------------------------------------

    def save_assets(self, manifest: AssetManifest) -> Path:
        payload = manifest.model_dump(mode="json")
        validate(SchemaName.ASSET_MANIFEST, payload)
        path = self.paths(manifest.project_id).asset_manifest_json
        _write_json(path, payload)
        return path

    def load_assets(self, project_id: str) -> AssetManifest:
        """Đọc manifest tài sản; trả về manifest rỗng nếu project chưa khai báo."""
        path = self.paths(project_id).asset_manifest_json
        if not path.is_file():
            return AssetManifest(project_id=project_id)
        payload = _read_json(path)
        validate(SchemaName.ASSET_MANIFEST, payload)
        return AssetManifest.model_validate(payload)

    # ----- render manifest -----------------------------------------------------

    def save_render_manifest(self, manifest: RenderManifest) -> Path:
        payload = manifest.model_dump(mode="json")
        validate(SchemaName.RENDER_MANIFEST, payload)
        path = self.paths(manifest.project_id).run_dir(manifest.run_id) / RENDER_MANIFEST_FILE
        _write_json(path, payload)
        return path

    def load_render_manifest(self, project_id: str, run_id: str) -> RenderManifest:
        payload = _read_json(self.paths(project_id).run_dir(run_id) / RENDER_MANIFEST_FILE)
        validate(SchemaName.RENDER_MANIFEST, payload)
        return RenderManifest.model_validate(payload)

    def list_run_ids(self, project_id: str) -> list[str]:
        renders = self.paths(project_id).renders_dir
        if not renders.is_dir():
            return []
        return sorted(
            entry.name
            for entry in renders.iterdir()
            if entry.is_dir() and (entry / RENDER_MANIFEST_FILE).is_file()
        )
