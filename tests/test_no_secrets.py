"""Quét repo tìm secret và dữ liệu thật.

Đây là bản tự động hoá của brief §4 và tiêu chí MVP §9: "Không có secret hoặc dữ
liệu thật trong Git/diff/log". Test chạy trên **toàn bộ file được Git theo dõi**,
nên nó bảo vệ cả những thay đổi sau này chứ không riêng gì D01.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Mẫu khoá bí mật thường gặp. Cố ý viết rời để chính file này không tự khớp.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

#: Đuôi file media/model không bao giờ được nằm trong Git.
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".wav",
        ".mp3",
        ".flac",
        ".m4a",
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".onnx",
        ".safetensors",
        ".ckpt",
        ".pt",
        ".bin",
        ".gguf",
    }
)

TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".md",
        ".json",
        ".toml",
        ".txt",
        ".yml",
        ".yaml",
        ".cfg",
        ".ini",
        ".ps1",
        ".sh",
        ".example",
        ".srt",
        ".gitignore",
    }
)


def _tracked_files() -> list[Path]:
    """File Git đang theo dõi + file mới chưa bị ignore (tức là sẽ vào commit tới)."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("không có git trên PATH")
    result = subprocess.run(  # noqa: S603 - đường dẫn git đã giải, tham số cố định
        [git, "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("không chạy được git ls-files")
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line.strip()]


def test_git_dang_theo_doi_file(tmp_path: Path) -> None:
    assert _tracked_files(), "phải có file để quét, nếu không test này vô nghĩa"


def test_khong_co_secret_trong_file_se_vao_git() -> None:
    vi_pham: list[str] = []
    for path in _tracked_files():
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        if path.name == Path(__file__).name:
            continue  # file này chứa chính các mẫu regex
        content = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                vi_pham.append(f"{path.relative_to(REPO_ROOT)}: {label}")
    assert not vi_pham, "Phát hiện secret: " + "; ".join(vi_pham)


def test_khong_co_media_hay_model_trong_git() -> None:
    vi_pham = [
        str(path.relative_to(REPO_ROOT))
        for path in _tracked_files()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    assert not vi_pham, "Media/model không được vào Git: " + ", ".join(vi_pham)


def test_env_that_khong_nam_trong_git() -> None:
    tracked = {path.name for path in _tracked_files()}
    assert ".env" not in tracked
    assert ".env.example" in tracked, "phải có file mẫu để người dùng biết cần biến gì"


def test_gitignore_loai_tru_dung_thu() -> None:
    lines = {
        line.strip() for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    for must in (".env", "runtime/", "*.wav", "*.mp4", ".venv/"):
        assert must in lines, f".gitignore thiếu {must}"


def test_env_example_chi_chua_gia_tri_gia() -> None:
    """Brief §4: ``.env.example`` chỉ được chứa tên biến và giá trị giả."""
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    for _, pattern in SECRET_PATTERNS:
        assert not pattern.search(content)
    assert "AIVA_VIDEO_API_KEY" in content
    assert "REPLACE_ME" in content


def test_khong_hardcode_khoa_trong_source() -> None:
    """Không được gán trực tiếp giá trị cho biến tên kiểu api_key/token/secret."""
    gan_truc_tiep = re.compile(
        r"""(?ix)
        \b (api[_-]?key | secret | token | password | passwd)
        \s* [=:] \s*
        ["'] [A-Za-z0-9_\-]{16,} ["']
        """
    )
    vi_pham: list[str] = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        if gan_truc_tiep.search(path.read_text(encoding="utf-8")):
            vi_pham.append(str(path.relative_to(REPO_ROOT)))
    assert not vi_pham, "Có vẻ hardcode khoá: " + ", ".join(vi_pham)


def test_source_khong_doc_gia_tri_bien_secret() -> None:
    """Chỉ được kiểm tra sự tồn tại của biến secret, không được đọc giá trị."""
    from ai_video_agent.config import SECRET_ENV_NAMES

    ten_bien = "|".join(re.escape(name) for name in SECRET_ENV_NAMES)
    doc_gia_tri = re.compile(rf"""os\.environ(?:\.get)?\s*[\[(]\s*["'](?:{ten_bien})["']""")
    for path in (REPO_ROOT / "src").rglob("*.py"):
        assert not doc_gia_tri.search(path.read_text(encoding="utf-8")), path


def test_khong_co_thu_muc_du_lieu_that_trong_repo() -> None:
    for cam in ("runtime", "projects", "outputs", "renders", "models", "voice-samples"):
        assert not (REPO_ROOT / cam).exists(), f"{cam}/ phải nằm ngoài repo"
