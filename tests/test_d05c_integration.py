"""D05-C — hai đường nối vào lifecycle thật.

Nhóm test này tồn tại vì audit của PO chỉ ra đúng hai lỗ hổng:

1. ``assert_shot_approved()`` trước đây **chỉ được test gọi**, không đường
   production nào gọi tới. Nay nó nằm trong ``RenderPipeline._compose``.
2. ``serialization.py`` trước đây **không được SubmissionMachine dùng**, nên
   test serializer tách rời không chứng minh được điều cần chứng minh: lỗi
   usage/report không làm mất ``operation_name`` hay file kết quả.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_video_agent.errors import (
    BrollQcFailedError,
    HumanApprovalRequiredError,
    ProviderError,
)
from ai_video_agent.orchestrator.pipeline import Pipeline
from ai_video_agent.providers.video_api.capability import VEO_STANDARD
from ai_video_agent.providers.video_api.fake import FakeVideoTransport
from ai_video_agent.providers.video_api.submission import (
    SubmissionMachine,
    SubmissionState,
    SubmissionStore,
)
from ai_video_agent.qc.approval import APPROVED, REJECTED, qc_report_path_for
from ai_video_agent.qc.broll import sha256_of

# =========================================================================
# B. Cổng QC + HUMAN_APPROVED nằm trên đường composer thật
# =========================================================================


def test_cong_duyet_duoc_goi_tu_pipeline_chu_khong_chi_tu_test() -> None:
    """Bằng chứng tĩnh: ``_compose`` gọi cổng, và cổng được import vào pipeline."""
    source = Path("src/ai_video_agent/orchestrator/pipeline.py").read_text(encoding="utf-8")
    assert "from ai_video_agent.qc.approval import" in source
    assert "_assert_paid_broll_approved" in source
    # cổng phải được gọi TRƯỚC khi dựng concat cho composer
    gate_at = source.index("self._assert_paid_broll_approved(artifacts)")
    concat_at = source.index("build_concat_file(")
    assert gate_at < concat_at, "cổng phải chạy trước khi dựng concat"


class _Artifact:
    """Artifact mang **provenance của run**, không mang cấu hình hiện tại."""

    def __init__(self, broll: Path | None, *, requires_approval: bool = True) -> None:
        self.broll = broll
        self.broll_requires_approval = requires_approval


class _PipelineStub:
    """Mượn ĐÚNG phương thức cổng của ``Pipeline`` thật.

    Cố ý không dựng cả pipeline: điều cần chứng minh là hàm cổng **của
    production** hành xử đúng, chứ không phải một bản sao trong test.

    ``providers = None`` là chủ ý: sau FIX 5, cổng không được phép hỏi provider
    hiện tại. Nếu nó còn hỏi, mọi test dưới đây sẽ nổ ngay.
    """

    providers = None

    _assert_paid_broll_approved = Pipeline._assert_paid_broll_approved


def _write_qc(clip: Path, verdict: str, approval: object) -> Path:
    report = qc_report_path_for(clip)
    report.write_text(
        json.dumps(
            {
                "clip_path": str(clip),
                "clip_sha256": sha256_of(clip),
                "verdict": verdict,
                "human_approval": approval,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report


def test_broll_tra_phi_thieu_bao_cao_qc_thi_composer_bi_chan(tmp_path: Path) -> None:
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"x")
    stub = _PipelineStub()
    with pytest.raises(HumanApprovalRequiredError, match="Thiếu báo cáo QC"):
        stub._assert_paid_broll_approved([_Artifact(clip)])


def test_broll_tra_phi_qc_fail_thi_composer_bi_chan(tmp_path: Path) -> None:
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"x")
    _write_qc(clip, "FAIL", None)
    stub = _PipelineStub()
    with pytest.raises(BrollQcFailedError):
        stub._assert_paid_broll_approved([_Artifact(clip)])


def test_qc_pass_nhung_chua_ai_duyet_thi_composer_bi_chan(tmp_path: Path) -> None:
    """PASS **không** tự duyệt — đây là ràng buộc trung tâm của D05-C."""
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"x")
    _write_qc(clip, "PASS", None)
    stub = _PipelineStub()
    with pytest.raises(HumanApprovalRequiredError, match="chưa có người duyệt"):
        stub._assert_paid_broll_approved([_Artifact(clip)])


def test_bi_nguoi_tu_choi_thi_composer_bi_chan(tmp_path: Path) -> None:
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"x")
    _write_qc(clip, "PASS", REJECTED)
    stub = _PipelineStub()
    with pytest.raises(HumanApprovalRequiredError):
        stub._assert_paid_broll_approved([_Artifact(clip)])


def test_da_duyet_thi_di_qua(tmp_path: Path) -> None:
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"x")
    _write_qc(clip, "PASS", APPROVED)
    stub = _PipelineStub()
    stub._assert_paid_broll_approved([_Artifact(clip)])


def test_duong_duix_vieneu_local_khong_bi_cong_nay_dung_toi(tmp_path: Path) -> None:
    """Artifact sinh bởi provider không tính tiền ⇒ không áp cổng. D04 không đổi."""
    clip = tmp_path / "broll.mock.mp4"
    clip.write_bytes(b"x")
    stub = _PipelineStub()
    stub._assert_paid_broll_approved([_Artifact(clip, requires_approval=False)])


def test_provenance_thang_cau_hinh_hien_tai(tmp_path: Path) -> None:
    """Điểm mấu chốt của FIX 5.

    Cổng chạy trên một stub có ``providers = None`` — tức không có cách nào hỏi
    "provider hiện tại có tính tiền không". Nó vẫn phải chặn, vì artifact mang
    dấu ``requires_approval=True`` từ lúc run gốc sinh ra nó.
    """
    clip = tmp_path / "broll.mp4"
    clip.write_bytes(b"da tra tien cho clip nay")
    _write_qc(clip, "PASS", None)
    stub = _PipelineStub()
    assert stub.providers is None
    with pytest.raises(HumanApprovalRequiredError):
        stub._assert_paid_broll_approved([_Artifact(clip, requires_approval=True)])


def test_khong_co_broll_provider_thi_khong_chan_gi(tmp_path: Path) -> None:
    del tmp_path
    stub = _PipelineStub()
    stub._assert_paid_broll_approved([_Artifact(None)])


# =========================================================================
# C. Serializer nằm trong lifecycle của SubmissionMachine
# =========================================================================


class _Hostile:
    """Usage không repr được và không chuẩn hoá được — ép mọi nhánh lỗi cùng lúc."""

    def __repr__(self) -> str:
        msg = "repr hong"
        raise RuntimeError(msg)

    @property
    def __dict__(self) -> dict[str, object]:  # type: ignore[override]
        msg = "khong doc duoc"
        raise RuntimeError(msg)


def _machine(tmp: Path, transport: FakeVideoTransport) -> SubmissionMachine:
    return SubmissionMachine(store=SubmissionStore(tmp / "submission.json"), transport=transport)


def test_usage_duoc_persist_qua_lifecycle_chu_khong_phai_test_roi_rac(tmp_path: Path) -> None:
    transport = FakeVideoTransport(usage_payload={"output_tokens": 46336})
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    machine.poll_until_done(record)

    # raw ghi TRƯỚC chuẩn hoá, cả hai đều nằm cạnh bản ghi
    assert (tmp_path / "submission.usage.raw.txt").is_file()
    assert (tmp_path / "submission.usage.json").is_file()
    saved = SubmissionStore(tmp_path / "submission.json").load()
    assert saved.raw_usage_repr is not None
    assert saved.usage is not None


def test_usage_hong_khong_lam_mat_operation_name(tmp_path: Path) -> None:
    """Đúng kịch bản D05-B, nhưng lần này ``operation_name`` phải sống sót."""
    transport = FakeVideoTransport(usage_payload=_Hostile())
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    machine.poll_until_done(record)

    saved = SubmissionStore(tmp_path / "submission.json").load()
    assert saved.operation_name == transport.operation_name, "operation_name KHÔNG được mất"
    assert saved.state != SubmissionState.SUBMISSION_UNKNOWN.value


def test_usage_hong_khong_lam_mat_file_ket_qua_da_tai(tmp_path: Path) -> None:
    """Video đã trả tiền phải còn nguyên dù báo cáo usage hỏng."""
    transport = FakeVideoTransport(usage_payload=_Hostile())
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    out = tmp_path / "broll.mp4"
    record = machine.download(record, out)
    machine.poll_until_done(record)

    assert out.is_file(), "file kết quả đã trả tiền KHÔNG được mất"
    saved = SubmissionStore(tmp_path / "submission.json").load()
    assert saved.result_path == str(out)
    assert saved.operation_name == transport.operation_name


def test_usage_hong_thi_ghi_ly_do_vao_note_chu_khong_nem_loi(tmp_path: Path) -> None:
    transport = FakeVideoTransport(usage_payload=_Hostile())
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    machine.poll_until_done(record)  # không được ném lỗi
    saved = SubmissionStore(tmp_path / "submission.json").load()
    assert saved.raw_usage_repr is not None


def test_download_hong_khong_lam_mat_operation_name(tmp_path: Path) -> None:
    transport = FakeVideoTransport(fail_download_times=99)
    machine = _machine(tmp_path, transport)
    record = machine.submit_once(
        submission_id="s1", model_id=VEO_STANDARD, payload={}, idempotency_key="k"
    )
    with pytest.raises(ProviderError):
        machine.download(record, tmp_path / "broll.mp4")

    saved = SubmissionStore(tmp_path / "submission.json").load()
    assert saved.operation_name == transport.operation_name
    assert transport.counter.submit == 1, "download hỏng KHÔNG được kéo theo submit lại"
