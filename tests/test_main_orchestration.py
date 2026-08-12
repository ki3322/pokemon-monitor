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


class TestSinkExclusion:
    """來源可以只排除某個目的地（例如 @UniteVids 不進 Notion）。"""

    def _sinks(self):
        return (
            FakeSink(SINK_TELEGRAM, "Telegram"),
            FakeSink(SINK_NOTION, "Notion", excluded_groups={"twitter_UniteVids"}),
        )

    def _two_rounds(self, state_file, notifier, group_id, first, second):
        """跑兩輪：第一輪初始化，第二輪才會真的投遞。

        每輪要新的 MonitorRun —— bootstrapped 是「本輪」的記錄，
        同一個 run 內重複呼叫同群組會一直走初始化流程。
        """
        telegram, notion = self._sinks()
        state = StateManager(state_file)

        MonitorRun(state, notifier, [telegram, notion]).process(group_id, first)
        note = MonitorRun(state, notifier, [telegram, notion]).process(group_id, second)

        return telegram, notion, state, note

    def test_excluded_group_skips_that_sink_only(self, state_file, notifier):
        items = [make_item("a"), make_item("b")]
        telegram, notion, _, _ = self._two_rounds(
            state_file, notifier, "twitter_UniteVids", items, items + [make_item("c")]
        )

        assert [d["item"].id for d in telegram.delivered] == ["c"]
        assert notion.delivered == []

    def test_excluded_group_leaves_no_notion_state(self, state_file, notifier):
        """排除的來源不該在 Notion 留下投遞記錄——之後取消排除時，
        它要能像新來源一樣先初始化，而不是把整頁舊內容當成新的湧出。"""
        telegram, notion = self._sinks()
        state = StateManager(state_file)
        MonitorRun(state, notifier, [telegram, notion]).process(
            "twitter_UniteVids", [make_item("a")]
        )

        assert state.is_initialized(SINK_TELEGRAM, "twitter_UniteVids") is True
        assert state.is_initialized(SINK_NOTION, "twitter_UniteVids") is False

    def test_other_groups_still_reach_both_sinks(self, state_file, notifier):
        telegram, notion, _, _ = self._two_rounds(
            state_file,
            notifier,
            "twitter_PokemonGoApp",
            [make_item("a")],
            [make_item("a"), make_item("b")],
        )

        assert [d["item"].id for d in telegram.delivered] == ["b"]
        assert [d["item"].id for d in notion.delivered] == ["b"]

    def test_note_mentions_only_the_accepting_sink(self, state_file, notifier):
        telegram, notion = self._sinks()
        note = MonitorRun(StateManager(state_file), notifier, [telegram, notion]).process(
            "twitter_UniteVids", [make_item("a")]
        )

        assert "Telegram" in note
        assert "Notion" not in note

    def test_all_sinks_excluded_reports_clearly(self, state_file, notifier):
        """全部目的地都排除時要說清楚，不能跟「沒有設定任何目的地」混淆。"""
        notion = FakeSink(SINK_NOTION, "Notion", excluded_groups={"g"})
        note = MonitorRun(StateManager(state_file), notifier, [notion]).process("g", [make_item("a")])

        assert note == "(此來源不投遞到任何目的地)"
