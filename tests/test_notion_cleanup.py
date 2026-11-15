from datetime import datetime, timezone

import pytest

from src.notion import schema
from src.notion.cleanup import (
    REASON_EXCLUDED,
    CleanupTarget,
    NotionCleanup,
    cleanup_filter,
    excluded_clause,
    excluded_source_names,
    stale_clause,
)

RSS = [{"name": "Pokemon GO Hub", "url": "https://a.example/feed"}]
SCRAPE = [
    {"name": "Serebii.net", "url": "https://b.example"},
    {"name": "玩具人 寶可夢", "url": "https://c.example", "group": "玩具人"},
    {"name": "玩具人 寶可夢中心", "url": "https://d.example", "group": "玩具人"},
]
TWITTER = ["UniteVids", "PokemonGoApp"]


def _page(page_id="p", title="標題", source="Serebii.net", status=schema.STATUS_PENDING):
    return {
        "id": page_id,
        "properties": {
            schema.TITLE: {"title": [{"plain_text": title}]},
            schema.SOURCE: {"rich_text": [{"plain_text": source}]},
            schema.STATUS: {"select": {"name": status}},
        },
    }


class FakeClient:
    def __init__(self, pages=None, query_fails=False, archive_fails=()):
        self.pages = pages if pages is not None else []
        self.query_fails = query_fails
        self.archive_fails = set(archive_fails)
        self.archived = []
        self.last_filter = None

    def is_configured(self):
        return True

    def query_database(self, filter_=None, page_size=100, sorts=None, limit=None):
        self.last_filter = filter_
        return None if self.query_fails else self.pages

    def archive_page(self, page_id):
        if page_id in self.archive_fails:
            return False
        self.archived.append(page_id)
        return True


class TestExcludedSourceNames:
    def test_twitter_group_maps_to_at_handle(self):
        """推文的「來源」欄位存的是 @帳號，不是群組 ID。"""
        names = excluded_source_names(RSS, SCRAPE, TWITTER, {"twitter_UniteVids"})
        assert names == {"@UniteVids"}

    def test_website_group_maps_to_source_name(self):
        names = excluded_source_names(RSS, SCRAPE, TWITTER, {"Serebii.net"})
        assert names == {"Serebii.net"}

    def test_shared_group_maps_to_every_member(self):
        """玩具人兩個標籤頁共用 group，來源欄位各自是自己的 name。"""
        names = excluded_source_names(RSS, SCRAPE, TWITTER, {"玩具人"})
        assert names == {"玩具人 寶可夢", "玩具人 寶可夢中心"}

    def test_unknown_group_contributes_nothing(self):
        assert excluded_source_names(RSS, SCRAPE, TWITTER, {"不存在"}) == set()

    def test_empty_exclusions(self):
        assert excluded_source_names(RSS, SCRAPE, TWITTER, set()) == set()


class TestCleanupFilter:
    def test_status_only(self):
        assert cleanup_filter(schema.STATUS_SKIPPED, set()) == {
            "or": [{"property": schema.STATUS, "select": {"equals": schema.STATUS_SKIPPED}}]
        }

    def test_sources_only(self):
        clauses = cleanup_filter("", {"@UniteVids"})["or"]
        assert clauses == [excluded_clause("@UniteVids")]

    def test_status_and_sources_are_a_union(self):
        """兩個條件是聯集：略過的、或來自排除來源的，都要清掉。"""
        clauses = cleanup_filter(schema.STATUS_SKIPPED, {"@UniteVids"})["or"]
        assert len(clauses) == 2

    def test_sources_sorted_for_stable_output(self):
        clauses = cleanup_filter("", {"B", "A"})["or"]
        assert [c["and"][0]["rich_text"]["equals"] for c in clauses] == ["A", "B"]

    def test_no_criteria_is_none(self):
        assert cleanup_filter("", set()) is None


def _depth(filter_):
    """複合條件（and / or）的巢狀層數。"""
    if not isinstance(filter_, dict):
        return 0
    for key in ("and", "or"):
        if key in filter_:
            return 1 + max((_depth(c) for c in filter_[key]), default=0)
    return 0


class TestExcludedClause:
    """排除來源也要有護欄：已經投入人力的項目不能因為來源被排除就一起清掉。"""

    CONDITIONS = excluded_clause("@UniteVids")["and"]

    def test_matches_the_source(self):
        assert {"property": schema.SOURCE, "rich_text": {"equals": "@UniteVids"}} in self.CONDITIONS

    def test_requires_unchecked(self):
        """勾了就是要寫，就算來源被排除也不清。"""
        assert {"property": schema.SELECTED, "checkbox": {"equals": False}} in self.CONDITIONS

    @pytest.mark.parametrize("status", [schema.STATUS_WRITING, schema.STATUS_DONE])
    def test_spares_invested_work(self, status):
        """撰寫中／已完成代表已經投入過人力。"""
        assert {
            "property": schema.STATUS,
            "select": {"does_not_equal": status},
        } in self.CONDITIONS

    def test_full_filter_stays_within_notion_nesting_limit(self):
        """Notion 的複合條件最多兩層，超過會被 API 拒絕。"""
        filter_ = cleanup_filter(schema.STATUS_SKIPPED, {"A", "B"}, stale_clause(2, NOW))
        assert _depth(filter_) <= 2


