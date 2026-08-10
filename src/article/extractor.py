"""從來源網址抓取可讀的文章正文。

寫稿需要原文內容，而監控只保存標題與連結，因此撰稿前要再抓一次全文。
抽取策略由精確到寬鬆：常見的內文容器 → <article> / <main> → 全頁文字。
"""
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from src.http_client import fetch

# 由精確到寬鬆的內文容器選擇器
_CONTENT_SELECTORS = [
    "article .entry-content",
    ".entry-content",
    ".post-content",
    ".article-content",
    ".article-contents",
    ".post-body",
    "article",
    "main",
]

# 這些元素不是內文，抽取前先移除
_NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe"]

# class 名稱含這些字樣的元素同樣不是內文（分享列、留言、相關文章等）。
# 必須比對「完整的 class 詞彙」而非任意子字串：版面用的 class 常含這些字，
# 例如 `p-body-main--withSidebar`、`-sidebar-on`，誤刪會整段內文消失。
_NOISE_CLASS = re.compile(
    r"(^|[-_])(share|sharing|social|comments?|related|breadcrumbs?|pagination|authorbox|author-box|taglist|tag-list)([-_]|$)",
    re.IGNORECASE,
)

# 只移除文字量佔全頁比例低於此值的元素。分享列、麵包屑都很小；
# 若某個「疑似雜訊」的元素裝著大半頁面文字，那它其實是版面容器，不能刪。
MAX_NOISE_TEXT_RATIO = 0.3

# 短於這個長度的抽取結果視為失敗，改用下一個策略
MIN_CONTENT_LENGTH = 200

# 交給撰稿者的正文長度上限
MAX_CONTENT_LENGTH = 12000


def _clean(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    total = len(soup.get_text(strip=True)) or 1

    for tag in soup.find_all(class_=_NOISE_CLASS):
        # 父層可能已被移除，子節點就不必再處理
        if tag.decomposed or tag.name in ("html", "body"):
            continue
        if len(tag.get_text(strip=True)) / total <= MAX_NOISE_TEXT_RATIO:
            tag.decompose()

    return soup


def _dedupe(parts: List[str]) -> List[str]:
    """移除重複段落。

    不少網站會為了響應式版面或 SEO 摘要把正文輸出兩次，
    整段重複會白白吃掉撰稿者的上下文，也容易讓事實被重複解讀。
    """
    seen = set()
    unique = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique.append(part)
    return unique


def _text_of(node) -> str:
    """取出節點內的段落文字，保留段落分行。"""
    parts: List[str] = []
    for element in node.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = element.get_text(" ", strip=True)
        if text:
            parts.append(text)

    if parts:
        return "\n\n".join(_dedupe(parts))
    return node.get_text("\n", strip=True)


def extract_content(html: str) -> str:
    """從 HTML 抽出正文純文字。抽不到時回傳空字串。"""
    soup = _clean(BeautifulSoup(html, "html.parser"))

    for selector in _CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        text = _text_of(node)
        if len(text) >= MIN_CONTENT_LENGTH:
            return text[:MAX_CONTENT_LENGTH]

    body = soup.body or soup
    return _text_of(body)[:MAX_CONTENT_LENGTH]


def fetch_content(url: str) -> Optional[str]:
    """抓取網址並抽出正文。連線或抽取失敗時回傳 None。"""
    if not url:
        return None

    response = fetch(url)
    if response is None:
        return None

    content = extract_content(response.text)
    if len(content) < MIN_CONTENT_LENGTH:
        print(f"    [Warning] {url} 抽取到的內文過短（{len(content)} 字），可能需要人工確認")

    return content or None
