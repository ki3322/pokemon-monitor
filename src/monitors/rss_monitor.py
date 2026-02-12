import feedparser
import hashlib
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import calendar
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import RSSHUB_INSTANCE, REQUEST_TIMEOUT, USER_AGENT

# 只通知這個時間範圍內的文章（小時）
MAX_AGE_HOURS = 24
TWITTER_MAX_AGE_HOURS = 1  # Twitter 推文只監控 1 小時內


@dataclass
class FeedItem:
    id: str
    title: str
    link: str
    source: str
    source_type: str  # 'website' or 'twitter'


def is_recent(entry, max_age_hours: int = MAX_AGE_HOURS) -> bool:
    """檢查文章是否在指定時間內發布"""
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        # 如果沒有時間資訊，假設是新的
        return True

    try:
        published_dt = datetime.fromtimestamp(calendar.timegm(published), tz=timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - published_dt
        return age < timedelta(hours=max_age_hours)
    except Exception:
        return True


def generate_item_id(link: str, title: str) -> str:
    content = f"{link}:{title}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


def fetch_rss(url: str) -> Optional[feedparser.FeedParserDict]:
    try:
        feed = feedparser.parse(
            url,
            request_headers={"User-Agent": USER_AGENT},
        )
        if feed.bozo and not feed.entries:
            return None
        return feed
    except Exception:
        return None


def get_rss_items(source: Dict) -> tuple[List[FeedItem], bool]:
    """取得 RSS 來源的文章

    Returns:
        tuple: (items, success) - items 是文章列表，success 表示是否成功連接
    """
    items = []
    feed = fetch_rss(source["url"])

    if feed is None:
        return items, False  # 連接失敗

    if not feed.entries:
        return items, True  # 連接成功但沒有文章

    for entry in feed.entries[:10]:  # 只處理最新 10 筆
        # 過濾掉超過 24 小時的文章
        if not is_recent(entry):
            continue

        item_id = generate_item_id(
            entry.get("link", ""),
            entry.get("title", "")
        )
        items.append(FeedItem(
            id=item_id,
            title=entry.get("title", "無標題"),
            link=entry.get("link", ""),
            source=source["name"],
            source_type=source.get("type", "website"),
        ))

    return items, True


def get_twitter_items(username: str) -> tuple[List[FeedItem], bool]:
    """透過 RSSHub 取得 Twitter/X 帳號的推文

    Returns:
        tuple: (items, success) - items 是推文列表，success 表示是否成功連接
    """
    items = []

    # 使用 RSSHub 的 Twitter 路由
    url = f"{RSSHUB_INSTANCE}/twitter/user/{username}"
    feed = fetch_rss(url)

    if feed is None:
        return items, False  # 連接失敗

    if not feed.entries:
        return items, True  # 連接成功但沒有推文

    for entry in feed.entries[:10]:
        # 過濾掉超過 1 小時的推文
        if not is_recent(entry, max_age_hours=TWITTER_MAX_AGE_HOURS):
            continue

        title = entry.get("title", "")
        if len(title) > 100:
            title = title[:97] + "..."

        item_id = generate_item_id(
            entry.get("link", ""),
            entry.get("title", "")
        )

        link = entry.get("link", "")

        items.append(FeedItem(
            id=item_id,
            title=title,
            link=link,
            source=f"@{username}",
            source_type="twitter",
        ))

    return items, True
