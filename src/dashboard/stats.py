"""從既有狀態推導儀表板要顯示的數字。

這個模組是純函式：輸入是已經讀好的資料結構，輸出是不可變的統計物件。
所有 I/O 都留在 collect.py，讓數字本身可以被單獨測試。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from src.notion import schema
from src.notion.reader import SelectedItem
from src.state import MAX_ITEMS_PER_SOURCE, SINK_NOTION, SINK_TELEGRAM

KIND_WEBSITE = "website"
KIND_TWITTER = "twitter"


@dataclass(frozen=True)
class GroupStat:
    """一個共用已讀記錄的來源群組。"""

    group: str
    kind: str
    members: Tuple[str, ...] = ()
    telegram: int = 0
    notion: int = 0

    @property
    def tracked(self) -> int:
        """記錄中的項目數，取兩個目的地的較大值。"""
        return max(self.telegram, self.notion)

    @property
    def is_saturated(self) -> bool:
        """是否已達每個群組的記錄上限（超過的舊記錄會被捨棄）。"""
        return self.tracked >= MAX_ITEMS_PER_SOURCE

    @property
    def is_bootstrapped(self) -> bool:
        return self.telegram > 0 or self.notion > 0


@dataclass(frozen=True)
class Stage:
    """流程漏斗的一段。"""

    label: str
    count: int
    note: str = ""


@dataclass(frozen=True)
class DraftStat:
    """drafts/ 目錄裡的一份稿件進度。"""

    slug: str
    has_brief: bool = False
    has_article: bool = False

    @property
    def status(self) -> str:
        if self.has_article:
            return "已成稿"
        return "撰寫中" if self.has_brief else "未知"


@dataclass(frozen=True)
class NewsStat:
    """Notion 資料庫裡的一則新聞（儀表板顯示用）。"""

    title: str
    link: str
    source: str
    status: str
    selected: bool
    days_old: Optional[int]  # 距發現日的日曆天數；None 表示沒有可用的發現時間

    @property
    def freshness(self) -> str:
        """與 Notion 的新鮮度欄位同一套標記，但按日曆日計算（昨天不算今天）。"""
        if self.days_old is None:
            return "—"
        if self.days_old <= 0:
            return "🔥 今天"
        if self.days_old <= 3:
            return "🟡 3 天內"
        if self.days_old <= 7:
            return "⚪ 一週內"
        return "🕓 較舊"


@dataclass(frozen=True)
class Dashboard:
    generated_at: str
    state_version: object = None
    notion_configured: bool = False
    groups: Tuple[GroupStat, ...] = field(default_factory=tuple)
    drafts: Tuple[DraftStat, ...] = field(default_factory=tuple)
    # None = 沒抓（Notion 未設定或查詢失敗）；空 tuple = 資料庫是空的
    news: Optional[Tuple[NewsStat, ...]] = None

    @property
    def website_groups(self) -> Tuple[GroupStat, ...]:
        return tuple(g for g in self.groups if g.kind == KIND_WEBSITE)

    @property
    def twitter_groups(self) -> Tuple[GroupStat, ...]:
        return tuple(g for g in self.groups if g.kind == KIND_TWITTER)

    @property
    def total_tracked(self) -> int:
        return sum(g.tracked for g in self.groups)

    @property
    def total_notion(self) -> int:
        return sum(g.notion for g in self.groups)

    @property
    def pending_groups(self) -> Tuple[GroupStat, ...]:
        """尚未初始化的群組：下一輪只會記錄現況，不會發通知。"""
        return tuple(g for g in self.groups if not g.is_bootstrapped)

    @property
    def queue(self) -> Tuple[NewsStat, ...]:
        """待撰稿佇列：已勾選「寫成文章」且尚未完成的項目。"""
        if not self.news:
            return ()
        return tuple(n for n in self.news if n.selected and n.status != schema.STATUS_DONE)

    @property
    def news_status_counts(self) -> Tuple[Tuple[str, int], ...]:
        """各狀態的筆數，依 schema 的狀態順序，略過 0 的。"""
        if not self.news:
            return ()
        counts = {status: 0 for status in schema.STATUS_OPTIONS}
        for item in self.news:
            counts[item.status] = counts.get(item.status, 0) + 1
        return tuple((status, count) for status, count in counts.items() if count)

    @property
    def stages(self) -> Tuple[Stage, ...]:
        articles = sum(1 for d in self.drafts if d.has_article)
        writing = sum(1 for d in self.drafts if d.has_brief and not d.has_article)
        return (
            Stage("監控來源", len(self.groups), "RSS · 網頁 · Twitter"),
            Stage("Telegram 記錄", sum(g.telegram for g in self.groups), "已推播"),
            Stage("Notion 記錄", self.total_notion, "可勾選"),
            Stage("撰寫中", writing, "已抓原文"),
            Stage("已成稿", articles, "可貼 WordPress"),
        )


def _sink_records(delivered: Dict, sink: str) -> Dict[str, List[str]]:
    records = (delivered or {}).get(sink) or {}
    return records if isinstance(records, dict) else {}


def _count(records: Dict[str, List[str]], group: str) -> int:
    return len(records.get(group) or [])


def build_groups(
    rss_sources: Sequence[Dict],
    scrape_sources: Sequence[Dict],
    twitter_accounts: Sequence[str],
    delivered: Dict,
) -> Tuple[GroupStat, ...]:
    """把設定檔的來源清單與狀態檔的投遞記錄合併成群組統計。

    共用 group 的來源（例如玩具人的兩個標籤頁）會合併成同一筆，
    因為它們的已讀記錄本來就是共用的。
    """
    telegram = _sink_records(delivered, SINK_TELEGRAM)
    notion = _sink_records(delivered, SINK_NOTION)

    # 保留設定檔的順序，同時合併同群組的成員
    order: List[Tuple[str, str]] = []
    members: Dict[Tuple[str, str], Tuple[str, ...]] = {}

    def add(group: str, kind: str, member: str) -> None:
        key = (group, kind)
        if key not in members:
            order.append(key)
            members[key] = ()
        members[key] = members[key] + (member,)

    for source in list(rss_sources) + list(scrape_sources):
        name = source.get("name", "")
        add(source.get("group") or name, KIND_WEBSITE, name)

    for username in twitter_accounts:
        add(f"twitter_{username}", KIND_TWITTER, f"@{username}")

    return tuple(
        GroupStat(
            group=group,
            kind=kind,
            members=members[(group, kind)],
            telegram=_count(telegram, group),
            notion=_count(notion, group),
        )
        for group, kind in order
    )


def _days_old(found_at: str, now: datetime) -> Optional[int]:
    """發現時間距今的日曆天數；無法解析時回傳 None（顯示為未知）。"""
    if not found_at:
        return None
    try:
        found = datetime.fromisoformat(found_at)
    except ValueError:
        return None

    if found.tzinfo is not None:
        # Notion 回傳 UTC；換成本機時區再取日期，「今天」才是使用者的今天
        found = found.astimezone()
    return max((now.date() - found.date()).days, 0)


def build_news(items: Sequence[SelectedItem], now: datetime) -> Tuple[NewsStat, ...]:
    """把 Notion 讀回的項目轉成儀表板要顯示的新聞列表。"""
    return tuple(
        NewsStat(
            title=item.title,
            link=item.link,
            source=item.source,
            status=item.status,
            selected=item.selected,
            days_old=_days_old(item.found_at, now),
        )
        for item in items
    )


def build_drafts(filenames: Sequence[str]) -> Tuple[DraftStat, ...]:
    """從 drafts/ 的檔名推導撰稿進度。

    命名慣例：<slug>.brief.md 為來源摘要，<slug>.article.md 為稿件。
    """
    briefs = {name[: -len(".brief.md")] for name in filenames if name.endswith(".brief.md")}
    articles = {name[: -len(".article.md")] for name in filenames if name.endswith(".article.md")}

    return tuple(
        DraftStat(slug=slug, has_brief=slug in briefs, has_article=slug in articles)
        for slug in sorted(briefs | articles)
    )
