"""投遞目的地。

每個目的地把「送出一則內容」包成統一介面，主流程就不必知道
Telegram 與 Notion 的差異，也能各自獨立記錄成功與失敗。

目的地也各自決定要不要收某個來源群組（`accepts`），
讓「這個來源只發 Telegram、不進 Notion」不必在主流程寫特例。
"""
from typing import Iterable, List, Optional, Set

from config import NOTION_EXCLUDED_GROUPS
from src.models import FeedItem
from src.notifier import TelegramNotifier
from src.notion.sync import NotionSync
from src.state import SINK_NOTION, SINK_TELEGRAM


class TelegramSink:
    name = SINK_TELEGRAM
    label = "Telegram"

    def __init__(self, notifier: TelegramNotifier):
        self.notifier = notifier

    def accepts(self, group_id: str) -> bool:
        """Telegram 收所有來源：排除設定只針對 Notion。"""
        return True

    def deliver(self, item: FeedItem, title: str) -> bool:
        return self.notifier.notify_new_item(
            title=title,
            link=item.link,
            source=item.source,
            source_type=item.source_type,
        )


class NotionSink:
    name = SINK_NOTION
    label = "Notion"

    def __init__(self, sync: NotionSync, excluded_groups: Optional[Iterable[str]] = None):
        self.sync = sync
        self.excluded_groups: Set[str] = set(excluded_groups or ())

    def accepts(self, group_id: str) -> bool:
        """排除的來源不進資料庫，也不會留下投遞記錄。"""
        return group_id not in self.excluded_groups

    def deliver(self, item: FeedItem, title: str) -> bool:
        # 翻譯後的標題只當顯示標題；item 保持原文，「原始標題」欄位靠它
        return self.sync.add_item(item, display_title=title)


def build_sinks(notifier: TelegramNotifier, notion: NotionSync) -> List:
    """只回傳已完成設定的目的地。

    未設定的目的地直接排除，而不是每則內容都失敗一次 —— 否則失敗計數
    會被未啟用的功能灌爆，也看不出真正的問題。
    """
    sinks = []

    if notifier.is_configured():
        sinks.append(TelegramSink(notifier))
    else:
        print("[Warning] Telegram 未設定，略過 Telegram 通知")

    if notion.is_configured():
        sinks.append(NotionSink(notion, NOTION_EXCLUDED_GROUPS))
        if NOTION_EXCLUDED_GROUPS:
            excluded = "、".join(sorted(NOTION_EXCLUDED_GROUPS))
            print(f"[Info] 以下來源不同步到 Notion（仍會發 Telegram）：{excluded}")
    else:
        print("[Info] Notion 未設定，略過 Notion 同步（設定 NOTION_TOKEN 與 NOTION_DATABASE_ID 即可啟用）")

    return sinks
