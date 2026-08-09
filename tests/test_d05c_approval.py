"""D05-C — cổng duyệt của con người trước composer cuối."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_video_agent.errors import BrollQcFailedError, HumanApprovalRequiredError
from ai_video_agent.qc.approval import (
    APPROVED,
    REJECTED,
    assert_shot_approved,
    record_human_decision,
)
from ai_video_agent.qc.broll import sha256_of


def _write(
    path: Path,
    verdict: str,
    approval: object,
    *,
    clip: Path | None = None,
    clip_sha256: str | None = None,
) -> Path:
    """Ghi báo cáo QC. Mặc định tạo clip thật và băm đúng, để test tách bạch
    được 'chưa duyệt' với 'clip đã đổi'."""
    if clip is None:
        clip = path.parent / "broll.mp4"
        clip.write_bytes(b"noi dung clip goc")
    payload = {
        "clip_path": str(clip),
        "clip_sha256": clip_sha256 if clip_sha256 is not None else sha256_of(clip),
        "verdict": verdict,
        "human_approval": approval,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# --- 16. Không có HUMAN_APPROVED thì composer từ chối ---------------------


def test_chua_ai_duyet_thi_bi_chan(tmp_path: Path) -> None:
    report = _write(tmp_path / "qc.json", "PASS", None)
    with pytest.raises(HumanApprovalRequiredError, match="chưa có người duyệt"):
        assert_shot_approved(report)


def test_qc_pass_khong_tu_dong_thanh_approved(tmp_path: Path) -> None:
    """PASS chỉ nghĩa là không đo được lỗi, không phải là duyệt thẩm mỹ."""
    report = _write(tmp_path / "qc.json", "PASS", None)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["human_approval"] is None
    with pytest.raises(HumanApprovalRequiredError):
        assert_shot_approved(report)


def test_qc_fail_thi_bi_chan_ke_ca_khi_da_tra_tien(tmp_path: Path) -> None:
    report = _write(tmp_path / "qc.json", "FAIL", None)
    with pytest.raises(BrollQcFailedError, match="kể cả khi đã trả tiền"):
        assert_shot_approved(report)


def test_qc_fail_van_bi_chan_du_co_nguoi_duyet(tmp_path: Path) -> None:
    """QC có quyền phủ quyết; người không ghi đè được một FAIL của máy."""
    report = _write(tmp_path / "qc.json", "FAIL", APPROVED)
    with pytest.raises(BrollQcFailedError):
        assert_shot_approved(report)


def test_bi_tu_choi_thi_bi_chan(tmp_path: Path) -> None:
    report = _write(tmp_path / "qc.json", "PASS", REJECTED)
    with pytest.raises(HumanApprovalRequiredError):
        assert_shot_approved(report)


def test_thieu_bao_cao_qc_thi_bi_chan(tmp_path: Path) -> None:
    with pytest.raises(HumanApprovalRequiredError, match="Thiếu báo cáo QC"):
        assert_shot_approved(tmp_path / "khong-ton-tai.json")


def test_co_nguoi_duyet_thi_qua(tmp_path: Path) -> None:
    report = _write(tmp_path / "qc.json", "PASS", None)
    record_human_decision(
        report, decision=APPROVED, decided_by="PO", decided_at="2026-08-07T00:00:00Z"
    )
    assert_shot_approved(report)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["human_approval"] == APPROVED
    assert data["approved_by"] == "PO"


# --- Fail-closed theo verdict: chỉ PASS mới được đi tiếp -----------------


@pytest.mark.parametrize(
    "verdict",
    ["", "WARN", "UNKNOWN", "pass ", "PASSED", "OK", "None", "0", "warn", "SKIP"],
)
def test_verdict_khong_phai_PASS_thi_bi_chan(tmp_path: Path, verdict: str) -> None:
    """Approval đúng, hash đúng, nhưng verdict không phải PASS ⇒ vẫn chặn.

    Đây là lỗ hổng của bản trước: cổng chỉ chặn ``FAIL``, nên một báo cáo hỏng
    hoặc bị sửa tay thành ``WARN`` vẫn đi tới composer.
    """
    report = _write(tmp_path / "qc.json", verdict, APPROVED)
    with pytest.raises(HumanApprovalRequiredError, match="không phải 'PASS'"):
        assert_shot_approved(report)


def test_thieu_han_truong_verdict_thi_bi_chan(tmp_path: Path) -> None:
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"noi dung")
    report = tmp_path / "qc.json"
    report.write_text(
        json.dumps(
            {
                "clip_path": str(clip),
                "clip_sha256": sha256_of(clip),
                "human_approval": APPROVED,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(HumanApprovalRequiredError, match=r"\(thiếu\)"):
        assert_shot_approved(report)


def test_PASS_kem_approved_va_hash_dung_thi_qua(tmp_path: Path) -> None:
    report = _write(tmp_path / "qc.json", "PASS", APPROVED)
    assert_shot_approved(report)


def test_verdict_pass_chu_thuong_van_duoc_chap_nhan(tmp_path: Path) -> None:
    """Chuẩn hoá hoa/thường là hợp lý; nới lỏng ngữ nghĩa thì không."""
    report = _write(tmp_path / "qc.json", "pass", APPROVED)
    assert_shot_approved(report)


def test_verdict_khong_phai_PASS_duoc_xet_TRUOC_phe_duyet(tmp_path: Path) -> None:
    """Chưa ai duyệt VÀ verdict lạ ⇒ lỗi phải nói về verdict, không phải phê duyệt."""
    report = _write(tmp_path / "qc.json", "WARN", None)
    with pytest.raises(HumanApprovalRequiredError, match="verdict"):
        assert_shot_approved(report)


# --- Toàn vẹn: băm được tính LẠI ngay trước composer ---------------------


def test_thieu_clip_sha256_thi_bi_chan(tmp_path: Path) -> None:
    """Không có băm thì không kiểm chứng được clip có bị đổi hay không."""
    report = _write(tmp_path / "qc.json", "PASS", APPROVED, clip_sha256="")
    with pytest.raises(HumanApprovalRequiredError, match="thiếu clip_sha256"):
        assert_shot_approved(report)


def test_clip_doi_mot_byte_sau_khi_duyet_thi_bi_chan(tmp_path: Path) -> None:
    """Đúng ca nguy hiểm: đã duyệt rồi file bị thay."""
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"noi dung clip goc")
    report = _write(tmp_path / "qc.json", "PASS", APPROVED, clip=clip)
    assert_shot_approved(report)  # còn nguyên thì qua

    clip.write_bytes(b"noi dung clip goc!")  # đổi đúng một byte
    with pytest.raises(HumanApprovalRequiredError, match="đã ĐỔI sau khi được duyệt"):
        assert_shot_approved(report)


def test_clip_bien_mat_thi_bi_chan(tmp_path: Path) -> None:
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"x")
    report = _write(tmp_path / "qc.json", "PASS", APPROVED, clip=clip)
    clip.unlink()
    with pytest.raises(HumanApprovalRequiredError, match="Không tìm thấy clip"):
        assert_shot_approved(report)


def test_bam_lai_tai_cho_chu_khong_tin_bao_cao(tmp_path: Path) -> None:
    """Báo cáo khai một băm bịa ⇒ vẫn bị bắt, vì băm được tính lại tại đây."""
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"that")
    report = _write(tmp_path / "qc.json", "PASS", APPROVED, clip=clip, clip_sha256="0" * 64)
    with pytest.raises(HumanApprovalRequiredError, match="đã ĐỔI"):
        assert_shot_approved(report)


def test_bao_cao_hong_thi_bi_chan(tmp_path: Path) -> None:
    report = tmp_path / "qc.json"
    report.write_text("{khong phai json", encoding="utf-8")
    with pytest.raises(HumanApprovalRequiredError, match="không đọc được"):
        assert_shot_approved(report)


def test_quyet_dinh_la_bi_tu_choi(tmp_path: Path) -> None:
    report = _write(tmp_path / "qc.json", "PASS", None)
    with pytest.raises(ValueError, match="Quyết định không hợp lệ"):
        record_human_decision(
            report, decision="co-le-duoc", decided_by="PO", decided_at="2026-08-07T00:00:00Z"
        )