class TestFindTargets:
    def test_maps_pages_to_targets(self):
        client = FakeClient([_page("p1", "標題A", "@UniteVids", schema.STATUS_PENDING)])
        targets = NotionCleanup(client).find_targets(sources={"@UniteVids"})

        assert len(targets) == 1
        assert targets[0].page_id == "p1"
        assert targets[0].title == "標題A"
        assert targets[0].source == "@UniteVids"

    def test_reason_names_the_matching_criterion(self):
        client = FakeClient(
            [
                _page("p1", "排除來源", "@UniteVids", schema.STATUS_PENDING),
                _page("p2", "略過的", "Serebii.net", schema.STATUS_SKIPPED),
            ]
        )
        targets = NotionCleanup(client).find_targets(
            status=schema.STATUS_SKIPPED, sources={"@UniteVids"}
        )

        reasons = {t.page_id: t.reason for t in targets}
        assert "來源已排除" in reasons["p1"]
        assert schema.STATUS_SKIPPED in reasons["p2"]

    def test_query_failure_returns_none(self):
        """查詢失敗要與「沒有東西要清」區分：前者不能讓使用者以為清乾淨了。"""
        assert NotionCleanup(FakeClient(query_fails=True)).find_targets(sources={"x"}) is None

    def test_no_criteria_returns_empty_without_querying(self):
        client = FakeClient([_page()])
        assert NotionCleanup(client).find_targets() == []
        assert client.last_filter is None


class TestArchive:
    def _targets(self, *page_ids):
        return [CleanupTarget(pid, "標題", "來源", "狀態", "原因") for pid in page_ids]

    def test_archives_every_target(self):
        client = FakeClient()
        assert NotionCleanup(client).archive(self._targets("a", "b")) == (2, 0)
        assert client.archived == ["a", "b"]

    def test_counts_failures_and_continues(self):
        """一筆失敗不該中止其餘的清理，但要如實回報。"""
        client = FakeClient(archive_fails={"a"})
        assert NotionCleanup(client).archive(self._targets("a", "b")) == (1, 1)
        assert client.archived == ["b"]

    def test_empty_is_noop(self):
        client = FakeClient()
        assert NotionCleanup(client).archive([]) == (0, 0)
        assert client.archived == []


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


class TestStaleClause:
    def _clause(self, days=2):
        return stale_clause(days, NOW)["and"]

    def test_requires_unchecked(self):
        """勾選了就是要寫，再舊都不能刪。"""
        assert {"property": schema.SELECTED, "checkbox": {"equals": False}} in self._clause()

    def test_requires_untouched_status(self):
        """只清「待處理」：撰寫中／已完成代表已經投入過人力，
        就算後來被取消勾選也不該連稿子一起刪掉。"""
        assert {
            "property": schema.STATUS,
            "select": {"equals": schema.STATUS_PENDING},
        } in self._clause()

    def test_cutoff_is_days_before_now(self):
        found = next(c for c in self._clause(2) if c["property"] == schema.FOUND_AT)
        assert found["date"]["before"] == "2026-08-09T12:00:00+00:00"

    def test_all_three_conditions_are_anded(self):
        assert len(self._clause()) == 3


class TestFilterWithStale:
    def test_stale_joins_the_union(self):
        clauses = cleanup_filter("", set(), stale_clause(2, NOW))["or"]
        assert len(clauses) == 1
        assert "and" in clauses[0]

    def test_combines_with_other_criteria(self):
        clauses = cleanup_filter(schema.STATUS_SKIPPED, {"@UniteVids"}, stale_clause(2, NOW))["or"]
        assert len(clauses) == 3

    def test_stale_alone_is_enough_to_query(self):
        assert cleanup_filter("", set(), stale_clause(2, NOW)) is not None


class TestStaleTargets:
    def test_find_targets_builds_stale_clause(self):
        client = FakeClient([_page("p1", "沒人要的新聞", "Serebii.net", schema.STATUS_PENDING)])
        targets = NotionCleanup(client).find_targets(status="", stale_days=2, now=NOW)

        assert len(targets) == 1
        assert "2 天" in targets[0].reason

    def test_no_stale_days_means_no_stale_clause(self):
        client = FakeClient([])
        NotionCleanup(client).find_targets(status=schema.STATUS_SKIPPED, now=NOW)

        assert client.last_filter == {
            "or": [{"property": schema.STATUS, "select": {"equals": schema.STATUS_SKIPPED}}]
        }

    def test_excluded_source_wins_the_reason(self):
        """同時符合兩個條件時，來源被排除是比較根本的理由。"""
        client = FakeClient([_page("p1", "舊推文", "@UniteVids", schema.STATUS_PENDING)])
        targets = NotionCleanup(client).find_targets(
            sources={"@UniteVids"}, stale_days=2, now=NOW
        )

        assert targets[0].reason == REASON_EXCLUDED


class TestStaleDaysValidation:
    """回歸測試：負數會把截止時間推到未來，匹配到每一筆待處理項目。

    實測 --stale -1 產生 before=明天，等於「封存整個資料庫」。
    """

    def test_negative_days_rejected(self):
        with pytest.raises(ValueError, match="至少 1 天"):
            stale_clause(-1, NOW)

    def test_zero_days_rejected(self):
        """0 天的截止時間就是「現在」，同樣會掃掉所有待處理項目。"""
        with pytest.raises(ValueError, match="至少 1 天"):
            stale_clause(0, NOW)

    def test_one_day_allowed(self):
        assert stale_clause(1, NOW)["and"]

    def test_cutoff_never_lands_in_the_future(self):
        for days in (1, 2, 30):
            found = next(
                c for c in stale_clause(days, NOW)["and"] if c["property"] == schema.FOUND_AT
            )
            assert found["date"]["before"] < NOW.isoformat()
