"""Tiện ích xử lý văn bản tiếng Việt cho planner.

Ba việc: tạo slug ID không dấu, tách câu đúng cách với chữ viết tắt tiếng Việt,
và trích các chuỗi **phải chính xác tuyệt đối** (số điện thoại, giá, pháp lý).

Nhóm cuối quan trọng vì brief §D04.2 quy định những chuỗi này do composer chèn
bằng FFmpeg, không giao cho model sinh video tự vẽ — vẽ sai một chữ số điện
thoại hay một con số giá là sai nghiêm trọng.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ai_video_agent.domain.enums import OnScreenTextKind

#: Viết tắt tiếng Việt thường gặp — không được coi dấu chấm sau chúng là hết câu.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "tp",
        "q",
        "p",
        "kp",
        "tt",
        "đt",
        "ql",
        "kcn",
        "kdc",
        "tx",
        "h",
        "x",
        "ts",
        "ths",
        "pgs",
        "gs",
        "bs",
        "ks",
        "vd",
        "vn",
        "hcm",
        "tphcm",
        "st",
        "no",
        "nr",
        "đc",
        "sđt",
        "cty",
        "tnhh",
        "cp",
    }
)

_SENTENCE_BREAK = re.compile(r"([.!?;])(\s+|$)")
_WHITESPACE = re.compile(r"\s+")

#: Số điện thoại Việt Nam: bắt đầu bằng 0 hoặc +84, cho phép dấu cách/chấm/gạch.
PHONE_RE = re.compile(r"(?<![\d+])(?:\+84|0)(?:[\s.\-]?\d){8,10}(?!\d)")

#: Giá tiền: "1,2 tỷ", "850 triệu", "35tr/m2", "2.500.000 đ", "1200 USD".
#: Lookahead ``(?!\w)`` chặn khớp nhầm kiểu "5 kg" -> "5 k".
PRICE_RE = re.compile(
    r"(?<!\w)\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\s*"
    r"(?:tỷ|tỉ|triệu|tr|nghìn|ngàn|k|đồng|đ|vnđ|vnd|usd)"
    r"(?!\w)"
    r"(?:\s*/\s*[\w²]+)?",
    re.IGNORECASE,
)

#: Cụm từ pháp lý phải hiển thị nguyên văn, không được diễn đạt lại.
LEGAL_PHRASES: tuple[str, ...] = (
    "sổ hồng riêng",
    "sổ hồng",
    "sổ đỏ",
    "sổ chung",
    "thổ cư",
    "đất ở đô thị",
    "đất ở nông thôn",
    "công chứng",
    "sang tên",
    "quy hoạch",
    "giấy phép xây dựng",
    "pháp lý rõ ràng",
    "shr",
)


@dataclass(frozen=True)
class ExactText:
    """Một chuỗi bắt buộc hiển thị nguyên văn, kèm loại của nó."""

    text: str
    kind: OnScreenTextKind


def strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt, giữ lại chữ cái Latin cơ bản."""
    replaced = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", replaced)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def slugify(text: str, *, max_length: int = 48, fallback: str = "project") -> str:
    """Chuyển tiêu đề tiếng Việt thành ID hợp lệ cho ``Project.id``."""
    ascii_text = strip_diacritics(text).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:max_length].strip("-")
    if len(slug) < 2:
        return fallback
    return slug


def normalize_spaces(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def split_sentences(text: str) -> list[str]:
    """Tách văn bản thành câu, bỏ qua dấu chấm của chữ viết tắt.

    Ví dụ ``"Nhà ở TP. Biên Hoà. Giá tốt."`` cho ra hai câu chứ không phải ba.
    """
    sentences: list[str] = []
    for block in text.splitlines():
        stripped = block.strip()
        if not stripped:
            continue
        cursor = 0
        for match in _SENTENCE_BREAK.finditer(stripped):
            candidate = stripped[cursor : match.end(1)]
            last_word = re.split(r"[\s(\[]", candidate.rstrip(".!?;"))[-1].lower()
            if match.group(1) == "." and last_word in ABBREVIATIONS:
                continue
            piece = normalize_spaces(candidate)
            if piece:
                sentences.append(piece)
            cursor = match.end()
        tail = normalize_spaces(stripped[cursor:])
        if tail:
            sentences.append(tail)
    return sentences


def _dedupe_keep_order(items: list[ExactText]) -> list[ExactText]:
    seen: set[str] = set()
    result: list[ExactText] = []
    for item in items:
        key = item.text.casefold()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def extract_exact_texts(text: str) -> list[ExactText]:
    """Trích số điện thoại, giá và cụm pháp lý cần hiển thị nguyên văn."""
    found: list[ExactText] = []

    for match in PHONE_RE.finditer(text):
        digits = re.sub(r"[^\d+]", "", match.group())
        # Số điện thoại VN hợp lệ: 10 số bắt đầu bằng 0, hoặc +84 kèm 9 số.
        if re.fullmatch(r"0\d{9}", digits) or re.fullmatch(r"\+84\d{9}", digits):
            found.append(ExactText(text=digits, kind=OnScreenTextKind.PHONE))

    for match in PRICE_RE.finditer(text):
        found.append(ExactText(text=normalize_spaces(match.group()), kind=OnScreenTextKind.PRICE))

    # Duyệt cụm dài trước rồi bỏ cụm ngắn nằm trong cụm đã lấy, để "sổ hồng riêng"
    # không kéo theo "sổ hồng" thành hai dòng chữ trùng ý.
    lowered = text.casefold()
    taken: list[str] = []
    for phrase in sorted(LEGAL_PHRASES, key=len, reverse=True):
        folded = phrase.casefold()
        index = lowered.find(folded)
        if index < 0 or any(folded in already for already in taken):
            continue
        taken.append(folded)
        found.append(ExactText(text=text[index : index + len(phrase)], kind=OnScreenTextKind.LEGAL))

    return _dedupe_keep_order(found)
