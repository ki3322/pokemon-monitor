import requests
from bs4 import BeautifulSoup
import hashlib
from typing import List, Dict, Optional
from dataclasses import dataclass
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import REQUEST_TIMEOUT, USER_AGENT


@dataclass
class ScrapedItem:
    id: str
    title: str
    link: str
    source: str
    source_type: str = "website"


def generate_item_id(link: str, title: str) -> str:
    content = f"{link}:{title}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


def fetch_page(url: str) -> Optional[BeautifulSoup]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"    [Error] Failed to fetch {url}: {e}")
        return None


def scrape_serebii(source: Dict) -> List[ScrapedItem]:
    """爬取 Serebii.net 新聞"""
    items = []
    soup = fetch_page(source["url"])

    if soup is None:
        return items

    # Serebii 新聞格式: <h2><a href="...">標題</a></h2>
    for h2 in soup.find_all("h2", limit=10):
        link_tag = h2.find("a")
        if not link_tag or not link_tag.get("href"):
            continue

        link = link_tag.get("href", "")
        if not link.startswith("http"):
            link = "https://www.serebii.net" + link

        title = link_tag.get_text(strip=True)
        if not title:
            continue

        item_id = generate_item_id(link, title)
        items.append(ScrapedItem(
            id=item_id,
            title=title[:100] + "..." if len(title) > 100 else title,
            link=link,
            source=source["name"],
        ))

    return items



def scrape_pokemon_infomation(source: Dict) -> List[ScrapedItem]:
    """爬取 Pokemon Information 網站"""
    items = []
    soup = fetch_page(source["url"])

    if soup is None:
        return items

    # 尋找文章連結 (排除導航連結)
    seen_links = set()
    for link_tag in soup.find_all("a", href=True):
        link = link_tag.get("href", "")

        # 只處理文章連結
        if not link.startswith("https://pokemon-infomation.com/"):
            continue

        # 排除分類頁和特殊頁面
        if "/category/" in link or "/contact/" in link or "/privacy" in link or "/profile/" in link:
            continue

        # 排除首頁
        if link == "https://pokemon-infomation.com/" or link == "https://pokemon-infomation.com":
            continue

        if link in seen_links:
            continue

        seen_links.add(link)
        title = link_tag.get_text(strip=True)

        # 過濾太短或是導航文字
        if not title or len(title) < 10:
            continue

        item_id = generate_item_id(link, title)
        items.append(ScrapedItem(
            id=item_id,
            title=title[:100] + "..." if len(title) > 100 else title,
            link=link,
            source=source["name"],
        ))

        if len(items) >= 10:
            break

    return items


def scrape_pokebeach(source: Dict) -> List[ScrapedItem]:
    """爬取 PokeBeach 新聞"""
    items = []
    soup = fetch_page(source["url"])

    if soup is None:
        return items

    # PokeBeach 格式: <article> 內含 <h2 class="entry-title"><a href="...">標題</a></h2>
    for article in soup.find_all("article", limit=15):
        h2 = article.find("h2", class_="entry-title")
        if not h2:
            continue

        link_tag = h2.find("a")
        if not link_tag or not link_tag.get("href"):
            continue

        link = link_tag.get("href", "")
        title = link_tag.get_text(strip=True)

        if not title:
            continue

        item_id = generate_item_id(link, title)
        items.append(ScrapedItem(
            id=item_id,
            title=title[:100] + "..." if len(title) > 100 else title,
            link=link,
            source=source["name"],
        ))

    return items


def get_scraped_items(source: Dict) -> List[ScrapedItem]:
    url = source.get("url", "")

    if "serebii.net" in url:
        return scrape_serebii(source)
    elif "pokemon-infomation.com" in url:
        return scrape_pokemon_infomation(source)
    elif "pokebeach.com" in url:
        return scrape_pokebeach(source)

    return []
