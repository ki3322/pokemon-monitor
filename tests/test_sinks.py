import pytest

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


class TestSinkAccepts:
    def test_telegram_accepts_every_group(self):
        """排除設定只針對 Notion：Telegram 仍要收到所有來源。"""
        sink = TelegramSink(FakeNotifier())
        assert sink.accepts("twitter_UniteVids") is True
        assert sink.accepts("Serebii.net") is True

    def test_notion_rejects_excluded_group(self):
        sink = NotionSink(FakeSync(), excluded_groups={"twitter_UniteVids"})
        assert sink.accepts("twitter_UniteVids") is False

    def test_notion_accepts_other_groups(self):
        sink = NotionSink(FakeSync(), excluded_groups={"twitter_UniteVids"})
        assert sink.accepts("twitter_PokemonGoApp") is True
        assert sink.accepts("Serebii.net") is True

    def test_no_exclusions_accepts_everything(self):
        assert NotionSink(FakeSync()).accepts("twitter_UniteVids") is True


class TestBuildSinks:
    def test_notion_sink_gets_configured_exclusions(self, monkeypatch):
        monkeypatch.setattr("src.sinks.NOTION_EXCLUDED_GROUPS", {"twitter_UniteVids"})
        sinks = build_sinks(FakeNotifier(), FakeSync())

        notion = next(s for s in sinks if s.name == SINK_NOTION)
        assert notion.accepts("twitter_UniteVids") is False

    def test_includes_only_configured_sinks(self):
        class Unconfigured:
            def is_configured(self):
                return False

        sinks = build_sinks(FakeNotifier(), Unconfigured())

        assert [s.name for s in sinks] == [SINK_TELEGRAM]

    def test_includes_notion_when_configured(self):
        sinks = build_sinks(FakeNotifier(), FakeSync())
        assert [s.name for s in sinks] == [SINK_TELEGRAM, SINK_NOTION]
