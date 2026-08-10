"""把 Markdown 文章解析成中介結構 (IR)。

同一份 IR 會被兩個 renderer 使用：Notion 原生區塊與 WordPress HTML，
確保兩種輸出永遠來自同一份解析結果，不會各自漂移。

只支援文章實際會用到的語法：H2/H3/H4、段落、無序與有序清單、
粗體、斜體、行內程式碼、連結。刻意不做完整的 Markdown 實作。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# 行內語法：程式碼 > 連結 > 粗體 > 斜體（程式碼優先，避免內部符號被誤判）
_INLINE_PATTERN = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)\s]+)\)"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|(?<!\*)\*(?P<italic>[^*]+)\*(?!\*)"
)

_HEADING_PATTERN = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+)$")
_BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+(?P<text>.+)$")
_ORDERED_PATTERN = re.compile(r"^\s*\d+[.)]\s+(?P<text>.+)$")
_QUOTE_PATTERN = re.compile(r"^>\s?(?P<text>.*)$")
_DIVIDER_PATTERN = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")

# 表格：一般列是 | a | b |，分隔列是 |---|:--:| 之類
_TABLE_ROW_PATTERN = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _split_row(line: str) -> List[str]:
    """把 | a | b | 拆成儲存格文字，去掉頭尾的空欄。"""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


@dataclass(frozen=True)
class Span:
    """一段行內文字及其樣式。"""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: str = ""


@dataclass(frozen=True)
class Block:
    """一個區塊層級元素。

    kind: heading_2 / heading_3 / heading_4 / paragraph /
          bulleted_list_item / numbered_list_item / quote / divider / table

    table 使用 rows（每列是一串儲存格，每格是一串 Span），其餘型別使用 spans。
    """

    kind: str
    spans: Tuple[Span, ...] = field(default_factory=tuple)
    rows: Tuple[Tuple[Tuple[Span, ...], ...], ...] = field(default_factory=tuple)
    has_header: bool = False


def parse_inline(text: str) -> Tuple[Span, ...]:
    """把一行文字解析成帶樣式的 Span 序列。"""
    spans: List[Span] = []
    cursor = 0

    for match in _INLINE_PATTERN.finditer(text):
        if match.start() > cursor:
            spans.append(Span(text[cursor:match.start()]))

        if match.group("code") is not None:
            spans.append(Span(match.group("code"), code=True))
        elif match.group("link_text") is not None:
            spans.append(Span(match.group("link_text"), href=match.group("link_url")))
        elif match.group("bold") is not None:
            spans.append(Span(match.group("bold"), bold=True))
        else:
            spans.append(Span(match.group("italic"), italic=True))

        cursor = match.end()

    if cursor < len(text):
        spans.append(Span(text[cursor:]))

    return tuple(span for span in spans if span.text)


def _heading_kind(level: int) -> str:
    # Notion 只有 heading_1~3；文章的 # 保留給標題本身，故 ## 對應 heading_2
    return {1: "heading_2", 2: "heading_2", 3: "heading_3"}.get(level, "heading_3")


def _parse_table(lines: List[str], start: int) -> Tuple[Block, int]:
    """從 start 開始解析表格，回傳 (表格區塊, 下一行索引)。

    呼叫前必須確認 lines[start] 是表頭、lines[start + 1] 是分隔列。
    """
    header = _split_row(lines[start])
    width = len(header)

    rows = [tuple(parse_inline(cell) for cell in header)]
    index = start + 2

    while index < len(lines) and _TABLE_ROW_PATTERN.match(lines[index]):
        cells = _split_row(lines[index])
        # Notion 要求每列寬度一致，不足補空、超出截斷
        normalized = (cells + [""] * width)[:width]
        rows.append(tuple(parse_inline(cell) for cell in normalized))
        index += 1

    return Block("table", rows=tuple(rows), has_header=True), index


def _single_line_block(line: str) -> Optional[Block]:
    """解析只佔一行的區塊（分隔線、標題、清單、引用）；不符合回傳 None。"""
    if _DIVIDER_PATTERN.match(line):
        return Block("divider")

    heading = _HEADING_PATTERN.match(line)
    if heading:
        level = len(heading.group("level"))
        return Block(_heading_kind(level), parse_inline(heading.group("text")))

    bullet = _BULLET_PATTERN.match(line)
    if bullet:
        return Block("bulleted_list_item", parse_inline(bullet.group("text")))

    ordered = _ORDERED_PATTERN.match(line)
    if ordered:
        return Block("numbered_list_item", parse_inline(ordered.group("text")))

    quote = _QUOTE_PATTERN.match(line)
    if quote:
        return Block("quote", parse_inline(quote.group("text")))

    return None


def parse_markdown(markdown: str) -> List[Block]:
    """把 Markdown 解析成 Block 序列。"""
    blocks: List[Block] = []
    paragraph_lines: List[str] = []
    lines = [raw.rstrip() for raw in markdown.splitlines()]

    def flush_paragraph() -> None:
        if paragraph_lines:
            joined = " ".join(line.strip() for line in paragraph_lines)
            blocks.append(Block("paragraph", parse_inline(joined)))
            paragraph_lines.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1

        if not line.strip():
            flush_paragraph()
            continue

        # 表格要先於分隔線判斷：|---|---| 也符合分隔線的樣子
        if (
            _TABLE_ROW_PATTERN.match(line)
            and index < len(lines)
            and _TABLE_SEPARATOR_PATTERN.match(lines[index])
        ):
            flush_paragraph()
            table, index = _parse_table(lines, index - 1)
            blocks.append(table)
            continue

        block = _single_line_block(line)
        if block:
            flush_paragraph()
            blocks.append(block)
            continue

        paragraph_lines.append(line)

    flush_paragraph()
    return blocks


def extract_title(markdown: str) -> str:
    """取出文章的 H1 標題；沒有 H1 時回傳空字串。"""
    for line in markdown.splitlines():
        heading = _HEADING_PATTERN.match(line.rstrip())
        if heading and len(heading.group("level")) == 1:
            return heading.group("text").strip()
    return ""


def strip_title(markdown: str) -> str:
    """移除 H1 標題行，讓正文不重複出現標題。"""
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        heading = _HEADING_PATTERN.match(line.rstrip())
        if heading and len(heading.group("level")) == 1:
            return "\n".join(lines[:index] + lines[index + 1:]).lstrip("\n")
    return markdown
