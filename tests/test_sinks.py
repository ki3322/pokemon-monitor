from src.sinks import NotionSink, TelegramSink, build_sinks
from src.state import SINK_NOTION, SINK_TELEGRAM
from tests.conftest import FakeNotifier, make_item


class FakeSync:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def is_configured(self):
        return True

    def add_item(self, item, display_title=""):
        self.calls.append({"item": item, "display_title": display_title})
        return self.ok


class TestTelegramSink:
    def test_delivers_with_translated_title(self):
        notifier = FakeNotifier()
        item = make_item("1", title="Original")

        assert TelegramSink(notifier).deliver(item, "翻譯後標題") is True
        assert notifier.sent[0]["title"] == "翻譯後標題"


class TestNotionSink:
    def test_keeps_original_title_on_the_item(self):
        """回歸測試：翻譯後的標題只能當顯示標題，
        item 本身要原封不動傳下去——「原始標題」欄位靠它。"""
        sync = FakeSync()
        item = make_item("1", title="Original")

        assert NotionSink(sync).deliver(item, "翻譯後標題") is True

        call = sync.calls[0]
        assert call["item"] is item
        assert call["item"].title == "Original"
        assert call["display_title"] == "翻譯後標題"

    def test_reports_failure(self):
        assert NotionSink(FakeSync(ok=False)).deliver(make_item("1"), "t") is False


class TestBuildSinks:
    def test_includes_only_configured_sinks(self):
        class Unconfigured:
            def is_configured(self):
                return False

        sinks = build_sinks(FakeNotifier(), Unconfigured())

        assert [s.name for s in sinks] == [SINK_TELEGRAM]

    def test_includes_notion_when_configured(self):
        sinks = build_sinks(FakeNotifier(), FakeSync())
        assert [s.name for s in sinks] == [SINK_TELEGRAM, SINK_NOTION]
