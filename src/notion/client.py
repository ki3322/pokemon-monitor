"""Notion API 用戶端。

只包裝這個專案用得到的端點，並統一錯誤處理：
失敗一律回傳 None 或 False 並印出 Notion 回傳的錯誤訊息，
讓呼叫端能像 Telegram 通知一樣「成功才記錄已投遞」。
"""
from typing import Dict, List, Optional

import requests

from config import NOTION_DATABASE_ID, NOTION_TOKEN, REQUEST_TIMEOUT

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionClient:
    def __init__(self, token: Optional[str] = None, database_id: Optional[str] = None):
        self.token = token or NOTION_TOKEN
        self.database_id = database_id or NOTION_DATABASE_ID

    def is_configured(self) -> bool:
        return bool(self.token and self.database_id)

    def has_token(self) -> bool:
        """setup 腳本只需要 token，還不需要 database。"""
        return bool(self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, payload: Optional[Dict] = None) -> Optional[Dict]:
        try:
            response = requests.request(
                method,
                f"{NOTION_API}{path}",
                headers=self._headers(),
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            detail = ""
            failed = getattr(error, "response", None)
            if failed is not None:
                detail = f" (HTTP {failed.status_code}: {failed.text[:300]})"
            print(f"    [Error] Notion {method} {path} 失敗: {error}{detail}")
            return None

    def whoami(self) -> Optional[Dict]:
        """驗證 token 是否有效，回傳 integration 自身資訊。"""
        return self._request("GET", "/users/me")

    # ------------------------------------------------------------------ 資料庫

    def create_database(self, parent_page_id: str, title: str, properties: Dict) -> Optional[Dict]:
        return self._request(
            "POST",
            "/databases",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": properties,
            },
        )

    def retrieve_database(self, database_id: str = "") -> Optional[Dict]:
        return self._request("GET", f"/databases/{database_id or self.database_id}")

    def update_database(self, database_id: str, patch: Dict) -> Optional[Dict]:
        """更新資料庫本身（欄位、圖示、說明）。呼叫端只該送出要改的部分。"""
        return self._request("PATCH", f"/databases/{database_id or self.database_id}", patch)

    def query_database(
        self,
        filter_: Optional[Dict] = None,
        page_size: int = 100,
        sorts: Optional[List[Dict]] = None,
        limit: Optional[int] = None,
    ) -> Optional[List[Dict]]:
        """查詢資料庫，自動翻頁。

        `limit` 是要的筆數上限：湊滿就停止翻頁（例如儀表板只要最近 N 筆，
        不該為此翻完整個資料庫）。失敗回傳 None（包含翻頁途中失敗）——
        不能回傳半套結果，呼叫端會把「不完整」誤判成「就這麼多」。
        """
        results: List[Dict] = []
        cursor = None

        while True:
            payload: Dict = {"page_size": page_size}
            if filter_:
                payload["filter"] = filter_
            if sorts:
                payload["sorts"] = sorts
            if cursor:
                payload["start_cursor"] = cursor

            data = self._request("POST", f"/databases/{self.database_id}/query", payload)
            if data is None:
                return None

            results.extend(data.get("results", []))
            if limit is not None and len(results) >= limit:
                return results[:limit]
            if not data.get("has_more"):
                return results
            cursor = data.get("next_cursor")

    # ------------------------------------------------------------------ 頁面

    def create_page(self, properties: Dict, children: Optional[List[Dict]] = None) -> Optional[Dict]:
        payload: Dict = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }
        if children:
            payload["children"] = children
        return self._request("POST", "/pages", payload)

    def create_child_page(
        self,
        parent_page_id: str,
        title: str,
        children: Optional[List[Dict]] = None,
    ) -> Optional[Dict]:
        """在某個頁面底下建立子頁面（而非資料庫項目）。"""
        payload: Dict = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        }
        if children:
            payload["children"] = children
        return self._request("POST", "/pages", payload)

    def retrieve_page(self, page_id: str) -> Optional[Dict]:
        return self._request("GET", f"/pages/{page_id}")

    def update_page(self, page_id: str, properties: Dict) -> Optional[Dict]:
        return self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def append_blocks(self, page_id: str, children: List[Dict]) -> bool:
        """附加區塊到頁面。呼叫端負責先分批（每批 100 個以內）。"""
        return self._request("PATCH", f"/blocks/{page_id}/children", {"children": children}) is not None

    def list_children(self, page_id: str) -> Optional[List[Dict]]:
        """列出頁面的子區塊，自動翻頁。

        失敗回傳 None——清除頁面前的讀取失敗必須被辨識出來，
        否則呼叫端會「刪掉零個區塊」後回報成功，內容疊成兩份。
        """
        results: List[Dict] = []
        cursor = None

        while True:
            suffix = f"?start_cursor={cursor}" if cursor else ""
            data = self._request("GET", f"/blocks/{page_id}/children{suffix}")
            if data is None:
                return None

            results.extend(data.get("results", []))
            if not data.get("has_more"):
                return results
            cursor = data.get("next_cursor")

    def delete_block(self, block_id: str) -> bool:
        return self._request("DELETE", f"/blocks/{block_id}") is not None
