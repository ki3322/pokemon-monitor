import pytest

from src.main import MonitorRun, Totals, finish, validate_config
from src.state import SINK_NOTION, SINK_TELEGRAM, StateManager
from tests.conftest import FakeSink, make_item


@pytest.fixture(autouse=True)
def no_translation(monkeypatch):
    """測試不打外部翻譯服務。"""
    monkeypatch.setattr("src.main.translate", lambda text: text)


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
            "src.main.translate", lambda text: calls.append(text) or f"譯:{text}"
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


class TestDeadSinks:
    """某個目的地整輪全數失敗（例如 Telegram token 失效）必須讓排程變紅。

    回歸測試：token 被撤銷那天 Telegram 0 則、Notion 2 則，
    合併計數看起來只是部分失敗，GitHub Actions 照樣顯示成功。
    """

    ALWAYS_FAIL = range(1, 100)

    def test_sink_that_failed_every_delivery_is_dead(self, state, notion_sink):
        telegram = FakeSink(SINK_TELEGRAM, "Telegram", fail_on=self.ALWAYS_FAIL)
        initialized(state, "A", telegram, notion_sink)
        run = MonitorRun(state, None, [telegram, notion_sink])

        run.process("A", [make_item("1"), make_item("2")])

        assert run.dead_sinks() == ("Telegram",)

    def test_partial_failure_is_not_dead(self, state):
        sink = FakeSink(fail_on=[1])
        initialized(state, "A", sink)
        run = MonitorRun(state, None, [sink])

        run.process("A", [make_item("1"), make_item("2")])

        assert run.dead_sinks() == ()

    def test_sink_with_nothing_to_deliver_is_not_dead(self, state, telegram_sink):
        initialized(state, "A", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])

        run.process("A", [])

        assert run.dead_sinks() == ()

    def test_finish_fails_the_run_when_a_sink_is_dead(self, state, notion_sink, capsys):
        telegram = FakeSink(SINK_TELEGRAM, "Telegram", fail_on=self.ALWAYS_FAIL)
        initialized(state, "A", telegram, notion_sink)
        run = MonitorRun(state, None, [telegram, notion_sink])
        run.process("A", [make_item("1")])

        assert finish(run) == 1
        assert "Telegram" in capsys.readouterr().out

    def test_finish_succeeds_on_a_normal_run(self, state, telegram_sink):
        initialized(state, "A", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])
        run.process("A", [make_item("1")])

        assert finish(run) == 0


class TestTranslationOutage:
    """整輪標題全部翻譯失敗必須讓排程變紅。

    回歸測試：Google 擋了 GitHub Actions 的 IP，11/10 起每則都以原文送出，
    但失敗只印成警告，排程照樣綠燈，一週後才被發現。
    """

    @pytest.fixture
    def failing_translation(self, monkeypatch):
        monkeypatch.setattr("src.main.translate", lambda text: None)

    def test_failed_translation_still_delivers_the_original(self, state, telegram_sink, failing_translation):
        initialized(state, "A", telegram_sink)

        MonitorRun(state, None, [telegram_sink]).process("A", [make_item("1", title="Original")])

        assert telegram_sink.delivered[0]["title"] == "Original"

    def test_every_translation_failing_is_an_outage(self, state, telegram_sink, failing_translation):
        initialized(state, "A", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])

        run.process("A", [make_item("1"), make_item("2")])

        assert run.translation_down()

    def test_one_success_is_not_an_outage(self, state, telegram_sink, monkeypatch):
        """部分失敗通常是單則標題的問題，不代表服務掛了。"""
        results = iter([None, "譯文", None])
        monkeypatch.setattr("src.main.translate", lambda text: next(results))
        initialized(state, "A", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])

        run.process("A", [make_item("1"), make_item("2"), make_item("3")])

        assert not run.translation_down()

    def test_a_single_failure_is_too_little_to_call(self, state, telegram_sink, failing_translation):
        """只有一則可能只是瞬斷；全部落空且至少兩則才算服務失效。"""
        initialized(state, "A", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])

        run.process("A", [make_item("1")])

        assert not run.translation_down()

    def test_sources_without_translation_do_not_count(self, state, telegram_sink, failing_translation):
        initialized(state, "A", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])

        run.process("A", [make_item("1"), make_item("2")], translate=False)

        assert not run.translation_down()

    def test_failures_add_up_across_sources(self, state, telegram_sink, failing_translation):
        initialized(state, "A", telegram_sink)
        initialized(state, "B", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])

        run.process("A", [make_item("1")])
        run.process("B", [make_item("2")])

        assert run.translation_down()

    def test_finish_fails_the_run_on_an_outage(self, state, telegram_sink, failing_translation, capsys):
        initialized(state, "A", telegram_sink)
        run = MonitorRun(state, None, [telegram_sink])
        run.process("A", [make_item("1"), make_item("2")])

        assert finish(run) == 1
        out = capsys.readouterr().out
        assert "翻譯" in out and "MYMEMORY_EMAIL" in out

    def test_finish_reports_both_problems(self, state, notion_sink, failing_translation, capsys):
        telegram = FakeSink(SINK_TELEGRAM, "Telegram", fail_on=range(1, 100))
        initialized(state, "A", telegram, notion_sink)
        run = MonitorRun(state, None, [telegram, notion_sink])
        run.process("A", [make_item("1"), make_item("2")])

        assert finish(run) == 1
        out = capsys.readouterr().out
        assert "Telegram" in out and "翻譯" in out


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
        monkeypatch.setattr("src.main.translate", lambda text: "不該被呼叫")

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

    def test_unknown_notion_exclusion_raises(self, monkeypatch):
        """排除設定打錯字必須立刻報錯：靜默失效的話，
        使用者會以為某來源不進 Notion，其實它一直在進。"""
        monkeypatch.setattr("src.main.NOTION_EXCLUDED_GROUPS", {"twitter_Typo"})
        with pytest.raises(ValueError, match="NOTION_EXCLUDED_GROUPS"):
            validate_config()

    def test_valid_notion_exclusion_passes(self, monkeypatch):
        monkeypatch.setattr("src.main.TWITTER_ACCOUNTS", ["UniteVids"])
        monkeypatch.setattr("src.main.NOTION_EXCLUDED_GROUPS", {"twitter_UniteVids"})
        validate_config()

    def test_website_group_exclusion_passes(self, monkeypatch):
        """網站來源用 name（或 group）當群組 ID，也要能排除。"""
        monkeypatch.setattr("src.main.RSS_SOURCES", [{"name": "GO Hub", "url": "https://x"}])
        monkeypatch.setattr("src.main.SCRAPE_SOURCES", [])
        monkeypatch.setattr("src.main.NOTION_EXCLUDED_GROUPS", {"GO Hub"})
        validate_config()
