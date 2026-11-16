"""Telegram 通知。"""
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests

from config import (
    LOCAL_UTC_OFFSET_HOURS,
    QUIET_HOURS_END,
    QUIET_HOURS_START,
    REQUEST_TIMEOUT,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

LOCAL_TZ = timezone(timedelta(hours=LOCAL_UTC_OFFSET_HOURS))


def is_quiet_hours(now: datetime) -> bool:
    """台北時間是否落在靜音時段。"""
    return QUIET_HOURS_START <= now.astimezone(LOCAL_TZ).hour < QUIET_HOURS_END


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramNotifier:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.clock = clock
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """送出訊息，成功回傳 True。

        呼叫端「必須」檢查回傳值：只有成功送出的項目才可以標記為已讀，
        否則失敗的通知會永久遺失。
        """
        if not self.is_configured():
            print("    [Warning] Telegram 未設定，略過通知")
            return False

        try:
            response = requests.post(
                f"{self.api_base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": False,
                    # 深夜不響鈴，但照常送達：延到早上再送會讓新聞晚好幾個小時
                    "disable_notification": is_quiet_hours(self.clock()),
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as error:
            detail = ""
            response = getattr(error, "response", None)
            if response is not None:
                detail = f" (HTTP {response.status_code}: {response.text[:200]})"
            # requests 的例外字串含請求 URL（也就是 bot token），必須遮蔽才能進 log
            message = str(error).replace(self.bot_token, "***") if self.bot_token else str(error)
            print(f"    [Error] Telegram 發送失敗: {message}{detail}")
            return False

    def notify_new_item(
        self,
        title: str,
        link: str,
        source: str,
        source_type: str = "website",
    ) -> bool:
        if source_type == "twitter":
            emoji, type_label = "🐦", "推文"
        else:
            emoji, type_label = "📰", "文章"

        # parse_mode=HTML 之下每個插入的欄位都要跳脫，連結也不例外：
        # 未跳脫的字元會讓 Telegram 回 400，該則通知就此消失。
        message = (
            f"{emoji} <b>新{type_label}</b>\n\n"
            f"📌 <b>{self._escape_html(source)}</b>\n"
            f"{self._escape_html(title)}\n\n"
            f"🔗 {self._escape_html(link)}"
        )

        return self.send_message(message)

    @staticmethod
    def _escape_html(text: str) -> str:
        # & 必須先換，否則會把後面產生的 &lt; 再次跳脫
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
