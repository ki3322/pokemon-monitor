"""main.py 中三個監控迴圈、投遞目的地組裝與警告冷卻的行為。"""
import pytest

from src import main as main_module
from src.main import (
    MonitorRun,
    alert_scrape_failures,
    alert_twitter_failures,
    monitor_rss,
    monitor_scrapers,
    monitor_twitter,
)
from src.sinks import build_sinks
from src.state import SINK_NOTION, SINK_TELEGRAM, StateManager
from tests.conftest import FakeNotifier, FakeSink, make_item


@pytest.fixture(autouse=True)
def no_translation(monkeypatch):
    monkeypatch.setattr("src.main.translate_title", lambda text: text)


@pytest.fixture
def sink():
    return FakeSink(SINK_TELEGRAM, "Telegram")


@pytest.fixture
def run(state_file, notifier, sink):
    return MonitorRun(StateManager(state_file), notifier, [sink])


class TestMonitorRss:
    def test_connection_failure_does_not_initialize_source(self, run, monkeypatch, capsys):
        """抓取失敗時不可以建立記錄，否則下一輪會把整頁當成新內容發出去。"""
        monkeypatch.setattr("src.main.RSS_SOURCES", [{"name": "S", "url": "https://x"}])
        monkeypatch.setattr(main_module, "get_rss_items", lambda source: ([], False))

        monitor_rss(run)

        assert "連接失敗" in capsys.readouterr().out
        assert not run.state.is_initialized(SINK_TELEGRAM, "S")

    def test_uses_group_for_dedupe(self, run, monkeypatch):
        source = {"name": "顯示名稱", "url": "https://x", "group": "共用群組"}
        monkeypatch.setattr("src.main.RSS_SOURCES", [source])
        monkeypatch.setattr(main_module, "get_rss_items", lambda s: ([make_item("1")], True))

        monitor_rss(run)

        assert run.state.is_initialized(SINK_TELEGRAM, "共用群組")
        assert not run.state.is_initialized(SINK_TELEGRAM, "顯示名稱")

    def test_respects_translate_flag(self, run, monkeypatch, sink):
        run.state.mark_all_delivered(SINK_TELEGRAM, "S", [])
        monkeypatch.setattr("src.main.translate_title", lambda text: "翻譯過")
        monkeypatch.setattr(
            "src.main.RSS_SOURCES", [{"name": "S", "url": "https://x", "translate": False}]
        )
        monkeypatch.setattr(
            main_module, "get_rss_items", lambda s: ([make_item("1", title="原文")], True)
        )

        monitor_rss(run)

        assert sink.delivered[0]["title"] == "原文"


class TestMonitorScrapers:
    def test_returns_failed_source_names(self, run, monkeypatch):
        monkeypatch.setattr(
            "src.main.SCRAPE_SOURCES",
            [{"name": "壞掉的來源", "url": "https://x"}, {"name": "正常來源", "url": "https://y"}],
        )
        results = iter([([], False), ([make_item("1")], True)])
        monkeypatch.setattr(main_module, "get_scraped_items", lambda s: next(results))

        assert monitor_scrapers(run) == ["壞掉的來源"]

    def test_no_failures_when_all_succeed(self, run, monkeypatch):
        monkeypatch.setattr("src.main.SCRAPE_SOURCES", [{"name": "A", "url": "https://x"}])
        monkeypatch.setattr(main_module, "get_scraped_items", lambda s: ([], True))

        assert monitor_scrapers(run) == []


class TestMonitorTwitter:
    def test_returns_failed_usernames(self, run, monkeypatch):
        monkeypatch.setattr("src.main.TWITTER_ACCOUNTS", ["good", "bad"])
        results = {"good": ([make_item("1")], True), "bad": ([], False)}
        monkeypatch.setattr(main_module, "get_twitter_items", lambda u: results[u])

        assert monitor_twitter(run) == ["bad"]

    def test_each_account_gets_its_own_group(self, run, monkeypatch):
        monkeypatch.setattr("src.main.TWITTER_ACCOUNTS", ["alice"])
        monkeypatch.setattr(main_module, "get_twitter_items", lambda u: ([make_item("1")], True))

        monitor_twitter(run)

        assert run.state.is_initialized(SINK_TELEGRAM, "twitter_alice")


class TestBuildSinks:
    def test_only_configured_sinks_included(self):
        notion = type("N", (), {"is_configured": lambda self: False})()
        sinks = build_sinks(FakeNotifier(), notion)

        assert [s.name for s in sinks] == [SINK_TELEGRAM]

    def test_notion_included_when_configured(self):
        notion = type("N", (), {"is_configured": lambda self: True})()
        sinks = build_sinks(FakeNotifier(), notion)

        assert [s.name for s in sinks] == [SINK_TELEGRAM, SINK_NOTION]

    def test_no_sinks_when_nothing_configured(self):
        notifier = FakeNotifier()
        notifier.is_configured = lambda: False
        notion = type("N", (), {"is_configured": lambda self: False})()

        assert build_sinks(notifier, notion) == []


class TestTwitterAlert:
    def test_no_alert_below_threshold(self, run, monkeypatch):
        monkeypatch.setattr("src.main.TWITTER_ACCOUNTS", ["a", "b", "c", "d", "e", "f", "g"])

        alert_twitter_failures(run, ["a"])

        assert run.notifier.messages == []

    def test_alert_sent_at_threshold(self, run, monkeypatch):
        monkeypatch.setattr("src.main.TWITTER_ACCOUNTS", ["a", "b", "c", "d", "e", "f", "g"])

        alert_twitter_failures(run, ["a", "b", "c"])

        assert len(run.notifier.messages) == 1
        assert "Twitter 監控警告" in run.notifier.messages[0]

    def test_alert_suppressed_within_cooldown(self, run, monkeypatch, capsys):
        """回歸測試：Cookie 過期時舊版每 30 分鐘轟炸一次，一天 48 則。"""
        monkeypatch.setattr("src.main.TWITTER_ACCOUNTS", ["a", "b", "c", "d", "e", "f", "g"])
        failures = ["a", "b", "c"]

        alert_twitter_failures(run, failures)
        alert_twitter_failures(run, failures)

        assert len(run.notifier.messages) == 1
        assert "冷卻中" in capsys.readouterr().out

    def test_cooldown_not_recorded_when_send_fails(self, state_file, monkeypatch, sink):
        """發送失敗時不記錄冷卻，否則警告會被靜音 12 小時。"""
        monkeypatch.setattr("src.main.TWITTER_ACCOUNTS", ["a", "b", "c", "d", "e", "f", "g"])
        notifier = FakeNotifier()
        notifier.send_message = lambda text, parse_mode="HTML": False
        run = MonitorRun(StateManager(state_file), notifier, [sink])

        alert_twitter_failures(run, ["a", "b", "c"])

        assert run.state.should_alert("twitter_failure", 12)


class TestScrapeAlert:
    def test_alert_on_widespread_scrape_failure(self, run, monkeypatch):
        """網頁來源大量失敗多半代表改版，必須主動通知而不是無聲失效。"""
        monkeypatch.setattr(
            "src.main.SCRAPE_SOURCES", [{"name": n, "url": "https://x"} for n in "abcd"]
        )

        alert_scrape_failures(run, ["a", "b"])

        assert "網頁監控警告" in run.notifier.messages[0]

    def test_no_alert_for_single_failure(self, run, monkeypatch):
        monkeypatch.setattr(
            "src.main.SCRAPE_SOURCES", [{"name": n, "url": "https://x"} for n in "abcd"]
        )

        alert_scrape_failures(run, ["a"])

        assert run.notifier.messages == []
