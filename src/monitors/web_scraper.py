"""無 RSS 網站的爬蟲。

每個爬蟲都回傳 (items, success)，讓「抓取失敗 / 版面改版」能與
「今天沒有新內容」區分開來 —— 否則監控會無聲失效。
"""
from typing import Callable, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from src.http_client import fetch
from src.models import FeedItem, generate_item_id, truncate_title

ScrapeResult = Tuple[List[FeedItem], bool]

# 從連結中抽標題時優先採用的標題元素
TITLE_TAGS = ("h1", "h2", "h3", "h4")

# 相對連結補全用的網站根網址
SEREBII_BASE_URL = "https://www.serebii.net"
POKEMON_INFO_BASE_URL = "https://pokemon-infomation.com/"
TOY_PEOPLE_BASE_URL = "https://www.toy-people.com"

# 每輪最多抓取的項目數：首頁列表以外的都是舊文，抓多只是浪費
SEREBII_MAX_HEADLINES = 10
POKEMON_INFO_MAX_ITEMS = 10
POKEBEACH_MAX_ARTICLES = 15
TOY_PEOPLE_MAX_CARDS = 15

# 過短的連結文字多半是「更多」「首頁」之類的導覽元素，不是文章標題
MIN_TITLE_LENGTH = 10


def fetch_page(url: str) -> Optional[BeautifulSoup]:
    response = fetch(url)
    if response is None:
        return None
    return BeautifulSoup(response.text, "html.parser")


def extract_title(tag) -> str:
    """從連結元素中取出標題。

    優先取內層的標題元素：整個卡片連結常常還包住日期、分類等 metadata，
    直接對外層做 get_text 會把「2026-06-02再販・抽選情報」這類文字
    黏在標題後面，既難看又會讓標題隨網站更新而改變。
    """
    for name in TITLE_TAGS:
        heading = tag.find(name)
        if heading:
            text = heading.get_text(strip=True)
            if text:
                return text
    return tag.get_text(strip=True)


def _make_item(link: str, title: str, source_name: str) -> Optional[FeedItem]:
    item_id = generate_item_id(link)
    if not item_id or not title:
        return None
    return FeedItem(
        id=item_id,
        title=truncate_title(title),
        link=link,
        source=source_name,
    )


def _absolute(link: str, base: str) -> str:
    if link.startswith("http"):
        return link
    return base.rstrip("/") + "/" + link.lstrip("/")


def scrape_serebii(source: Dict) -> ScrapeResult:
    """爬取 Serebii.net 新聞。

    每個 h2 對應一個「當日彙整頁」，標題會整天累加新主題，
    因此項目 ID 只以連結計算，同一天只會通知一次。
    """
    soup = fetch_page(source["url"])
    if soup is None:
        return [], False

    items = []
    for h2 in soup.find_all("h2", limit=SEREBII_MAX_HEADLINES):
        link_tag = h2.find("a", href=True)
        if not link_tag:
            continue

        link = _absolute(link_tag["href"], SEREBII_BASE_URL)
        item = _make_item(link, link_tag.get_text(strip=True), source["name"])
        if item:
            items.append(item)

    return items, True


def scrape_pokemon_infomation(source: Dict) -> ScrapeResult:
    """爬取 Pokemon Information 網站。"""
    soup = fetch_page(source["url"])
    if soup is None:
        return [], False

    base = POKEMON_INFO_BASE_URL
    # 這些路徑是分類頁與靜態頁，不是文章
    excluded_paths = ("/category/", "/contact/", "/privacy", "/profile/")

    items = []
    seen_links = set()

    for link_tag in soup.find_all("a", href=True):
        link = link_tag["href"]

        if not link.startswith(base):
            continue
        if any(path in link for path in excluded_paths):
            continue
        if link.rstrip("/") == base.rstrip("/"):
            continue
        if link in seen_links:
            continue
        seen_links.add(link)

        title = extract_title(link_tag)
        if len(title) < MIN_TITLE_LENGTH:
            continue

        item = _make_item(link, title, source["name"])
        if item:
            items.append(item)

        if len(items) >= POKEMON_INFO_MAX_ITEMS:
            break

    return items, True


def scrape_pokebeach(source: Dict) -> ScrapeResult:
    """爬取 PokeBeach 新聞。"""
    soup = fetch_page(source["url"])
    if soup is None:
        return [], False

    items = []
    for article in soup.find_all("article", limit=POKEBEACH_MAX_ARTICLES):
        h2 = article.find("h2", class_="entry-title")
        if not h2:
            continue

        link_tag = h2.find("a", href=True)
        if not link_tag:
            continue

        item = _make_item(link_tag["href"], link_tag.get_text(strip=True), source["name"])
        if item:
            items.append(item)

    return items, True


def scrape_toy_people(source: Dict) -> ScrapeResult:
    """爬取 玩具人 toy-people.com 文章列表。"""
    soup = fetch_page(source["url"])
    if soup is None:
        return [], False

    items = []
    for card in soup.find_all("div", class_="card")[:TOY_PEOPLE_MAX_CARDS]:
        text_div = card.find("div", class_="text")
        if not text_div:
            continue

        h2 = text_div.find("h2")
        if not h2:
            continue

        link_tag = h2.find("a", href=True)
        if not link_tag:
            continue

        link = _absolute(link_tag["href"], TOY_PEOPLE_BASE_URL)
        item = _make_item(link, link_tag.get_text(strip=True), source["name"])
        if item:
            items.append(item)

    return items, True


# 網域 -> 爬蟲函式
SCRAPERS: Tuple[Tuple[str, Callable[[Dict], ScrapeResult]], ...] = (
    ("serebii.net", scrape_serebii),
    ("pokemon-infomation.com", scrape_pokemon_infomation),
    ("pokebeach.com", scrape_pokebeach),
    ("toy-people.com", scrape_toy_people),
)


def find_scraper(url: str) -> Optional[Callable[[Dict], ScrapeResult]]:
    """找出處理該網址的爬蟲，沒有對應時回傳 None。"""
    for domain, scraper in SCRAPERS:
        if domain in url:
            return scraper
    return None


def get_scraped_items(source: Dict) -> ScrapeResult:
    """依來源網址分派到對應的爬蟲。

    Raises:
        ValueError: 沒有對應的爬蟲。設定錯誤必須立刻報錯，
            不能無聲回傳空清單導致該來源永遠不被監控。
    """
    url = source.get("url", "")
    scraper = find_scraper(url)
    if scraper is None:
        raise ValueError(f"沒有對應的爬蟲可處理來源網址: {url}")
    return scraper(source)
