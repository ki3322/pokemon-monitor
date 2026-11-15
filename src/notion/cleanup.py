"""清掉 Notion 資料庫裡不需要的項目。

兩種清理對象：
  1. 標成「略過」的 —— 看過了、確定不會寫。
  2. 來自 NOTION_EXCLUDED_GROUPS 的 —— 排除設定只擋新的，
     設定之前已經同步進去的舊項目要靠這裡清。已勾選、撰寫中、已完成的除外。

一律走 Notion 的封存（archived）而不是真的刪除：那是「移到垃圾桶」，
30 天內在 Notion 介面還能還原。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Set

from src.models import display_group, source_group, twitter_group
from src.notion import schema
from src.notion.client import NotionClient

REASON_EXCLUDED = "來源已排除"

# 沒勾選的新聞放這麼多天後自動清掉
DEFAULT_STALE_DAYS = 2

# 天數下限：更小的值會讓截止時間落在現在或未來
MIN_STALE_DAYS = 1

# 已經投入過人力的狀態：不論哪個條件選中，都不該連稿子帶頁面一起清掉
INVESTED_STATUSES = (schema.STATUS_WRITING, schema.STATUS_DONE)


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


def stale_clause(days: int, now: Optional[datetime] = None) -> Dict:
    """「放太久沒人要」的條件：沒勾選、沒動過、而且夠舊。

    三個條件缺一不可，每一個都是防止誤刪的護欄：
      - 沒勾選：勾了就是要寫，再舊都不能刪。
      - 狀態為待處理：撰寫中／已完成代表已經投入過人力，
        就算事後被取消勾選，也不該把稿子連頁面一起刪掉。
      - 發現時間夠舊：才有機會被看到。
    """
    # 負數或 0 會把截止時間推到現在或未來，於是「超過 N 天沒人要」變成
    # 「每一筆待處理項目」——整個資料庫會被封存。這是不可逆的規模，
    # 必須在組出條件之前就擋下來。
    if days < MIN_STALE_DAYS:
        raise ValueError(
            f"--stale 至少 1 天（收到 {days}）：0 或負數的截止時間會落在現在或未來，"
            "等於封存所有待處理項目"
        )

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    return {
        "and": [
            {"property": schema.SELECTED, "checkbox": {"equals": False}},
            {"property": schema.STATUS, "select": {"equals": schema.STATUS_PENDING}},
            {"property": schema.FOUND_AT, "date": {"before": cutoff.isoformat()}},
        ]
    }


def excluded_clause(source_name: str) -> Dict:
    """「來源已排除」的條件：來源相符，而且沒有人在用。

    排除設定是「以後不要再送進來」，不是「把做過的也丟掉」，所以同樣要有護欄：
      - 沒勾選：勾了就是要寫，即使來源被排除。
      - 不是撰寫中／已完成：已經投入過人力。

    每個來源各自一個 and，而不是把所有來源包成一個 or 再 and：
    外層 cleanup_filter 已經是 or，Notion 的複合條件最多只能兩層。
    """
    return {
        "and": [
            {"property": schema.SOURCE, "rich_text": {"equals": source_name}},
            {"property": schema.SELECTED, "checkbox": {"equals": False}},
            *(
                {"property": schema.STATUS, "select": {"does_not_equal": status}}
                for status in INVESTED_STATUSES
            ),
        ]
    }


def cleanup_filter(
    status: str,
    sources: Iterable[str],
    stale: Optional[Dict] = None,
) -> Optional[Dict]:
    """組出各條件的聯集；沒有任何條件時回傳 None。"""
    clauses: List[Dict] = []

    if status:
        clauses.append({"property": schema.STATUS, "select": {"equals": status}})

    # 排序讓輸出穩定，測試與日誌才可預期
    for name in sorted(sources):
        clauses.append(excluded_clause(name))

    if stale:
        clauses.append(stale)

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
        stale_days: int = 0,
        now: Optional[datetime] = None,
    ) -> Optional[List[CleanupTarget]]:
        """找出符合條件的項目。查詢失敗回傳 None。

        失敗必須與「沒有東西要清」區分開來，否則 API 掛掉會被當成清乾淨了。
        """
        source_names = set(sources or ())
        stale = stale_clause(stale_days, now) if stale_days else None

        filter_ = cleanup_filter(status, source_names, stale)
        if filter_ is None:
            return []

        pages = self.client.query_database(filter_)
        if pages is None:
            return None

        return [self._to_target(page, status, source_names, stale_days) for page in pages]

    @staticmethod
    def _reason(source: str, page_status: str, source_names: Set[str], stale_days: int, status: str) -> str:
        """說明這筆為什麼被選中。多個條件都符合時挑最根本的那個。"""
        if source in source_names:
            return REASON_EXCLUDED
        if stale_days and page_status == schema.STATUS_PENDING:
            return f"超過 {stale_days} 天未勾選"
        return f"狀態為{page_status or status}"

    @classmethod
    def _to_target(
        cls,
        page: Dict,
        status: str,
        source_names: Set[str],
        stale_days: int = 0,
    ) -> CleanupTarget:
        properties = page.get("properties", {})
        source = _plain_text(properties.get(schema.SOURCE))
        page_status = _status_name(properties.get(schema.STATUS))

        return CleanupTarget(
            page_id=page.get("id", ""),
            title=_plain_text(properties.get(schema.TITLE)),
            source=source,
            status=page_status,
            reason=cls._reason(source, page_status, source_names, stale_days, status),
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
