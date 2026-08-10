"""把標為「略過」的新聞移到 Notion 垃圾桶。

用途是清掉一眼就知道不會寫的新聞，讓資料庫只剩真正的候選。

這是「可還原的軟刪除」：頁面進 Notion 垃圾桶，30 天內都能還原，
Notion API 也沒有永久刪除的端點。要真的清空只能在 Notion 介面上做。

刪掉不會讓監控把同一則再抓回來——去重是靠 state.json 的投遞記錄，
與資料庫裡有沒有那一頁無關。
"""
from typing import Dict, List, Optional, Tuple

from src.notion import schema
from src.notion.client import NotionClient
from src.notion.reader import SelectedItem, to_selected_item


def skipped_filter() -> Dict:
    """狀態為「略過」的項目。"""
    return {"property": schema.STATUS, "select": {"equals": schema.STATUS_SKIPPED}}


class NotionCleanup:
    def __init__(self, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()

    def skipped_items(self) -> Optional[List[SelectedItem]]:
        """查詢失敗回傳 None——不能把「查不到」當成「沒有要刪的」。"""
        pages = self.client.query_database(skipped_filter())
        if pages is None:
            return None
        return [to_selected_item(page) for page in pages]

    def run(self, dry_run: bool = False) -> Optional[Tuple[int, int]]:
        """刪除所有「略過」的項目，回傳 (成功, 失敗)。查詢失敗回傳 None。"""
        items = self.skipped_items()
        if items is None:
            print("[Error] 讀不到資料庫，已中止")
            return None

        removed = failed = 0
        for item in items:
            print(f"  - {item.title[:52]}")
            if dry_run:
                removed += 1
            elif self.client.archive_page(item.page_id):
                removed += 1
            else:
                failed += 1

        return removed, failed
