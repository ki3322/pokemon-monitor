import os

# Telegram 設定
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# RSSHub 實例 (用於 Twitter/X 監控)
RSSHUB_INSTANCE = "https://pokemonhubs.zeabur.app"

# Nitter 實例列表 (已棄用，改用 RSSHub)
NITTER_INSTANCES = []

# RSS 來源 (網站)
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
    {
        "name": "玩具人 寶可夢",
        "url": "https://www.toy-people.com/?tag=%E5%AF%B6%E5%8F%AF%E5%A4%A2",
        "type": "website",
    },
    {
        "name": "玩具人 寶可夢中心",
        "url": "https://www.toy-people.com/?tag=%E5%AF%B6%E5%8F%AF%E5%A4%A2%E4%B8%AD%E5%BF%83",
        "type": "website",
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

# 狀態檔案路徑
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

# 請求設定
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
