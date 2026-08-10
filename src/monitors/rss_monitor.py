"""RSS 與 Twitter（透過 RSSHub）監控。"""
import calendar
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import feedparser

from config import RSSHUB_INSTANCE
from src.http_client import fetch
from src.models import FeedItem, generate_item_id, truncate_title

# 只通知這個時間範圍內的文章（小時）
MAX_AGE_HOURS = 24

# Twitter 推文的時間範圍。必須明顯大於 cron 間隔：GitHub 排程工作
# 常被延遲 10~30 分鐘，視窗太窄時一次延遲或連續兩次失敗就會永久漏掉推文。
# 重複發送已由 seen_items 擋掉，這個視窗只是用來避免初次抓取灌爆通知。
TWITTER_MAX_AGE_HOURS = 12

# 每個來源每輪最多處理的筆數
MAX_ENTRIES_PER_FEED = 10


def is_recent(entry, max_age_hours: int = MAX_AGE_HOURS) -> bool:
    """檢查文章是否在指定時間內發布。無法判斷時視為新文章。"""
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return True

    try:
        published_dt = datetime.fromtimestamp(calendar.timegm(published), tz=timezone.utc)
    except (ValueError, OverflowError, TypeError):
        return True

    return datetime.now(timezone.utc) - published_dt < timedelta(hours=max_age_hours)


def fetch_feed(url: str) -> Optional[feedparser.FeedParserDict]:
    """取得並解析 feed，失敗回傳 None。"""
    response = fetch(url)
    if response is None:
        return None

    feed = feedparser.parse(response.text)
    if feed.bozo and not feed.entries:
        print(f"    [Error] 無法解析 feed {url}: {feed.get('bozo_exception')}")
        return None
    return feed


def _entry_to_item(
    entry,
    source_name: str,
    source_type: str,
    default_title: str = "無標題",
) -> Optional[FeedItem]:
    """把 feed entry 轉成 FeedItem，缺少可用識別碼時回傳 None。"""
    link = entry.get("link", "") or ""
    # guid 比連結更穩定（連結可能帶追蹤參數），優先採用
    guid = entry.get("id", "") or ""

    item_id = generate_item_id(link, guid)
    if not item_id:
        return None

    return FeedItem(
        id=item_id,
        title=truncate_title(entry.get("title", "") or default_title),
        link=link,
        source=source_name,
        source_type=source_type,
    )


def get_rss_items(source: Dict) -> Tuple[List[FeedItem], bool]:
    """取得 RSS 來源的文章。

    Returns:
        (items, success) - success 表示是否成功連接並解析。
    """
    feed = fetch_feed(source["url"])
    if feed is None:
        return [], False

    items = []
    for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
        if not is_recent(entry):
            continue
        item = _entry_to_item(entry, source["name"], source.get("type", "website"))
        if item:
            items.append(item)

    return items, True


def get_twitter_items(username: str) -> Tuple[List[FeedItem], bool]:
    """透過 RSSHub 取得 Twitter/X 帳號的推文。

    Returns:
        (items, success) - success 表示是否成功連接並解析。
    """
    feed = fetch_feed(f"{RSSHUB_INSTANCE}/twitter/user/{username}")
    if feed is None:
        return [], False

    items = []
    for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
        if not is_recent(entry, max_age_hours=TWITTER_MAX_AGE_HOURS):
            continue
        item = _entry_to_item(entry, f"@{username}", "twitter", default_title="（無內容）")
        if item:
            items.append(item)

    return items, True
