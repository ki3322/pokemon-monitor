import pytest

from src.main import MonitorRun, Totals, validate_config
from src.state import SINK_NOTION, SINK_TELEGRAM, StateManager
from tests.conftest import FakeSink, make_item


@pytest.fixture(autouse=True)
def no_translation(monkeypatch):
    """測試不打外部翻譯服務。"""
    monkeypatch.setattr("src.main.translate_title", lambda text: text)


@pytest.fixture
def state(state_file):
    return StateManager(state_file)


def initialized(state, group, *sinks):
    """讓群組跳過初始化階段，模擬已經跑過至少一輪。"""
    for sink in sinks:
        state.mark_all_delivered(sink.name, group, [])
    return state


class TestBootstrap:
    def test_first_run_records_without_delivering(self, state, telegram_sink):
        """新來源第一輪只記錄現況，否則整頁內容會一次湧出。"""
        run = MonitorRun(state, None, [telegram_sink])

        run.process("A", [make_item("1"), make_item("2")])

        assert telegram_sink.delivered == []
        assert state.is_delivered(SINK_TELEGRAM, "A", "1")

    def test_second_run_delivers_new_items(self, state, telegram_sink):
        MonitorRun(state, None, [telegram_sink]).process("A", [make_item("1")])

        MonitorRun(state, None, [telegram_sink]).process("A", [make_item("1"), make_item("2")])

        assert len(telegram_sink.delivered) == 1
        assert telegram_sink.delivered[0]["item"].id == "2"

    def test_empty_first_fetch_still_marks_initialized(self, state, telegram_sink):
        MonitorRun(state, None, [telegram_sink]).process("A", [])
        assert state.is_initialized(SINK_TELEGRAM, "A")

    def test_new_sink_bootstraps_independently(self, state, telegram_sink, notion_sink):
        """回歸測試：後來才啟用 Notion，不該回頭補送所有舊項目。"""
        MonitorRun(state, None, [telegram_sink]).process("A", [make_item("1")])
        MonitorRun(state, None, [telegram_sink]).process("A", [make_item("1"), make_item("2")])

        # Notion 首次啟用
        MonitorRun(state, None, [telegram_sink, notion_sink]).process(
            "A", [make_item("1"), make_item("2")]
        )

        assert notion_sink.delivered == []
        assert state.is_delivered(SINK_NOTION, "A", "1")


class TestMultipleSinks:
    def test_item_goes_to_every_sink(self, state, telegram_sink, notion_sink):
        initialized(state, "A", telegram_sink, notion_sink)
        run = MonitorRun(state, None, [telegram_sink, notion_sink])

        run.process("A", [make_item("1")])

        assert len(telegram_sink.delivered) == 1
        assert len(notion_sink.delivered) == 1

    def test_failure_in_one_sink_does_not_block_the_other(self, state, notion_sink):
        """回歸測試：Notion 掛掉不該讓 Telegram 通知重複發送。"""
        failing = FakeSink(SINK_TELEGRAM, "Telegram", fail_on=[1])
        initialized(state, "A", failing, notion_sink)
        run = MonitorRun(state, None, [failing, notion_sink])

        run.process("A", [make_item("1")])

        assert not state.is_delivered(SINK_TELEGRAM, "A", "1")
        assert state.is_delivered(SINK_NOTION, "A", "1")

    def test_failed_sink_retries_without_resending_the_other(self, state):
        telegram = FakeSink(SINK_TELEGRAM, "Telegram")
        notion = FakeSink(SINK_NOTION, "Notion", fail_on=[1])
        initialized(state, "A", telegram, notion)

        MonitorRun(state, None, [telegram, notion]).process("A", [make_item("1")])
        MonitorRun(state, None, [telegram, notion]).process("A", [make_item("1")])

        assert len(telegram.delivered) == 1  # 沒有重複發送
        assert len(notion.delivered) == 1    # 重試成功

    def test_translation_runs_once_for_all_sinks(self, state, monkeypatch, telegram_sink, notion_sink):
        calls = []
        monkeypatch.setattr(
            "src.main.translate_title", lambda text: calls.append(text) or f"譯:{text}"
        )
        initialized(state, "A", telegram_sink, notion_sink)

        MonitorRun(state, None, [telegram_sink, notion_sink]).process(
            "A", [make_item("1", title="Title")]
        )

        assert calls == ["Title"]
        assert telegram_sink.delivered[0]["title"] == "譯:Title"
        assert notion_sink.delivered[0]["title"] == "譯:Title"

    def test_no_sinks_reports_clearly(self, state):
        assert MonitorRun(state, None, []).process("A", [make_item("1")]) == "(無可用的投遞目的地)"


