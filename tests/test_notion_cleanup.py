from src.notion import schema
from src.notion.cleanup import (
    CleanupTarget,
    NotionCleanup,
    cleanup_filter,
    excluded_source_names,
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
        assert clauses == [{"property": schema.SOURCE, "rich_text": {"equals": "@UniteVids"}}]

    def test_status_and_sources_are_a_union(self):
        """兩個條件是聯集：略過的、或來自排除來源的，都要清掉。"""
        clauses = cleanup_filter(schema.STATUS_SKIPPED, {"@UniteVids"})["or"]
        assert len(clauses) == 2

    def test_sources_sorted_for_stable_output(self):
        clauses = cleanup_filter("", {"B", "A"})["or"]
        assert [c["rich_text"]["equals"] for c in clauses] == ["A", "B"]

    def test_no_criteria_is_none(self):
        assert cleanup_filter("", set()) is None


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
