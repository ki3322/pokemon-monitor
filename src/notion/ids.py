"""Notion 識別碼的解析。

Notion 的頁面 ID 在網址、分享連結與 API 回應裡有數種寫法，
集中在這裡處理，避免每個進入點各寫一份正則。
"""
import re

# Notion 頁面 ID 是 32 位十六進位字元，可能以連字號分隔
_ID_PATTERN = re.compile(
    r"[0-9a-fA-F]{32}"
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# 從資料庫檢視打開某一列時，那一列的 ID 放在 p 參數
_ROW_PARAM_PATTERN = re.compile(r"[?&]p=([0-9a-fA-F]{32}|[0-9a-fA-F-]{36})")


def parse_page_id(value: str) -> str:
    """從網址或原始 ID 取出頁面 ID。找不到時回傳空字串。

    要分辨三種網址，差別都在查詢字串：
      - 一般頁面 `.../標題-<頁面ID>` —— ID 在路徑結尾
      - 資料庫   `.../<資料庫ID>?v=<檢視ID>` —— `v` 是檢視，不是資料庫本身
      - 資料庫的某一列 `.../<資料庫ID>?v=<檢視ID>&p=<列ID>` —— 使用者要的是那一列

    所以先看有沒有 `p` 參數，沒有的話只在路徑裡找，把查詢字串整段丟掉。
    """
    text = (value or "").strip()
    if not text:
        return ""

    row = _ROW_PARAM_PATTERN.search(text)
    if row:
        return row.group(1)

    # 只看路徑：查詢字串裡的 ID 都不是頁面本身
    path = text.split("?", 1)[0]
    matches = _ID_PATTERN.findall(path)

    # 標題 slug 也可能含十六進位字串，頁面 ID 一律在結尾
    return matches[-1] if matches else ""


def page_url(page_id: str) -> str:
    """把頁面 ID 轉成可點的網址。"""
    return f"https://www.notion.so/{page_id.replace('-', '')}" if page_id else ""
