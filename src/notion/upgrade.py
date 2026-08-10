"""把既有的 Notion 資料庫升級到目前的欄位定義。

設計原則是「只補不改」：只送出資料庫還沒有的欄位，
既有欄位（以及使用者在 Notion 手動加的選項、改的名稱）一律不碰。
重複執行是安全的。
"""
from typing import Dict, List, Optional, Tuple

from src.notion import schema
from src.notion.client import NotionClient


def _description_text(database: Dict) -> str:
    return "".join(part.get("plain_text", "") for part in database.get("description", []))


def build_patch(database: Dict) -> Dict:
    """算出要送出的 PATCH 內容。沒有任何要改的就回傳空 dict。"""
    patch: Dict = {}

    new_properties = schema.missing_properties(database.get("properties"))
    if new_properties:
        patch["properties"] = new_properties

    if not database.get("icon"):
        patch["icon"] = {"type": "emoji", "emoji": schema.DATABASE_ICON}

    if not _description_text(database):
        patch["description"] = [
            {"type": "text", "text": {"content": schema.DATABASE_DESCRIPTION}}
        ]

    return patch


def describe(patch: Dict) -> List[str]:
    """把 PATCH 內容轉成給人看的變更清單。"""
    changes = [f"新增欄位「{name}」" for name in patch.get("properties", {})]
    if "icon" in patch:
        changes.append(f"設定圖示 {schema.DATABASE_ICON}")
    if "description" in patch:
        changes.append("補上資料庫說明")
    return changes


class NotionUpgrade:
    def __init__(self, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()

    def run(self, database_id: str = "") -> Tuple[bool, List[str]]:
        """升級資料庫。回傳 (是否成功, 變更說明)。"""
        target = database_id or self.client.database_id
        if not target:
            return False, ["缺少 NOTION_DATABASE_ID"]

        database = self.client.retrieve_database(target)
        if database is None:
            return False, ["讀不到這個資料庫（確認 ID，以及是否分享給 integration）"]

        patch = build_patch(database)
        if not patch:
            return True, []

        if self.client.update_database(target, patch) is None:
            return False, ["寫入失敗，資料庫未變更"]

        return True, describe(patch)

    def backfill_original_titles(self, database_id: str = "") -> Optional[Tuple[int, int]]:
        """把既有項目的「原始標題」補上。

        只填空的欄位，已經有值的不覆寫——那可能是使用者自己改過的。
        回傳 (補上的筆數, 失敗筆數)；查詢失敗回傳 None——
        必須與「資料庫是空的」區分開來，否則會回報 0 筆補上、看起來一切正常。
        """
        client = self.client
        if database_id:
            client = NotionClient(token=client.token, database_id=database_id)

        pages = client.query_database()
        if pages is None:
            return None

        filled = failed = 0
        for page in pages:
            properties = page.get("properties", {})
            existing = (properties.get(schema.ORIGINAL_TITLE) or {}).get("rich_text") or []
            if existing:
                continue

            title = "".join(
                part.get("plain_text", "")
                for part in (properties.get(schema.TITLE) or {}).get("title", [])
            )
            if not title:
                continue

            updated = client.update_page(
                page.get("id", ""),
                {schema.ORIGINAL_TITLE: {"rich_text": [{"type": "text", "text": {"content": title}}]}},
            )
            if updated is None:
                failed += 1
            else:
                filled += 1

        return filled, failed
