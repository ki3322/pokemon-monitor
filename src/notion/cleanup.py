"""清掉 Notion 資料庫裡不需要的項目。

兩種清理對象：
  1. 標成「略過」的 —— 看過了、確定不會寫。
  2. 來自 NOTION_EXCLUDED_GROUPS 的 —— 排除設定只擋新的，
     設定之前已經同步進去的舊項目要靠這裡清。

一律走 Notion 的封存（archived）而不是真的刪除：那是「移到垃圾桶」，
30 天內在 Notion 介面還能還原。
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set

from src.models import display_group, source_group, twitter_group
from src.notion import schema
from src.notion.client import NotionClient

REASON_EXCLUDED = "來源已排除"


@dataclass(frozen=True)
class CleanupTarget:
    """一筆要清掉的項目，以及為什麼。"""

    page_id: str
    title: str
    source: str
    status: str
    reason: str


def excluded_source_names(
    rss_sources: Sequence[Dict],
    scrape_sources: Sequence[Dict],
    twitter_accounts: Sequence[str],
    excluded_groups: Iterable[str],
) -> Set[str]:
    """把排除的「群組」換算成資料庫「來源」欄位實際存的名稱。

    群組不等於來源名稱，兩者要分開處理：
      - 推文的來源是 @帳號
      - 網站的來源是各自的 name，多個 name 可能共用同一個 group
        （例如玩具人的兩個標籤頁）
    """
    excluded = set(excluded_groups)
    names: Set[str] = set()

    for source in list(rss_sources) + list(scrape_sources):
        if source_group(source) in excluded:
            names.add(source.get("name", ""))

    for username in twitter_accounts:
        group = twitter_group(username)
        if group in excluded:
            names.add(display_group(group))

    return {name for name in names if name}


def cleanup_filter(status: str, sources: Iterable[str]) -> Optional[Dict]:
    """組出「狀態符合、或來源符合」的聯集條件；沒有條件時回傳 None。"""
    clauses: List[Dict] = []

    if status:
        clauses.append({"property": schema.STATUS, "select": {"equals": status}})

    # 排序讓輸出穩定，測試與日誌才可預期
    for name in sorted(sources):
        clauses.append({"property": schema.SOURCE, "rich_text": {"equals": name}})

    return {"or": clauses} if clauses else None


def _plain_text(prop: Optional[Dict]) -> str:
    if not prop:
        return ""
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(item.get("plain_text", "") for item in items)


def _status_name(prop: Optional[Dict]) -> str:
    if not prop:
        return ""
    selected = prop.get("select")
    return selected.get("name", "") if selected else ""


class NotionCleanup:
    def __init__(self, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()

    def is_configured(self) -> bool:
        return self.client.is_configured()

    def find_targets(
        self,
        status: str = "",
        sources: Optional[Iterable[str]] = None,
    ) -> Optional[List[CleanupTarget]]:
        """找出符合條件的項目。查詢失敗回傳 None。

        失敗必須與「沒有東西要清」區分開來，否則 API 掛掉會被當成清乾淨了。
        """
        source_names = set(sources or ())
        filter_ = cleanup_filter(status, source_names)
        if filter_ is None:
            return []

        pages = self.client.query_database(filter_)
        if pages is None:
            return None

        return [self._to_target(page, status, source_names) for page in pages]

    @staticmethod
    def _to_target(page: Dict, status: str, source_names: Set[str]) -> CleanupTarget:
        properties = page.get("properties", {})
        source = _plain_text(properties.get(schema.SOURCE))
        page_status = _status_name(properties.get(schema.STATUS))

        # 兩個條件都符合時，來源優先——那是比較根本的理由
        reason = REASON_EXCLUDED if source in source_names else f"狀態為{page_status or status}"

        return CleanupTarget(
            page_id=page.get("id", ""),
            title=_plain_text(properties.get(schema.TITLE)),
            source=source,
            status=page_status,
            reason=reason,
        )

    def archive(self, targets: Sequence[CleanupTarget]) -> tuple:
        """把項目移到垃圾桶，回傳 (成功筆數, 失敗筆數)。

        單筆失敗不中止其餘的清理：剩下的仍該清掉，失敗的如實回報即可。
        """
        archived = failed = 0

        for target in targets:
            if self.client.archive_page(target.page_id):
                archived += 1
            else:
                failed += 1

        return archived, failed
