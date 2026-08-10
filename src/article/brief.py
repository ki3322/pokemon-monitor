"""產生撰稿用的來源摘要檔。

摘要檔是交給撰稿者（Claude Code）的輸入：包含 Notion 頁面識別、
來源連結，以及抓回來的原文內容。
"""
import os
import re
from typing import Optional

from src.notion.reader import SelectedItem

# 檔名只保留安全字元
_UNSAFE_FILENAME = re.compile(r"[^0-9a-zA-Z._-]+")


def slug_for(item: SelectedItem) -> str:
    """由 page_id 產生穩定且安全的檔名前綴。"""
    return _UNSAFE_FILENAME.sub("", item.page_id.replace("-", ""))[:12] or "untitled"


def brief_path(directory: str, item: SelectedItem) -> str:
    return os.path.join(directory, f"{slug_for(item)}.brief.md")


def article_path(directory: str, item: SelectedItem) -> str:
    return os.path.join(directory, f"{slug_for(item)}.article.md")


def build_brief(item: SelectedItem, content: Optional[str]) -> str:
    """組出摘要檔內容。"""
    body = content or "（無法自動抓取原文，請直接開啟來源連結確認內容）"

    return "\n".join([
        "---",
        f"page_id: {item.page_id}",
        f"link: {item.link}",
        f"source: {item.source}",
        f"category: {item.category}",
        "---",
        "",
        f"# {item.title}",
        "",
        f"- 來源：{item.source}",
        f"- 連結：{item.link}",
        "",
        "## 原文內容",
        "",
        body,
        "",
    ])


def write_brief(directory: str, item: SelectedItem, content: Optional[str]) -> str:
    """把摘要寫進檔案並回傳路徑。"""
    os.makedirs(directory, exist_ok=True)
    path = brief_path(directory, item)
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_brief(item, content))
    return path
