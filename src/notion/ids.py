"""Notion 識別碼的解析。

Notion 的頁面 ID 在網址、分享連結與 API 回應裡有三種寫法，
集中在這裡處理，避免每個進入點各寫一份正則。
"""
import re

# Notion 頁面 ID 是 32 位十六進位字元，可能以連字號分隔
_PAGE_ID_PATTERN = re.compile(
    r"([0-9a-fA-F]{32})"
    r"|([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def parse_page_id(value: str) -> str:
    """從網址或原始 ID 取出頁面 ID。找不到時回傳空字串。"""
    matches = _PAGE_ID_PATTERN.findall((value or "").strip())
    if not matches:
        return ""
    # findall 回傳分組 tuple，取有值的那一組；網址結尾的 ID 才是頁面本身
    last = matches[-1]
    return last[0] or last[1]


def page_url(page_id: str) -> str:
    """把頁面 ID 轉成可點的網址。"""
    return f"https://www.notion.so/{page_id.replace('-', '')}" if page_id else ""
