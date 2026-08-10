"""把文章 IR 轉成 Notion 區塊 JSON。

Notion API 有幾個硬限制，這裡集中處理：
  - 單一 rich_text 項目的 content 上限 2000 字元
  - 一次請求最多附加 100 個區塊
"""
from typing import Dict, Iterator, List, Sequence

from src.article.markdown import Block, Span

# Notion 單一 rich_text 項目的字元上限
MAX_RICH_TEXT_LENGTH = 2000

# Notion 單次請求的區塊數量上限
MAX_BLOCKS_PER_REQUEST = 100

# IR 的 kind 與 Notion 區塊型別同名，divider 除外（沒有 rich_text）
_KINDS_WITHOUT_TEXT = {"divider"}


def chunk_text(text: str, size: int = MAX_RICH_TEXT_LENGTH) -> List[str]:
    """把長文字切成符合 Notion 上限的片段。"""
    if not text:
        return []
    return [text[start:start + size] for start in range(0, len(text), size)]


def rich_text(content: str, annotations: Dict = None, href: str = "") -> List[Dict]:
    """建立 rich_text 項目，超長內容自動切片。"""
    items = []
    for piece in chunk_text(content):
        item: Dict = {"type": "text", "text": {"content": piece}}
        if href:
            item["text"]["link"] = {"url": href}
        if annotations:
            item["annotations"] = annotations
        items.append(item)
    return items


def render_spans(spans: Sequence[Span]) -> List[Dict]:
    """把行內 Span 序列轉成 Notion rich_text 陣列。"""
    items: List[Dict] = []

    for span in spans:
        annotations = {}
        if span.bold:
            annotations["bold"] = True
        if span.italic:
            annotations["italic"] = True
        if span.code:
            annotations["code"] = True

        items.extend(rich_text(span.text, annotations or None, span.href))

    return items


def render_table(block: Block) -> Dict:
    """把表格區塊轉成 Notion table。

    Notion 要求每一列的儲存格數量等於 table_width，解析階段已做過正規化。
    """
    width = len(block.rows[0]) if block.rows else 0
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": block.has_header,
            "has_row_header": False,
            "children": [
                {
                    "object": "block",
                    "type": "table_row",
                    "table_row": {"cells": [render_spans(cell) for cell in row]},
                }
                for row in block.rows
            ],
        },
    }


def render_block(block: Block) -> Dict:
    """把單一 Block 轉成 Notion 區塊。"""
    if block.kind == "table":
        return render_table(block)

    if block.kind in _KINDS_WITHOUT_TEXT:
        return {"object": "block", "type": block.kind, block.kind: {}}

    return {
        "object": "block",
        "type": block.kind,
        block.kind: {"rich_text": render_spans(block.spans)},
    }


def render_blocks(blocks: Sequence[Block]) -> List[Dict]:
    return [render_block(block) for block in blocks]


def code_block(code: str, language: str = "html") -> Dict:
    """建立程式碼區塊。Notion 的複製鈕會原樣複製整段內容。"""
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": rich_text(code), "language": language},
    }


def heading_block(text: str, level: int = 2, color: str = "") -> Dict:
    kind = f"heading_{min(max(level, 1), 3)}"
    payload: Dict = {"rich_text": rich_text(text)}
    if color:
        payload["color"] = color
    return {"object": "block", "type": kind, kind: payload}


def paragraph_block(text: str, color: str = "") -> Dict:
    payload: Dict = {"rich_text": rich_text(text)}
    if color:
        payload["color"] = color
    return {"object": "block", "type": "paragraph", "paragraph": payload}


def callout_block(text: str, emoji: str = "", color: str = "", children: Sequence[Dict] = ()) -> Dict:
    """建立標註區塊。Notion 沒有自訂樣式，色塊是唯一能表現強調的手段。"""
    payload: Dict = {"rich_text": rich_text(text)}
    if emoji:
        payload["icon"] = {"type": "emoji", "emoji": emoji}
    if color:
        payload["color"] = color
    if children:
        payload["children"] = list(children)
    return {"object": "block", "type": "callout", "callout": payload}


def column_list_block(columns: Sequence[Sequence[Dict]]) -> Dict:
    """建立多欄版面。

    Notion 要求至少兩欄、且每欄都要有內容，欄數不足時呼叫端必須自行補齊。
    """
    return {
        "object": "block",
        "type": "column_list",
        "column_list": {
            "children": [
                {"object": "block", "type": "column", "column": {"children": list(blocks)}}
                for blocks in columns
            ]
        },
    }


def rich_table(rows: Sequence[Sequence[List[Dict]]], has_header: bool = True) -> Dict:
    """用已經渲染好的 rich_text 儲存格建立表格。

    每列的儲存格數量會對齊第一列——Notion 會拒絕寬度不一致的列。
    """
    width = len(rows[0]) if rows else 0
    normalized = [list(row)[:width] + [[] for _ in range(width - len(row))] for row in rows]

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": [
                {"object": "block", "type": "table_row", "table_row": {"cells": cells}}
                for cells in normalized
            ],
        },
    }


def text_table(rows: Sequence[Sequence[str]], has_header: bool = True) -> Dict:
    """用純文字列建立表格。不需要連結時用這個。"""
    return rich_table([[rich_text(cell) for cell in row] for row in rows], has_header)


def divider_block() -> Dict:
    return {"object": "block", "type": "divider", "divider": {}}


def batched(blocks: Sequence[Dict], size: int = MAX_BLOCKS_PER_REQUEST) -> Iterator[List[Dict]]:
    """依 Notion 的單次上限把區塊分批。"""
    for start in range(0, len(blocks), size):
        yield list(blocks[start:start + size])
