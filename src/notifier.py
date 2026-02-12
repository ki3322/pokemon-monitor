import requests
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REQUEST_TIMEOUT


class TelegramNotifier:
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.is_configured():
            print("[Warning] Telegram not configured, skipping notification")
            return False

        try:
            response = requests.post(
                f"{self.api_base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": False,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"[Error] Failed to send Telegram message: {e}")
            return False

    def notify_new_item(
        self,
        title: str,
        link: str,
        source: str,
        source_type: str = "website"
    ) -> bool:
        if source_type == "twitter":
            emoji = "🐦"
            type_label = "推文"
        else:
            emoji = "📰"
            type_label = "文章"

        message = (
            f"{emoji} <b>新{type_label}</b>\n\n"
            f"📌 <b>{self._escape_html(source)}</b>\n"
            f"{self._escape_html(title)}\n\n"
            f"🔗 {link}"
        )

        return self.send_message(message)

    def notify_batch(self, items: list) -> int:
        success_count = 0
        for item in items:
            if self.notify_new_item(
                title=item.title,
                link=item.link,
                source=item.source,
                source_type=getattr(item, "source_type", "website"),
            ):
                success_count += 1
        return success_count

    @staticmethod
    def _escape_html(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
