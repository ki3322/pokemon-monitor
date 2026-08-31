from src.notion import schema
from src.notion.cleanup import NotionCleanup, skipped_filter


def _page(page_id, title="標題"):
    return {
        "id": page_id,
        "properties": {
            schema.TITLE: {"title": [{"plain_text": title}]},
            schema.STATUS: {"select": {"name": schema.STATUS_SKIPPED}},
        },
    }


class FakeClient:
    def __init__(self, pages=None, fail_ids=()):
        self.pages = pages
        self.fail_ids = set(fail_ids)
        self.archived = []
        self.queries = []

    def query_database(self, filter_=None, page_size=100, sorts=None, limit=None):
        self.queries.append(filter_)
        return self.pages

    def archive_page(self, page_id):
        if page_id in self.fail_ids:
            return False
        self.archived.append(page_id)
        return True


class TestSkippedFilter:
    def test_matches_only_skipped_status(self):
        assert skipped_filter() == {
            "property": schema.STATUS,
            "select": {"equals": schema.STATUS_SKIPPED},
        }

    def test_filter_is_sent_to_notion(self):
        client = FakeClient([])
        NotionCleanup(client).run()
        assert client.queries == [skipped_filter()]


class TestRun:
    def test_archives_every_skipped_page(self):
        client = FakeClient([_page("p1"), _page("p2")])
        assert NotionCleanup(client).run() == (2, 0)
        assert client.archived == ["p1", "p2"]

    def test_nothing_to_do_is_not_an_error(self):
        client = FakeClient([])
        assert NotionCleanup(client).run() == (0, 0)
        assert client.archived == []

    def test_query_failure_returns_none(self):
        """回歸測試：查不到不等於沒有要刪的，必須中止而不是回報「已完成」。"""
        assert NotionCleanup(FakeClient(None)).run() is None

    def test_counts_failures_separately(self):
        client = FakeClient([_page("p1"), _page("p2")], fail_ids={"p1"})
        assert NotionCleanup(client).run() == (1, 1)

    def test_one_failure_does_not_stop_the_rest(self):
        client = FakeClient([_page("p1"), _page("p2")], fail_ids={"p1"})
        NotionCleanup(client).run()
        assert client.archived == ["p2"]

    def test_dry_run_archives_nothing(self):
        client = FakeClient([_page("p1"), _page("p2")])
        assert NotionCleanup(client).run(dry_run=True) == (2, 0)
        assert client.archived == []


class TestSkippedItems:
    def test_parses_pages_into_items(self):
        items = NotionCleanup(FakeClient([_page("p1", "不要的新聞")])).skipped_items()
        assert [i.page_id for i in items] == ["p1"]
        assert items[0].title == "不要的新聞"

    def test_failure_returns_none(self):
        assert NotionCleanup(FakeClient(None)).skipped_items() is None
