import pytest

from src.models import FeedItem
from src.state import SINK_NOTION, SINK_TELEGRAM


class FakeNotifier:
    """記錄所有通知的假 notifier，可指定哪幾次要失敗。"""

    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.sent = []
        self.messages = []
        self.calls = 0

    def is_configured(self):
        return True

    def notify_new_item(self, title, link, source, source_type="website"):
        self.calls += 1
        if self.calls in self.fail_on:
            return False
        self.sent.append({"title": title, "link": link, "source": source, "source_type": source_type})
        return True

    def send_message(self, text, parse_mode="HTML"):
        self.messages.append(text)
        return True


class FakeSink:
    """通用的假投遞目的地。"""

    def __init__(self, name=SINK_TELEGRAM, label="Telegram", fail_on=()):
        self.name = name
        self.label = label
        self.fail_on = set(fail_on)
        self.delivered = []
        self.calls = 0

    def deliver(self, item, title):
        self.calls += 1
        if self.calls in self.fail_on:
            return False
        self.delivered.append({"item": item, "title": title})
        return True


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def telegram_sink():
    return FakeSink(SINK_TELEGRAM, "Telegram")


@pytest.fixture
def notion_sink():
    return FakeSink(SINK_NOTION, "Notion")


@pytest.fixture
def state_file(tmp_path):
    return str(tmp_path / "state.json")


def make_item(item_id, title="標題", link=None, source="來源", source_type="website"):
    return FeedItem(
        id=item_id,
        title=title,
        link=link if link is not None else f"https://example.com/{item_id}",
        source=source,
        source_type=source_type,
    )
