"""Cổng duyệt của con người trước composer cuối.

Một shot sinh bằng model chỉ được vào composer khi ở trạng thái
``HUMAN_APPROVED``. Không có đường tắt nào biến ``PASS`` của QC tự động thành
``approved`` — máy không có quyền đó (D05-C §7.5).
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_video_agent.errors import BrollQcFailedError, HumanApprovalRequiredError
from ai_video_agent.qc.broll import sha256_of

APPROVED = "approved"
REJECTED = "rejected"

#: Hai giá trị verdict duy nhất có ý nghĩa ở cổng này. Mọi giá trị khác —
#: kể cả ``WARN`` — đều được coi là "chưa xác định" và bị chặn.
VERDICT_PASS = "PASS"  # noqa: S105 - phán quyết QC, không phải mật khẩu
VERDICT_FAIL = "FAIL"

#: Đuôi của báo cáo QC đi kèm một clip: ``broll.mp4`` -> ``broll.qc.json``.
QC_REPORT_SUFFIX = ".qc.json"


def qc_report_path_for(clip: Path) -> Path:
    """Đường dẫn báo cáo QC đi kèm một clip, đặt cạnh chính clip đó."""
    return clip.with_suffix(QC_REPORT_SUFFIX)


def assert_shot_approved(qc_report_path: Path, clip_path: Path | None = None) -> None:
    """Cho qua **chỉ khi** ``verdict == "PASS"`` VÀ ``human_approval == "approved"``
    VÀ clip còn nguyên như lúc được duyệt.

    Hợp đồng là danh sách trắng, không phải danh sách đen: mọi trạng thái nằm
    ngoài ba điều kiện trên đều bị chặn, kể cả những trạng thái chưa ai nghĩ tới.

    Băm được tính lại **tại đây**, ngay trước composer — không tin vào con số đã
    ghi lúc QC chạy. Người duyệt một clip cụ thể; nếu file đổi dù chỉ một byte
    giữa lúc duyệt và lúc ghép, phê duyệt đó không còn nói về thứ sắp được dùng.

    Ném :class:`BrollQcFailedError` nếu QC tự động đã từ chối, hoặc
    :class:`HumanApprovalRequiredError` cho mọi trường hợp còn lại.
    """
    if not qc_report_path.is_file():
        msg = (
            f"Thiếu báo cáo QC tại {qc_report_path}. "
            "Shot sinh bằng model không được vào composer khi chưa qua QC."
        )
        raise HumanApprovalRequiredError(msg)

    try:
        data = json.loads(qc_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Báo cáo QC tại {qc_report_path} không đọc được: {exc}."
        raise HumanApprovalRequiredError(msg) from exc

    verdict = str(data.get("verdict", "")).upper()
    approval = data.get("human_approval")

    if verdict == VERDICT_FAIL:
        msg = (
            f"QC tự động đã TỪ CHỐI clip {data.get('clip_path')}. "
            "Clip không được vào composer kể cả khi đã trả tiền cho nó."
        )
        raise BrollQcFailedError(msg)

    # Fail-closed: chỉ ĐÚNG ``PASS`` mới được đi tiếp. Thiếu trường, chuỗi rỗng,
    # ``WARN``, hay bất kỳ giá trị lạ nào đều là "không biết clip có đạt không" —
    # và không biết thì không ghép. Trước đây chỉ chặn ``FAIL``, nên một báo cáo
    # hỏng hoặc bị sửa tay thành ``WARN`` vẫn lọt tới composer nếu có phê duyệt.
    if verdict != VERDICT_PASS:
        shown = verdict or "(thiếu)"
        msg = (
            f"Báo cáo QC {qc_report_path} có verdict={shown!r}, không phải "
            f"{VERDICT_PASS!r}. Chỉ clip đã qua QC với verdict PASS mới được vào "
            "composer. Chạy lại QC cho clip này."
        )
        raise HumanApprovalRequiredError(msg)

    # Chỉ tới đây — sau khi verdict đã được xác nhận PASS — mới xét phê duyệt.
    if approval != APPROVED:
        msg = (
            f"Shot chưa có người duyệt (human_approval={approval!r}). "
            "QC tự động chỉ có quyền từ chối; PASS không phải là duyệt thẩm mỹ. "
            "Chạy 'aiva broll approve' sau khi xem clip."
        )
        raise HumanApprovalRequiredError(msg)

    _assert_clip_unchanged(data, qc_report_path, clip_path)


def _assert_clip_unchanged(
    data: dict[str, object], qc_report_path: Path, clip_path: Path | None
) -> None:
    """Băm lại clip hiện hữu và so với băm đã ghi trong báo cáo QC."""
    target = clip_path or Path(str(data.get("clip_path", "")))
    if not str(target):
        msg = f"Báo cáo QC {qc_report_path} không cho biết clip nào đã được duyệt."
        raise HumanApprovalRequiredError(msg)

    recorded = str(data.get("clip_sha256") or "")
    if not recorded:
        msg = (
            f"Báo cáo QC {qc_report_path} thiếu clip_sha256 nên không kiểm chứng được "
            "clip có bị đổi sau khi duyệt hay không. Chạy lại QC."
        )
        raise HumanApprovalRequiredError(msg)

    if not target.is_file():
        msg = (
            f"Không tìm thấy clip đã duyệt tại {target}. "
            "Không ghép từ artifact thiếu."
        )
        raise HumanApprovalRequiredError(msg)

    actual = sha256_of(target)
    if actual != recorded:
        msg = (
            f"Clip {target.name} đã ĐỔI sau khi được duyệt "
            f"(đã duyệt {recorded[:16]}…, hiện tại {actual[:16]}…). "
            "Phê duyệt cũ không còn hiệu lực — chạy lại QC và duyệt lại."
        )
        raise HumanApprovalRequiredError(msg)


def record_human_decision(
    qc_report_path: Path, *, decision: str, decided_by: str, decided_at: str
) -> None:
    """Ghi quyết định của con người vào báo cáo QC."""
    if decision not in {APPROVED, REJECTED}:
        msg = f"Quyết định không hợp lệ: {decision!r}. Chỉ nhận {APPROVED!r} hoặc {REJECTED!r}."
        raise ValueError(msg)

    data = json.loads(qc_report_path.read_text(encoding="utf-8"))
    data["human_approval"] = decision
    data["approved_by"] = decided_by
    data["approved_at"] = decided_at
    qc_report_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
