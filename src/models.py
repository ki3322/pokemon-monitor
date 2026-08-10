"""共用的資料模型與項目 ID 產生邏輯。"""
import hashlib
from dataclasses import dataclass

# 通知標題的最大長度
MAX_TITLE_LENGTH = 100


@dataclass(frozen=True)
class FeedItem:
    """一則待通知的內容（文章或推文）。"""

    id: str
    title: str
    link: str
    source: str
    source_type: str = "website"  # 'website' 或 'twitter'


def generate_item_id(link: str, guid: str = "") -> str:
    """由穩定識別碼產生項目 ID。

    只使用 guid / 連結，「絕對不使用標題」：標題會隨網站更新而變動
    （例如 Serebii 的當日彙整標題會整天累加、Pokemon Information 的
    標題含有最後更新日期），若把標題納入雜湊，同一篇文章會被反覆通知。

    Returns:
        16 位元的十六進位字串；沒有可用識別碼時回傳空字串。
    """
    key = (guid or link).strip()
    if not key:
        return ""
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def truncate_title(title: str, max_length: int = MAX_TITLE_LENGTH) -> str:
    """把過長的標題截斷並補上刪節號。"""
    if len(title) <= max_length:
        return title
    return title[: max_length - 3] + "..."


def source_group(source: dict) -> str:
    """取得來源的去重群組。

    多個設定項目可以透過 `group` 共用同一份已讀記錄，避免同一篇文章
    因為出現在不同標籤頁而被通知兩次。未指定時以 `name` 為群組。
    """
    return source.get("group") or source["name"]