class TestDeliveryFailureHandling:
    def test_failed_item_is_not_marked_delivered(self, state):
        """回歸測試：舊版在送出前就標記已讀，失敗的通知永久消失。"""
        sink = FakeSink(fail_on=[1])
        initialized(state, "A", sink)
        run = MonitorRun(state, None, [sink])

        run.process("A", [make_item("1")])

        assert not state.is_delivered(SINK_TELEGRAM, "A", "1")
        assert run.totals.failed == 1

    def test_failed_item_is_retried_next_run(self, state):
        failing = FakeSink(fail_on=[1])
        initialized(state, "A", failing)
        MonitorRun(state, None, [failing]).process("A", [make_item("1")])

        retry = FakeSink()
        MonitorRun(state, None, [retry]).process("A", [make_item("1")])

        assert len(retry.delivered) == 1
        assert state.is_delivered(SINK_TELEGRAM, "A", "1")

    def test_successful_items_marked_even_when_others_fail(self, state):
        sink = FakeSink(fail_on=[1])
        initialized(state, "A", sink)
        run = MonitorRun(state, None, [sink])

        run.process("A", [make_item("1"), make_item("2")])

        assert not state.is_delivered(SINK_TELEGRAM, "A", "1")
        assert state.is_delivered(SINK_TELEGRAM, "A", "2")
        assert run.totals == Totals(sent=1, failed=1)


class TestGroupedSources:
    def test_shared_group_delivers_duplicate_article_once(self, state, telegram_sink):
        """回歸測試：兩個玩具人標籤頁重疊約 29%，共用 group 才不會重複發送。"""
        initialized(state, "玩具人", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])

        run.process("玩具人", [make_item("dup", source="玩具人 寶可夢")])
        run.process("玩具人", [make_item("dup", source="玩具人 寶可夢中心")])

        assert len(telegram_sink.delivered) == 1

    def test_bootstrap_covers_all_sources_in_group(self, state, telegram_sink):
        """同群組的第二個來源在同一輪也要走初始化，不能立刻發通知。"""
        run = MonitorRun(state, None, [telegram_sink])

        run.process("玩具人", [make_item("a")])
        run.process("玩具人", [make_item("b")])

        assert telegram_sink.delivered == []
        assert state.is_delivered(SINK_TELEGRAM, "玩具人", "b")


class TestTranslationToggle:
    def test_translation_skipped_when_disabled(self, state, monkeypatch, telegram_sink):
        initialized(state, "A", telegram_sink)
        monkeypatch.setattr("src.main.translate_title", lambda text: "不該被呼叫")

        MonitorRun(state, None, [telegram_sink]).process(
            "A", [make_item("1", title="繁中標題")], translate=False
        )

        assert telegram_sink.delivered[0]["title"] == "繁中標題"


class TestValidateConfig:
    def test_current_config_is_valid(self):
        validate_config()

    def test_unhandled_source_raises(self, monkeypatch):
        monkeypatch.setattr(
            "src.main.SCRAPE_SOURCES", [{"name": "X", "url": "https://unknown.example/"}]
        )
        with pytest.raises(ValueError, match="沒有對應的爬蟲"):
            validate_config()
