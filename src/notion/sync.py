"""把監控到的新內容推進 Notion 資料庫。"""
from datetime import datetime, timezone
from typing import Dict, Optional

from src.article.markdown import Span
from src.models import FeedItem
from src.notion import schema
from src.notion.blocks import render_spans
from src.notion.client import NotionClient


def _properties(item: FeedItem, display_title: str = "", now: Optional[datetime] = None) -> Dict:
    now = now or datetime.now(timezone.utc)
    return {
        # TITLE 用翻譯後的顯示標題（Notion 列表才可讀），未提供時退回原文標題
        schema.TITLE: {"title": [{"type": "text", "text": {"content": display_title or item.title}}]},
        # 「原始標題」必須是監控抓到的原文——翻譯後就再也還原不了，
        # 而發布時 TITLE 會被換成定稿標題，原文標題只有這裡留得住
        schema.ORIGINAL_TITLE: {"rich_text": [{"type": "text", "text": {"content": item.title}}]},
        schema.LINK: {"url": item.link or None},
        schema.SOURCE: {"rich_text": [{"type": "text", "text": {"content": item.source}}]},
        schema.CATEGORY: {"select": {"name": schema.category_for(item.source_type)}},
        schema.FOUND_AT: {"date": {"start": now.isoformat()}},
        schema.SELECTED: {"checkbox": False},
        schema.STATUS: {"select": {"name": schema.STATUS_PENDING}},
        schema.ITEM_ID: {"rich_text": [{"type": "text", "text": {"content": item.id}}]},
    }


def _intro_blocks(item: FeedItem) -> list:
    """頁面初始內容：一段可點擊的來源連結，方便直接開原文。"""
    if not item.link:
        return []
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": render_spans([Span("👉 開啟來源原文", href=item.link)])},
        }
    ]


class NotionSync:
    """建立資料庫項目。每則內容一頁。"""

    def __init__(self, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()

    def is_configured(self) -> bool:
        return self.client.is_configured()

    def add_item(self, item: FeedItem, display_title: str = "") -> bool:
        """建立一筆資料庫項目，成功回傳 True。

        `display_title` 是翻譯後的顯示標題；item 本身保持原文，
        「原始標題」欄位靠它。呼叫端「必須」檢查回傳值：
        只有成功建立的項目才可以標記為已投遞。
        """
        if not self.is_configured():
            print("    [Warning] Notion 未設定，略過同步")
            return False

        created = self.client.create_page(_properties(item, display_title), _intro_blocks(item))
        return created is not None
