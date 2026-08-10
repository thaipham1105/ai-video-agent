"""CLI ``aiva`` — chạy hết đường đi doctor -> plan -> approve -> estimate -> render."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_video_agent.cli.main import app
from ai_video_agent.domain.enums import ProjectState
from ai_video_agent.orchestrator.repository import ProjectRepository

runner = CliRunner()

BRIEF = (
    "Bán lô đất thổ cư tại TP. Biên Hoà, sổ hồng riêng. "
    "Giá 1,2 tỷ, công chứng ngay. Liên hệ 0909123456."
)
PROJECT_ID = "demo-cli"


def _plan(**extra: str) -> None:
    args = ["plan", "--brief", BRIEF, "--id", PROJECT_ID, "--duration", "30"]
    for key, value in extra.items():
        args += [f"--{key.replace('_', '-')}", value]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


def _approve() -> None:
    result = runner.invoke(app, ["approve", PROJECT_ID, "--by", "Chủ máy"])
    assert result.exit_code == 0, result.output


# --- các lệnh cơ bản ----------------------------------------------------------


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ai-video-agent" in result.output


def test_doctor_chay_duoc_va_khong_lo_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIVA_VIDEO_API_KEY", "sk-khong-duoc-in-ra")

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    assert "sk-khong-duoc-in-ra" not in result.output
    payload = json.loads(result.output)
    assert {"name", "status", "detail"} <= set(payload[0])
    assert any(item["name"] == "schemas" and item["status"] == "PASS" for item in payload)


def test_plan_tao_du_file_va_dat_trang_thai_planned(runtime_dir: Path) -> None:
    _plan()

    repo = ProjectRepository(runtime_dir)
    project = repo.load_project(PROJECT_ID)
    assert project.state is ProjectState.PLANNED
    assert repo.paths(PROJECT_ID).storyboard_json.is_file()


def test_plan_tu_choi_ty_le_khung_hinh_la() -> None:
    result = runner.invoke(app, ["plan", "--brief", BRIEF, "--id", PROJECT_ID, "--aspect", "4:3"])
    assert result.exit_code == 1
    assert "không hợp lệ" in result.output


def test_status_liet_ke_project(runtime_dir: Path) -> None:
    _plan()

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert PROJECT_ID in result.output


def test_status_cua_mot_project_hien_thi_ngan_sach() -> None:
    _plan()

    result = runner.invoke(app, ["status", PROJECT_ID])

    assert result.exit_code == 0
    assert "ngân sách" in result.output
    assert "chưa" in result.output  # chưa duyệt


def test_validate_kiem_tra_theo_schema() -> None:
    _plan()

    result = runner.invoke(app, ["validate", PROJECT_ID])

    assert result.exit_code == 0
    assert "project.json" in result.output
    assert "storyboard.json" in result.output


def test_estimate_bao_khong_ton_tien_o_che_do_mock() -> None:
    _plan()

    result = runner.invoke(app, ["estimate", PROJECT_ID, "--detail"])

    assert result.exit_code == 0
    assert "0.0000 USD" in result.output


# --- phê duyệt và render ------------------------------------------------------


def test_approve_chuyen_sang_trang_thai_approved(runtime_dir: Path) -> None:
    _plan()
    _approve()

    project = ProjectRepository(runtime_dir).load_project(PROJECT_ID)
    assert project.state is ProjectState.APPROVED
    assert project.approval is not None


def test_render_mac_dinh_la_dry_run(runtime_dir: Path) -> None:
    """Brief §D01.5: không có cờ nào thì tuyệt đối không chạy provider."""
    _plan()
    _approve()

    result = runner.invoke(app, ["render", PROJECT_ID])

    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert not list((runtime_dir / "projects" / PROJECT_ID / "artifacts").rglob("*"))


def test_render_dry_run_in_canh_bao_ngon_ngu_va_preflight() -> None:
    """D04-D: hai câu này phải đọc được ngay ở dry-run, không cần --execute.

    Test ở tầng CLI chứ không phải tầng manifest: manifest có mà CLI nuốt mất
    thì với người dùng là không có.
    """
    _plan()
    _approve()

    result = runner.invoke(app, ["render", PROJECT_ID])

    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert "NGÔN NGỮ" in result.output, "Duix chưa kiểm chứng 'vi' — phải nói ra"
    assert "wenet-aishell" in result.output, "phải chỉ ra nguyên nhân gốc"
    assert "Preflight tài nguyên" in result.output


def test_render_that_bi_chan_khi_chua_duyet() -> None:
    _plan()

    result = runner.invoke(app, ["render", PROJECT_ID, "--execute"])

    assert result.exit_code == 1
    assert "approve" in result.output


def test_render_execute_chay_het_duong_ong_bang_mock(runtime_dir: Path) -> None:
    _plan()
    _approve()

    result = runner.invoke(app, ["render", PROJECT_ID, "--execute"])

    assert result.exit_code == 0, result.output
    assert "ĐÃ CHẠY" in result.output
    assert "file GIẢ" in result.output
    outputs = list((runtime_dir / "projects" / PROJECT_ID / "outputs").glob("*.mock.mp4"))
    assert outputs


def test_lap_lai_ke_hoach_lam_mat_hieu_luc_phe_duyet(runtime_dir: Path) -> None:
    """Sửa brief sau khi duyệt thì phải duyệt lại trước khi render (brief §9)."""
    _plan()
    _approve()

    result = runner.invoke(
        app,
        [
            "plan",
            "--brief",
            BRIEF + " Tặng thêm phí sang tên.",
            "--id",
            PROJECT_ID,
            "--duration",
            "30",
        ],
    )
    assert result.exit_code == 0, result.output

    project = ProjectRepository(runtime_dir).load_project(PROJECT_ID)
    assert project.approval is None
    assert project.state is ProjectState.PLANNED

    blocked = runner.invoke(app, ["render", PROJECT_ID, "--execute"])
    assert blocked.exit_code == 1


def test_render_chi_mot_shot(runtime_dir: Path) -> None:
    _plan()
    _approve()
    runner.invoke(app, ["render", PROJECT_ID, "--execute"])

    repo = ProjectRepository(runtime_dir)
    shot_id = repo.load_storyboard(PROJECT_ID).shots[0].id
    result = runner.invoke(app, ["render", PROJECT_ID, "--execute", "--only-shot", shot_id])

    assert result.exit_code == 0, result.output
    assert "reused" in result.output


def test_render_bao_loi_khi_shot_khong_ton_tai() -> None:
    _plan()
    _approve()

    result = runner.invoke(app, ["render", PROJECT_ID, "--only-shot", "shot-999"])

    assert result.exit_code == 1
    assert "Không có shot" in result.output


def test_status_bao_project_khong_ton_tai() -> None:
    result = runner.invoke(app, ["status", "khong-ton-tai"])
    assert result.exit_code == 1
