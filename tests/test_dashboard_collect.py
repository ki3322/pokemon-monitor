import json
import os

from src.dashboard.collect import NEWS_LIMIT, build_dashboard, list_drafts, read_state
from src.notion.reader import SelectedItem
from src.state import STATE_VERSION


class FakeNewsReader:
    """假的 NotionReader，避免測試打真的 Notion API。"""

    def __init__(self, items=(), configured=True, fails=False):
        self.items = list(items)
        self.configured = configured
        self.fails = fails
        self.requested_limit = None

    def is_configured(self):
        return self.configured

    def recent_items(self, limit):
        self.requested_limit = limit
        return None if self.fails else self.items


def _news_item(title="標題"):
    return SelectedItem(
        page_id="p",
        title=title,
        link="https://a.example/1",
        source="Serebii.net",
        category="文章",
        status="待處理",
        selected=True,
        found_at="2026-08-10T02:00:00",
    )


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(payload, str):
            f.write(payload)
        else:
            json.dump(payload, f, ensure_ascii=False)


class TestReadState:
    def test_missing_file_is_empty(self, tmp_path):
        assert read_state(str(tmp_path / "nope.json")) == (None, {})

    def test_current_version_returns_records(self, tmp_path):
        path = str(tmp_path / "state.json")
        _write(path, {"version": STATE_VERSION, "delivered": {"telegram": {"g": ["a"]}}})
        version, delivered = read_state(path)
        assert version == STATE_VERSION
        assert delivered == {"telegram": {"g": ["a"]}}

    def test_legacy_version_reports_version_but_no_records(self, tmp_path):
        """回歸測試：StateManager 會捨棄舊版記錄，儀表板不該顯示不會被採用的數字。"""
        path = str(tmp_path / "state.json")
        _write(path, {"seen_items": {"Serebii.net": ["a", "b", "c"]}})
        assert read_state(path) == (None, {})

    def test_corrupt_json_does_not_raise(self, tmp_path):
        path = str(tmp_path / "state.json")
        _write(path, "{not json")
        assert read_state(path) == (None, {})

    def test_non_object_json_rejected(self, tmp_path):
        path = str(tmp_path / "state.json")
        _write(path, [1, 2, 3])
        assert read_state(path) == (None, {})


class TestListDrafts:
    def test_missing_directory_is_empty(self, tmp_path):
        assert list_drafts(str(tmp_path / "nope")) == []

    def test_returns_sorted_names(self, tmp_path):
        for name in ("b.brief.md", "a.brief.md"):
            _write(str(tmp_path / name), "x")
        assert list_drafts(str(tmp_path)) == ["a.brief.md", "b.brief.md"]

    def test_unreadable_directory_does_not_raise(self, tmp_path, monkeypatch):
        """儀表板只是唯讀的檢視工具，讀不到目錄就顯示空的，不該讓指令失敗。"""

        def deny(_path):
            raise PermissionError("denied")

        monkeypatch.setattr(os, "listdir", deny)
        assert list_drafts(str(tmp_path)) == []


class TestBuildDashboard:
    def test_uses_real_config_sources(self, tmp_path):
        from config import RSS_SOURCES, SCRAPE_SOURCES, TWITTER_ACCOUNTS

        dashboard = build_dashboard(
            state_file=str(tmp_path / "state.json"), drafts_dir=str(tmp_path)
        )
        # 共用 group 的來源會合併，所以群組數不大於來源數
        assert 0 < len(dashboard.groups) <= len(RSS_SOURCES) + len(SCRAPE_SOURCES) + len(
            TWITTER_ACCOUNTS
        )

    def test_survives_missing_state_and_drafts(self, tmp_path):
        dashboard = build_dashboard(
            state_file=str(tmp_path / "nope.json"), drafts_dir=str(tmp_path / "nope")
        )
        assert dashboard.total_tracked == 0
        assert dashboard.drafts == ()

    def test_generated_at_is_formatted(self, tmp_path):
        from datetime import datetime

        dashboard = build_dashboard(
            state_file=str(tmp_path / "s.json"),
            drafts_dir=str(tmp_path),
            now=datetime(2026, 8, 10, 9, 5),
        )
        assert dashboard.generated_at == "2026-08-10 09:05"

    def test_drafts_picked_up(self, tmp_path):
        _write(str(tmp_path / "abc.brief.md"), "x")
        _write(str(tmp_path / "abc.article.md"), "x")
        dashboard = build_dashboard(state_file=str(tmp_path / "s.json"), drafts_dir=str(tmp_path))
        assert [d.slug for d in dashboard.drafts] == ["abc"]
        assert dashboard.drafts[0].has_article


class TestBuildDashboardNews:
    def test_no_reader_means_no_news(self, tmp_path):
        dashboard = build_dashboard(state_file=str(tmp_path / "s.json"), drafts_dir=str(tmp_path))
        assert dashboard.news is None

    def test_unconfigured_reader_means_no_news(self, tmp_path):
        dashboard = build_dashboard(
            state_file=str(tmp_path / "s.json"),
            drafts_dir=str(tmp_path),
            news_reader=FakeNewsReader(configured=False),
        )
        assert dashboard.news is None

    def test_reader_items_become_news(self, tmp_path):
        reader = FakeNewsReader([_news_item("皮卡丘")])
        dashboard = build_dashboard(
            state_file=str(tmp_path / "s.json"), drafts_dir=str(tmp_path), news_reader=reader
        )

        assert [n.title for n in dashboard.news] == ["皮卡丘"]
        assert reader.requested_limit == NEWS_LIMIT

    def test_query_failure_reported_but_dashboard_still_builds(self, tmp_path, capsys):
        """回歸測試：Notion 掛掉時儀表板還是要能產生，但必須說清楚少了什麼。"""
        dashboard = build_dashboard(
            state_file=str(tmp_path / "s.json"),
            drafts_dir=str(tmp_path),
            news_reader=FakeNewsReader(fails=True),
        )

        assert dashboard.news is None
        assert "[Warn]" in capsys.readouterr().out


class TestCliIntegration:
    def test_dashboard_command_writes_file(self, tmp_path, capsys, monkeypatch):
        from src import cli

        monkeypatch.setattr(cli, "NotionReader", lambda: FakeNewsReader(configured=False))

        output = str(tmp_path / "out" / "dashboard.html")
        assert cli.main(["dashboard", "--output", output, "--dir", str(tmp_path)]) == 0
        assert os.path.exists(output)
        with open(output, encoding="utf-8") as f:
            assert "<html" in f.read()
        assert "儀表板已產生" in capsys.readouterr().out

    def test_dashboard_command_includes_notion_news(self, tmp_path, monkeypatch):
        """dashboard 指令要把 Notion 的最近新聞帶進網頁。"""
        from src import cli

        monkeypatch.setattr(cli, "NotionReader", lambda: FakeNewsReader([_news_item("皮卡丘新聞")]))

        output = str(tmp_path / "dashboard.html")
        assert cli.main(["dashboard", "--output", output, "--dir", str(tmp_path)]) == 0
        with open(output, encoding="utf-8") as f:
            html = f.read()

        assert "皮卡丘新聞" in html
        assert "待撰稿佇列" in html
