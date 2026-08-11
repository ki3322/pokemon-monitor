"""讀取 Notion 中被勾選、等待撰稿的項目。"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.notion import schema
from src.notion.client import NotionClient


@dataclass(frozen=True)
class SelectedItem:
    """資料庫裡的一筆新聞（撰稿流程與儀表板共用）。"""

    page_id: str
    title: str
    link: str
    source: str
    category: str
    status: str
    selected: bool = False
    found_at: str = ""  # ISO 8601；監控寫入的發現時間


def _plain_text(prop: Optional[Dict]) -> str:
    """從 title / rich_text 屬性取出純文字。"""
    if not prop:
        return ""
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(item.get("plain_text", "") for item in items)


def _select_name(prop: Optional[Dict]) -> str:
    if not prop:
        return ""
    selected = prop.get("select")
    return selected.get("name", "") if selected else ""


def _date_start(prop: Optional[Dict]) -> str:
    if not prop:
        return ""
    return (prop.get("date") or {}).get("start") or ""


def to_selected_item(page: Dict) -> SelectedItem:
    properties = page.get("properties", {})
    return SelectedItem(
        page_id=page.get("id", ""),
        title=_plain_text(properties.get(schema.TITLE)),
        link=(properties.get(schema.LINK) or {}).get("url") or "",
        source=_plain_text(properties.get(schema.SOURCE)),
        category=_select_name(properties.get(schema.CATEGORY)),
        status=_select_name(properties.get(schema.STATUS)),
        selected=bool((properties.get(schema.SELECTED) or {}).get("checkbox")),
        found_at=_date_start(properties.get(schema.FOUND_AT)),
    )


def pending_filter() -> Dict:
    """已勾選、且還沒動過的項目。

    刻意用「等於待處理」而不是「不等於已完成」：自動撰稿把寫好的稿子標成
    「撰寫中」等人審，若條件是「不等於已完成」，那篇下一輪仍然符合，
    會被無限重寫。狀態一旦離開「待處理」就代表已經處理過了。

    要重寫某一篇，把它的狀態改回「待處理」即可。
    """
    return {
        "and": [
            {"property": schema.SELECTED, "checkbox": {"equals": True}},
            {"property": schema.STATUS, "select": {"equals": schema.STATUS_PENDING}},
        ]
    }


class NotionReader:
    def __init__(self, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()

    def is_configured(self) -> bool:
        return self.client.is_configured()

    def pending_items(self) -> Optional[List[SelectedItem]]:
        """取得所有勾選待寫的項目。

        查詢失敗回傳 None——必須與「沒有勾選項目」（空清單）區分開來，
        否則 API 掛掉會被當成一切正常。
        """
        pages = self.client.query_database(pending_filter())
        if pages is None:
            return None
        return [to_selected_item(page) for page in pages]

    def recent_items(self, limit: int) -> Optional[List[SelectedItem]]:
        """取得最近發現的項目（依發現時間新到舊），供儀表板顯示。

        查詢失敗回傳 None，理由同 pending_items。
        """
        pages = self.client.query_database(
            sorts=[{"property": schema.FOUND_AT, "direction": "descending"}],
            limit=limit,
        )
        if pages is None:
            return None
        return [to_selected_item(page) for page in pages]
