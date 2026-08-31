"""把來源目前看得到的內容補進 Notion 資料庫。

為什麼需要這個：新啟用一個目的地時，第一輪只會把現況「標記為已投遞」而
不建立頁面，避免整頁舊內容一次湧出。副作用是那些既有文章永遠不會進資料庫，
使用者看到的是一個幾乎空的資料庫，要等全新發佈的文章才會長。

回填只補 Notion，不碰 Telegram，也不改投遞記錄——那些項目本來就已經
標記為已投遞了，重跑監控不會因此重複通知。
"""
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from src.models import FeedItem
from src.notion import schema
from src.notion.client import NotionClient
from src.notion.sync import NotionSync
from src.translator import translate_title


def collect_items(
    rss_sources: Sequence[Dict],
    scrape_sources: Sequence[Dict],
    twitter_accounts: Sequence[str],
    get_rss: Callable,
    get_scraped: Callable,
    get_twitter: Callable,
) -> Tuple[List[Tuple[FeedItem, bool]], List[str]]:
    """抓取所有來源，回傳 [(項目, 是否需要翻譯)] 與失敗的來源名稱。

    抓取失敗的來源只是少補一些內容，不該讓整個回填中止。
    """
    collected: List[Tuple[FeedItem, bool]] = []
    failures: List[str] = []
    seen: Set[str] = set()

    def absorb(items: Sequence[FeedItem], translate: bool) -> None:
        for item in items:
            if item.id and item.id not in seen:
                seen.add(item.id)
                collected.append((item, translate))

    for source in rss_sources:
        items, ok = get_rss(source)
        if ok:
            absorb(items, source.get("translate", True))
        else:
            failures.append(source["name"])

    for source in scrape_sources:
        try:
            items, ok = get_scraped(source)
        except ValueError as error:
            print(f"    [Error] {source.get('name', '?')}: {error}")
            failures.append(source.get("name", "?"))
            continue
        if ok:
            absorb(items, source.get("translate", True))
        else:
            failures.append(source["name"])

    for username in twitter_accounts:
        items, ok = get_twitter(username)
        if ok:
            absorb(items, True)
        else:
            failures.append(f"@{username}")

    return collected, failures


class NotionBackfill:
    def __init__(self, sync: Optional[NotionSync] = None, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()
        self.sync = sync or NotionSync(self.client)

    def existing_item_ids(self) -> Optional[Set[str]]:
        """資料庫裡已有的項目 ID。查詢失敗回傳 None——不能把「查不到」
        當成「都不存在」，那會把整個資料庫再灌一次。
        """
        pages = self.client.query_database()
        if pages is None:
            return None

        found: Set[str] = set()
        for page in pages:
            prop = (page.get("properties", {}).get(schema.ITEM_ID) or {}).get("rich_text") or []
            item_id = "".join(part.get("plain_text", "") for part in prop)
            if item_id:
                found.add(item_id)
        return found

    def run(
        self,
        collected: Sequence[Tuple[FeedItem, bool]],
        dry_run: bool = False,
        translate: Callable[[str], str] = translate_title,
    ) -> Tuple[int, int, int]:
        """回傳 (建立, 略過, 失敗) 的筆數。"""
        existing = self.existing_item_ids()
        if existing is None:
            print("[Error] 讀不到現有項目，已中止以免建立重複頁面")
            return 0, 0, 0

        created = skipped = failed = 0

        for item, needs_translation in collected:
            if item.id in existing:
                skipped += 1
                continue

            if dry_run:
                print(f"  + {item.source}｜{item.title[:44]}")
                created += 1
                continue

            title = translate(item.title) if needs_translation else item.title
            if self.sync.add_item(item, display_title=title):
                created += 1
                existing.add(item.id)
            else:
                failed += 1

        return created, skipped, failed
