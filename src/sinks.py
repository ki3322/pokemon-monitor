"""投遞目的地。

每個目的地把「送出一則內容」包成統一介面，主流程就不必知道
Telegram 與 Notion 的差異，也能各自獨立記錄成功與失敗。
"""
from typing import List

from src.models import FeedItem
from src.notifier import TelegramNotifier
from src.notion.sync import NotionSync
from src.state import SINK_NOTION, SINK_TELEGRAM


class TelegramSink:
    name = SINK_TELEGRAM
    label = "Telegram"

    def __init__(self, notifier: TelegramNotifier):
        self.notifier = notifier

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

    def __init__(self, sync: NotionSync):
        self.sync = sync

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
        sinks.append(NotionSink(notion))
    else:
        print("[Info] Notion 未設定，略過 Notion 同步（設定 NOTION_TOKEN 與 NOTION_DATABASE_ID 即可啟用）")

    return sinks
