import os

# Telegram 設定
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Nitter 實例列表 (按優先順序)
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.cz",
]

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
]

# Twitter 帳號 (透過 Nitter RSS)
# 注意: Nitter 實例目前大多已失效，Twitter 監控功能暫時停用
# 如需啟用，請取消下方註解並確認有可用的 Nitter 實例
TWITTER_ACCOUNTS = [
    # "PokemonGoApp",
    # "Zabi_pokeka",
    # "pokecamatomeru",
    # "UniteVids",
    # "pokerapidinfo",
    # "pokepoke_GW",
    # "pokemongoappko",
    # "snkrdunk_akiba",
]

# 狀態檔案路徑
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

# 請求設定
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
