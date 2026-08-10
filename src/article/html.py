"""把文章 IR 轉成可直接貼進 WordPress 的乾淨 HTML。

刻意不輸出 class、id、inline style 或任何包裝用的 <div>：
貼進 WordPress 程式碼編輯器後，樣式完全由佈景主題決定。
"""
from typing import List, Sequence

from src.article.markdown import Block, Span, parse_markdown, strip_title

# 這些區塊會被合併成單一清單容器
_LIST_KINDS = {"bulleted_list_item": "ul", "numbered_list_item": "ol"}

_BLOCK_TAGS = {
    "heading_2": "h2",
    "heading_3": "h3",
    "heading_4": "h4",
    "paragraph": "p",
    "quote": "blockquote",
}


def escape_text(text: str) -> str:
    """跳脫 HTML 文字節點。& 必須先換，否則會二次跳脫。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def escape_attribute(value: str) -> str:
    """跳脫 HTML 屬性值。"""
    return escape_text(value).replace('"', "&quot;")


def render_spans(spans: Sequence[Span]) -> str:
    """把行內 Span 序列轉成 HTML。"""
    parts: List[str] = []

    for span in spans:
        if span.code:
            # 程式碼不再套用其他樣式
            parts.append(f"<code>{escape_text(span.text)}</code>")
            continue

        content = escape_text(span.text)
        if span.bold:
            content = f"<strong>{content}</strong>"
        if span.italic:
            content = f"<em>{content}</em>"
        if span.href:
            content = f'<a href="{escape_attribute(span.href)}">{content}</a>'
        parts.append(content)

    return "".join(parts)


def render_table(block: Block) -> List[str]:
    """把表格區塊轉成 <table>。有表頭時第一列放進 <thead>。"""
    if not block.rows:
        return []

    lines = ["<table>"]
    body_start = 0

    if block.has_header:
        header = "".join(f"<th>{render_spans(cell)}</th>" for cell in block.rows[0])
        lines.extend(["<thead>", f"<tr>{header}</tr>", "</thead>"])
        body_start = 1

    body_rows = block.rows[body_start:]
    if body_rows:
        lines.append("<tbody>")
        for row in body_rows:
            cells = "".join(f"<td>{render_spans(cell)}</td>" for cell in row)
            lines.append(f"<tr>{cells}</tr>")
        lines.append("</tbody>")

    lines.append("</table>")
    return lines


def render_blocks(blocks: Sequence[Block]) -> str:
    """把 Block 序列轉成 HTML，連續的清單項目會合併成同一個 ul/ol。"""
    lines: List[str] = []
    open_list = ""

    def close_list() -> None:
        nonlocal open_list
        if open_list:
            lines.append(f"</{open_list}>")
            open_list = ""

    for block in blocks:
        list_tag = _LIST_KINDS.get(block.kind)

        if list_tag:
            if open_list != list_tag:
                close_list()
                lines.append(f"<{list_tag}>")
                open_list = list_tag
            lines.append(f"<li>{render_spans(block.spans)}</li>")
            continue

        close_list()

        if block.kind == "divider":
            lines.append("<hr />")
            continue

        if block.kind == "table":
            lines.extend(render_table(block))
            continue

        tag = _BLOCK_TAGS.get(block.kind, "p")
        lines.append(f"<{tag}>{render_spans(block.spans)}</{tag}>")

    close_list()
    return "\n".join(lines)


def markdown_to_html(markdown: str, drop_title: bool = True) -> str:
    """把 Markdown 文章轉成 WordPress HTML。

    Args:
        markdown: 文章原文。
        drop_title: 是否移除 H1（WordPress 的標題另外填，正文不該重複）。
    """
    body = strip_title(markdown) if drop_title else markdown
    return render_blocks(parse_markdown(body))
