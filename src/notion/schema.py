"""Notion 資料庫的欄位定義。

欄位名稱集中在這裡，setup 腳本、同步與讀取都引用同一份常數，
避免任何一邊改名造成靜默失效。
"""

# 欄位名稱
TITLE = "標題"
ORIGINAL_TITLE = "原始標題"
LINK = "連結"
SOURCE = "來源"
CATEGORY = "類型"
FOUND_AT = "發現時間"
SELECTED = "寫成文章"
STATUS = "狀態"
ITEM_ID = "項目ID"
WORDPRESS_URL = "WordPress"
FRESHNESS = "新鮮度"
PUBLISHED = "上稿"

DATABASE_ICON = "📰"
DATABASE_DESCRIPTION = (
    "監控自動寫入。勾選「寫成文章」→ 執行 python -m src.cli pending → "
    "寫稿 → publish 回寫。標題會在發布時換成定稿標題，原始標題保留在「原始標題」欄。"
)

# 寶可夢情報退燒很快，用發現時間換算出好掃描的新鮮度標記。
# dateBetween(now(), 發現時間, "days") 為經過的天數。
FRESHNESS_FORMULA = (
    f'if(empty(prop("{FOUND_AT}")), "—", '
    f'if(dateBetween(now(), prop("{FOUND_AT}"), "days") <= 1, "🔥 今天", '
    f'if(dateBetween(now(), prop("{FOUND_AT}"), "days") <= 3, "🟡 3 天內", '
    f'if(dateBetween(now(), prop("{FOUND_AT}"), "days") <= 7, "⚪ 一週內", "🕓 較舊"))))'
)

# 「已完成」只代表稿子寫完，不代表貼上 WordPress 了。
# 用 WordPress 欄位是否有值自動推導，不必再手動維護一個狀態。
PUBLISHED_FORMULA = f'if(empty(prop("{WORDPRESS_URL}")), "⬜ 未上稿", "✅ 已上稿")'

# 狀態選項
STATUS_PENDING = "待處理"
STATUS_WRITING = "撰寫中"
STATUS_DONE = "已完成"
STATUS_SKIPPED = "略過"

STATUS_OPTIONS = [STATUS_PENDING, STATUS_WRITING, STATUS_DONE, STATUS_SKIPPED]

# 類型選項
CATEGORY_ARTICLE = "文章"
CATEGORY_TWEET = "推文"

CATEGORY_OPTIONS = [CATEGORY_ARTICLE, CATEGORY_TWEET]


def database_properties() -> dict:
    """建立資料庫時使用的屬性定義。

    來源刻意用 rich_text 而非 select：select 選項若未預先建立，
    寫入未知值會被 Notion 拒絕，新增監控來源時就會靜默失敗。
    """
    return {
        TITLE: {"title": {}},
        ORIGINAL_TITLE: {"rich_text": {}},
        LINK: {"url": {}},
        SOURCE: {"rich_text": {}},
        CATEGORY: {"select": {"options": [{"name": name} for name in CATEGORY_OPTIONS]}},
        FOUND_AT: {"date": {}},
        SELECTED: {"checkbox": {}},
        STATUS: {"select": {"options": [{"name": name} for name in STATUS_OPTIONS]}},
        ITEM_ID: {"rich_text": {}},
        WORDPRESS_URL: {"url": {}},
        FRESHNESS: {"formula": {"expression": FRESHNESS_FORMULA}},
        PUBLISHED: {"formula": {"expression": PUBLISHED_FORMULA}},
    }


def missing_properties(existing: dict) -> dict:
    """回傳既有資料庫還缺的欄位定義。

    只補缺的，絕不重送已存在的欄位——PATCH 送出同名欄位會覆寫它的設定，
    使用者在 Notion 手動調整過的選項就會被打回預設值。
    """
    return {
        name: definition
        for name, definition in database_properties().items()
        if name not in (existing or {})
    }


def category_for(source_type: str) -> str:
    return CATEGORY_TWEET if source_type == "twitter" else CATEGORY_ARTICLE
