import os

# Telegram 設定
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# RSSHub 實例 (用於 Twitter/X 監控)
# 必須用 or 而不是 os.environ.get 的預設值：GitHub Actions 在
# ${{ vars.RSSHUB_INSTANCE }} 未定義時仍會把環境變數設成「空字串」，
# 空字串不是 None，預設值永遠不會生效，網址就變成 /twitter/user/xxx 而無 scheme。
RSSHUB_INSTANCE = (
    os.environ.get("RSSHUB_INSTANCE", "").strip() or "https://pokemonhubs.zeabur.app"
).rstrip("/")

# Notion 設定 (選填；未設定時自動略過 Notion 同步)
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")

# 撰稿工作目錄 (存放來源摘要與草稿)
DRAFTS_DIR = os.path.join(os.path.dirname(__file__), "drafts")

# RSS 來源 (網站)
#   name      顯示名稱
#   url       feed 網址
#   group     選填，共用已讀記錄的群組（預設為 name）
#   translate 選填，是否翻譯標題（預設 True；已是繁中的來源請設 False）
RSS_SOURCES = [
    {
        "name": "Pokemon GO Hub",
        "url": "https://pokemongohub.net/feed/",
        "type": "website",
    },
]

# 網頁爬蟲來源 (無 RSS 的網站)
SCRAPE_SOURCES = [
    {
        "name": "Serebii.net",
        "url": "https://www.serebii.net/index2.shtml",
        "type": "website",
    },
    {
        "name": "Pokemon Information",
        "url": "https://pokemon-infomation.com/",
        "type": "website",
    },
    {
        "name": "PokeBeach",
        "url": "https://www.pokebeach.com/",
        "type": "website",
    },
    # 以下兩個標籤頁的文章大量重疊，共用 group 以免同一篇被通知兩次。
    # 內容本身已是繁體中文，不需要翻譯。
    {
        "name": "玩具人 寶可夢",
        "url": "https://www.toy-people.com/?tag=%E5%AF%B6%E5%8F%AF%E5%A4%A2",
        "type": "website",
        "group": "玩具人",
        "translate": False,
    },
    {
        "name": "玩具人 寶可夢中心",
        "url": "https://www.toy-people.com/?tag=%E5%AF%B6%E5%8F%AF%E5%A4%A2%E4%B8%AD%E5%BF%83",
        "type": "website",
        "group": "玩具人",
        "translate": False,
    },
]

# Twitter/X 帳號 (透過 RSSHub)
TWITTER_ACCOUNTS = [
    "PokemonGoApp",
    "Zabi_pokeka",
    "pokecamatomeru",
    "UniteVids",
    "pokerapidinfo",
    "pokepoke_GW",
    "pokemongoappko",
]

# 不同步到 Notion 的來源群組。
#
# 這裡列的來源「仍會發 Telegram 通知」，只是不進「Pokemon 新聞待撰稿」資料庫——
# 適合那些值得知道、但不會拿來寫成文章的來源。
#
# 群組 ID 的寫法：網站來源用 name（有設 group 就用 group），
# Twitter 帳號用 twitter_<帳號>。打錯字會在啟動時直接報錯，不會靜默失效。
NOTION_EXCLUDED_GROUPS = {
    "twitter_UniteVids",  # 以影片為主，不寫成文章
}

# 狀態檔案路徑
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

# 請求設定
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
