"""Brief tiếng Việt -> ``storyboard.json``.

D01 dùng :class:`RuleBasedPlanner`: hoàn toàn offline, tất định (deterministic),
không gọi LLM và không tốn tiền. Nó đủ để chứng minh toàn bộ hợp đồng dữ liệu và
đường đi của pipeline chạy được.

Ở vận hành thật, Claude Code mới là bộ lập kịch bản (brief §1.1). Vì
:class:`Planner` là một Protocol nên chỉ cần cắm ``ClaudePlanner`` vào chỗ này,
phần còn lại của hệ thống không phải sửa gì.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_video_agent.domain.enums import AspectRatio, BrollKind, OnScreenTextKind, SceneRole
from ai_video_agent.domain.storyboard import BrollPlan, OnScreenText, Scene, Shot, Storyboard
from ai_video_agent.errors import ValidationError
from ai_video_agent.orchestrator.textutil import ExactText, extract_exact_texts, split_sentences

#: Thời lượng mong muốn của một shot, dùng để suy ra số shot cần có.
TARGET_SHOT_SEC = 5.0
MIN_SHOT_SEC = 1.5
MAX_SHOT_SEC = 12.0
#: Tối thiểu hook + body + CTA.
MIN_SHOTS = 3


class Planner(Protocol):
    """Bất cứ thứ gì biến brief thành storyboard."""

    def plan(
        self,
        *,
        project_id: str,
        brief_vi: str,
        target_duration_sec: float,
        aspect_ratio: AspectRatio,
    ) -> Storyboard: ...


@dataclass
class RuleBasedPlanner:
    """Bộ lập kịch bản offline theo luật, dùng cho D01 và cho test."""

    target_shot_sec: float = TARGET_SHOT_SEC
    min_shot_sec: float = MIN_SHOT_SEC
    max_shot_sec: float = MAX_SHOT_SEC
    cta_text: str = "Liên hệ ngay để được tư vấn"

    def plan(
        self,
        *,
        project_id: str,
        brief_vi: str,
        target_duration_sec: float,
        aspect_ratio: AspectRatio = AspectRatio.VERTICAL,
    ) -> Storyboard:
        sentences = split_sentences(brief_vi)
        if not sentences:
            msg = "Brief rỗng: không tách được câu nào để dựng kịch bản."
            raise ValidationError(msg)

        groups = self._group_sentences(sentences, target_duration_sec)
        durations = self._allocate_durations(groups, target_duration_sec)
        exact_texts = extract_exact_texts(brief_vi)

        shots = [
            self._build_shot(index=i, text=text, duration=duration, exact_texts=exact_texts)
            for i, (text, duration) in enumerate(zip(groups, durations, strict=True))
        ]
        scenes = self._build_scenes(shots)

        return Storyboard(
            project_id=project_id,
            aspect_ratio=aspect_ratio,
            scenes=scenes,
        )

    # ----- chia câu thành shot -------------------------------------------------

    def _group_sentences(self, sentences: list[str], target_duration_sec: float) -> list[str]:
        """Gộp câu thành đúng số shot phù hợp với thời lượng mục tiêu.

        Ít câu hơn số shot mong muốn thì giữ nguyên; nhiều câu quá thì gộp lại để
        không sinh ra hàng chục shot chớp nhoáng.
        """
        wanted = max(MIN_SHOTS, round(target_duration_sec / self.target_shot_sec))
        count = min(wanted, len(sentences))
        if count >= len(sentences):
            return list(sentences)

        total_chars = sum(len(s) for s in sentences)
        per_shot = total_chars / count
        groups: list[list[str]] = [[] for _ in range(count)]
        index = 0
        running = 0
        for sentence in sentences:
            groups[index].append(sentence)
            running += len(sentence)
            remaining_groups = count - index - 1
            remaining_sentences = len(sentences) - sum(len(g) for g in groups)
            # Sang nhóm kế tiếp khi đã đủ "phần" của nhóm hiện tại, nhưng luôn
            # chừa đủ câu để mọi nhóm còn lại có ít nhất một câu.
            if index < count - 1 and (
                running >= per_shot * (index + 1) or remaining_sentences <= remaining_groups
            ):
                index += 1
        return [" ".join(group) for group in groups if group]

    # ----- chia thời lượng -----------------------------------------------------

    def _allocate_durations(self, groups: list[str], target_duration_sec: float) -> list[float]:
        """Chia thời lượng theo độ dài chữ, kẹp trong [min, max] rồi cân lại tổng."""
        weights = [max(1, len(text)) for text in groups]
        total_weight = sum(weights)
        durations = [target_duration_sec * w / total_weight for w in weights]

        for _ in range(4):
            durations = [min(self.max_shot_sec, max(self.min_shot_sec, d)) for d in durations]
            residual = target_duration_sec - sum(durations)
            if abs(residual) < 1e-6:
                break
            adjustable = [
                i
                for i, d in enumerate(durations)
                if (residual > 0 and d < self.max_shot_sec)
                or (residual < 0 and d > self.min_shot_sec)
            ]
            if not adjustable:
                break
            share = residual / len(adjustable)
            for i in adjustable:
                durations[i] += share

        return [round(min(self.max_shot_sec, max(self.min_shot_sec, d)), 3) for d in durations]

    # ----- dựng shot / scene ---------------------------------------------------

    def _build_shot(
        self,
        *,
        index: int,
        text: str,
        duration: float,
        exact_texts: list[ExactText],
    ) -> Shot:
        on_screen = [
            OnScreenText(text=item.text, kind=item.kind, start_offset_sec=0.0, exact=True)
            for item in exact_texts
            if self._belongs_to(item, text)
        ]
        return Shot(
            id=f"shot-{index + 1:03d}",
            order=index,
            duration_sec=duration,
            narration_vi=text,
            on_screen_text=on_screen,
            broll=BrollPlan(kind=BrollKind.NONE),
            provider_hint="duix",
            subtitle=True,
        )

    @staticmethod
    def _belongs_to(item: ExactText, shot_text: str) -> bool:
        """Chuỗi chính xác có thuộc về shot này không.

        Số điện thoại được so bằng chữ số vì bản trích đã bỏ dấu cách/chấm, còn
        giá và cụm pháp lý so nguyên văn để tránh khớp nhầm những con số rời rạc.
        """
        if item.kind is OnScreenTextKind.PHONE:
            digits = "".join(ch for ch in shot_text if ch.isdigit())
            return item.text.lstrip("+") in digits
        return item.text.casefold() in shot_text.casefold()

    def _build_scenes(self, shots: list[Shot]) -> list[Scene]:
        """Bọc shot vào cấu trúc hook / body / CTA của video ngắn."""
        if len(shots) < MIN_SHOTS:
            return [Scene(id="scene-01", title="Nội dung chính", role=SceneRole.BODY, shots=shots)]

        cta_shot = shots[-1]
        if not any(t.kind is OnScreenTextKind.CTA for t in cta_shot.on_screen_text):
            cta_shot.on_screen_text = [
                *cta_shot.on_screen_text,
                OnScreenText(text=self.cta_text, kind=OnScreenTextKind.CTA, exact=True),
            ]

        return [
            Scene(id="scene-01", title="Mở đầu", role=SceneRole.HOOK, shots=[shots[0]]),
            Scene(id="scene-02", title="Nội dung", role=SceneRole.BODY, shots=shots[1:-1]),
            Scene(id="scene-03", title="Kêu gọi hành động", role=SceneRole.CTA, shots=[cta_shot]),
        ]
