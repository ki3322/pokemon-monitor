"""把寫好的文章回寫到 Notion 頁面。

頁面結構（由上而下）：
  1. 來源連結
  2. 摺疊的「WordPress HTML」區塊 —— 展開後點程式碼區塊的複製鈕即可貼上
  3. 分隔線
  4. 文章本體（Notion 原生排版，方便直接閱讀校稿）
"""
from typing import Dict, List, Optional

from src.article.html import markdown_to_html
from src.article.markdown import Span, extract_title, parse_markdown, strip_title
from src.notion import blocks as nb
from src.notion import schema
from src.notion.client import NotionClient

HTML_TOGGLE_LABEL = "📋 WordPress HTML（展開後點複製鈕，貼進 WordPress 程式碼編輯器）"


def _source_block(link: str) -> List[Dict]:
    if not link:
        return []
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": nb.render_spans([Span("👉 來源原文", href=link)])},
        }
    ]


def _html_toggle(html: str) -> Dict:
    """摺疊的 HTML 區塊，預設收起以免佔滿整頁。"""
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": nb.rich_text(HTML_TOGGLE_LABEL),
            "children": [nb.code_block(html, language="html")],
        },
    }


def build_page_blocks(markdown: str, link: str = "") -> List[Dict]:
    """由文章 Markdown 組出整頁的 Notion 區塊。"""
    html = markdown_to_html(markdown)
    body = parse_markdown(strip_title(markdown))

    return [
        *_source_block(link),
        _html_toggle(html),
        nb.divider_block(),
        *nb.render_blocks(body),
    ]


def _properties(markdown: str, wordpress_url: str = "") -> Dict:
    properties: Dict = {
        schema.STATUS: {"select": {"name": schema.STATUS_DONE}},
    }

    title = extract_title(markdown)
    if title:
        # 用定稿標題覆寫，Notion 列表就會顯示實際要上稿的標題
        properties[schema.TITLE] = {"title": [{"type": "text", "text": {"content": title}}]}

    if wordpress_url:
        properties[schema.WORDPRESS_URL] = {"url": wordpress_url}

    return properties


class NotionWriter:
    def __init__(self, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()

    def is_configured(self) -> bool:
        return self.client.is_configured()

    def clear_page(self, page_id: str) -> bool:
        """刪除頁面既有內容，讓重新發布不會疊加出兩份文章。"""
        children = self.client.list_children(page_id)
        if children is None:
            # 讀不到既有內容不能當成「頁面是空的」，照樣附加會疊成兩份
            return False
        for block in children:
            if not self.client.delete_block(block.get("id", "")):
                return False
        return True

    def publish(
        self,
        page_id: str,
        markdown: str,
        link: str = "",
        wordpress_url: str = "",
        replace: bool = True,
    ) -> bool:
        """把文章寫進頁面並把狀態設為已完成。成功回傳 True。"""
        if not self.is_configured():
            print("[Error] Notion 未設定（需要 NOTION_TOKEN 與 NOTION_DATABASE_ID）")
            return False

        if replace and not self.clear_page(page_id):
            print("[Error] 清除頁面既有內容失敗，已中止以免產生重複內容")
            return False

        page_blocks = build_page_blocks(markdown, link)
        for batch in nb.batched(page_blocks):
            if not self.client.append_blocks(page_id, batch):
                print("[Error] 寫入頁面內容失敗")
                return False

        if self.client.update_page(page_id, _properties(markdown, wordpress_url)) is None:
            print("[Error] 更新頁面屬性失敗（內容已寫入，但狀態未變更）")
            return False

        return True
