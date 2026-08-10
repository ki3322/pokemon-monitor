"""讀取檔案系統與設定，組出儀表板資料。

刻意不透過 StateManager 讀狀態：StateManager 在版本不符時會直接回傳空狀態，
儀表板需要如實顯示「目前檔案裡是什麼版本」，才看得出下一輪會不會重新初始化。
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from config import DRAFTS_DIR, NOTION_DATABASE_ID, NOTION_TOKEN, STATE_FILE
from config import RSS_SOURCES, SCRAPE_SOURCES, TWITTER_ACCOUNTS
from src.dashboard.stats import Dashboard, NewsStat, build_drafts, build_groups, build_news
from src.state import STATE_VERSION

# 儀表板顯示的最近新聞筆數
NEWS_LIMIT = 30


def read_state(path: str = STATE_FILE) -> Tuple[object, Dict]:
    """回傳 (版本, 投遞記錄)。

    版本不符時投遞記錄一律視為空的——這與 StateManager 的行為一致，
    儀表板不該顯示下一輪其實不會採用的數字。
    """
    if not os.path.exists(path):
        return None, {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError) as error:
        print(f"[Warn] 無法讀取狀態檔 {path}: {error}")
        return None, {}

    if not isinstance(loaded, dict):
        return None, {}

    version = loaded.get("version")
    if version != STATE_VERSION:
        return version, {}

    return version, loaded.get("delivered") or {}


def list_drafts(directory: str = DRAFTS_DIR) -> List[str]:
    if not os.path.isdir(directory):
        return []
    try:
        return sorted(os.listdir(directory))
    except OSError as error:
        print(f"[Warn] 無法讀取草稿目錄 {directory}: {error}")
        return []


def fetch_news(news_reader, now: datetime) -> Optional[Tuple[NewsStat, ...]]:
    """從 Notion 抓最近的新聞。

    沒給 reader 或未設定時回傳 None（顯示為未設定）；
    查詢失敗也回傳 None，但要留下明確痕跡——儀表板照樣產生，只是少了新聞列表。
    """
    if news_reader is None or not news_reader.is_configured():
        return None

    items = news_reader.recent_items(NEWS_LIMIT)
    if items is None:
        print("[Warn] Notion 查詢失敗，本次儀表板不含新聞列表")
        return None

    return build_news(items, now)


def build_dashboard(
    state_file: str = STATE_FILE,
    drafts_dir: str = DRAFTS_DIR,
    now: datetime = None,
    news_reader=None,
) -> Dashboard:
    version, delivered = read_state(state_file)
    now = now or datetime.now()

    return Dashboard(
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        state_version=version,
        notion_configured=bool(NOTION_TOKEN and NOTION_DATABASE_ID),
        groups=build_groups(RSS_SOURCES, SCRAPE_SOURCES, TWITTER_ACCOUNTS, delivered),
        drafts=build_drafts(list_drafts(drafts_dir)),
        news=fetch_news(news_reader, now),
    )
