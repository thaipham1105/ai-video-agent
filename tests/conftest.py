"""Fixture dùng chung.

Hai bảo đảm quan trọng của toàn bộ bộ test:

* Mọi biến môi trường ``AIVA_*`` bị xoá trước mỗi test, nên kết quả không phụ
  thuộc vào cấu hình riêng của máy đang chạy.
* ``AIVA_RUNTIME_DIR`` trỏ vào ``tmp_path``, nên test không bao giờ đụng vào
  thư mục runtime thật của người dùng.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_video_agent.clock import FixedClock
from ai_video_agent.composer.runner import MockComposer
from ai_video_agent.config import Config
from ai_video_agent.domain.assets import AssetEntry, AssetManifest, Consent
from ai_video_agent.domain.enums import AspectRatio, AssetKind, ConsentStatus, ProviderMode
from ai_video_agent.domain.project import BudgetPolicy, Project, ProviderSelection
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.orchestrator.pipeline import Pipeline
from ai_video_agent.orchestrator.planner import RuleBasedPlanner
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers import resource_budget
from ai_video_agent.providers.registry import build_provider_set

FIXED_MOMENT = datetime(2026, 8, 4, 9, 30, tzinfo=UTC)

SAMPLE_BRIEF = (
    "Bán lô đất thổ cư mặt tiền đường nhựa tại TP. Biên Hoà. "
    "Diện tích 100m2, sổ hồng riêng, công chứng trong ngày. "
    "Giá chỉ 1,2 tỷ, thương lượng cho khách thiện chí. "
    "Khu dân cư hiện hữu, gần chợ và trường học. "
    "Liên hệ 0909123456 để xem đất ngay hôm nay."
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cách ly test khỏi môi trường thật của máy."""
    for name in list(os.environ):
        if name.startswith("AIVA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIVA_RUNTIME_DIR", str(tmp_path / "runtime"))

    # Chốt chặn: nếu có test nào lỡ chạm vào adapter thật, Hugging Face phải
    # BÁO LỖI NGAY thay vì âm thầm tải 312 MB model. Brief §4: test không được
    # gọi ra ngoài; đây là cách biến quy tắc đó thành thứ máy tự thực thi.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    # Cùng lý do, cho GPU: preflight tài nguyên gọi `nvidia-smi` trên đường thật.
    # Để nguyên thì kết quả test phụ thuộc vào card đang cắm và VRAM đang rảnh
    # lúc chạy — hôm nay xanh, mai đỏ. Mặc định trả `None` = "chưa xác minh
    # được", đúng trạng thái của một máy không có GPU. Test nào cần dò thật thì
    # tự tiêm probe của mình.
    monkeypatch.setattr(resource_budget, "probe_free_vram_mib", lambda: None)
    # Từ D05-C, sampler lúc render cũng hỏi tổng VRAM. Chặn nốt đường đó, nếu
    # không thì `peak_vram_mib` trong test sẽ phụ thuộc vào card đang cắm.
    monkeypatch.setattr(resource_budget, "probe_total_vram_mib", lambda: None)


@pytest.fixture
def sample_brief() -> str:
    """Brief tiếng Việt có đủ số điện thoại, giá và cụm pháp lý."""
    return SAMPLE_BRIEF


@pytest.fixture
def runtime_dir(tmp_path: Path) -> Path:
    return tmp_path / "runtime"


@pytest.fixture
def config(runtime_dir: Path) -> Config:
    return Config(runtime_dir=runtime_dir)


@pytest.fixture
def repo(runtime_dir: Path) -> ProjectRepository:
    return ProjectRepository(runtime_dir)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(FIXED_MOMENT)


@pytest.fixture
def project() -> Project:
    return Project(
        id="demo-bds",
        title="Đất thổ cư Biên Hoà",
        brief_vi=SAMPLE_BRIEF,
        aspect_ratio=AspectRatio.VERTICAL,
        target_duration_sec=45.0,
        budget=BudgetPolicy(cap_usd=0.0),
        providers=ProviderSelection(),
        created_at=FIXED_MOMENT,
        updated_at=FIXED_MOMENT,
    )


@pytest.fixture
def storyboard(project: Project) -> Storyboard:
    return RuleBasedPlanner().plan(
        project_id=project.id,
        brief_vi=project.brief_vi,
        target_duration_sec=project.target_duration_sec,
        aspect_ratio=project.aspect_ratio,
    )


@pytest.fixture
def empty_assets(project: Project) -> AssetManifest:
    return AssetManifest(project_id=project.id)


@pytest.fixture
def granted_assets(project: Project) -> AssetManifest:
    """Manifest với đầy đủ tài sản đã được chủ sở hữu đồng ý cho dùng."""
    return AssetManifest(
        project_id=project.id,
        assets=[
            AssetEntry(
                id="avatar-main",
                path="avatar/nguoi-dai-dien.mp4",
                sha256="a" * 64,
                kind=AssetKind.AVATAR_SOURCE,
                bytes=1024,
                consent=Consent(
                    status=ConsentStatus.GRANTED,
                    owner="Chủ máy",
                    granted_by="Chủ máy",
                    granted_at=FIXED_MOMENT,
                    scope="Dùng cho video marketing của công ty",
                    evidence_ref="HS-2026-001",
                ),
            ),
            AssetEntry(
                id="logo",
                path="brand/logo.png",
                sha256="b" * 64,
                kind=AssetKind.LOGO,
                bytes=2048,
                consent=Consent(status=ConsentStatus.NOT_REQUIRED, owner="Công ty"),
            ),
        ],
    )


@pytest.fixture
def pending_assets(project: Project) -> AssetManifest:
    """Manifest có tài sản CHƯA được đồng ý — phải chặn render thật."""
    return AssetManifest(
        project_id=project.id,
        assets=[
            AssetEntry(
                id="voice-khach",
                path="voice/mau-giong.wav",
                sha256="c" * 64,
                kind=AssetKind.VOICE_SAMPLE,
                bytes=4096,
                consent=Consent(status=ConsentStatus.PENDING, owner="Người khác"),
            )
        ],
    )


@pytest.fixture
def pipeline(repo: ProjectRepository, config: Config, clock: FixedClock) -> Pipeline:
    providers = build_provider_set(ProviderSelection(), mode=ProviderMode.MOCK, config=config)
    return Pipeline(
        repository=repo,
        providers=providers,
        config=config,
        composer=MockComposer(),
        now=clock.now_utc,
        make_run_id=clock.new_run_id,
    )
