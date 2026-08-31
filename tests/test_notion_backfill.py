from src.models import FeedItem
from src.notion import schema
from src.notion.backfill import NotionBackfill, collect_items


def make_item(item_id, title="標題", source="Serebii.net"):
    return FeedItem(
        id=item_id, title=title, link=f"https://a.example/{item_id}",
        source=source, source_type="website",
    )


def _page(item_id):
    return {
        "id": f"page-{item_id}",
        "properties": {schema.ITEM_ID: {"rich_text": [{"plain_text": item_id}]}},
    }


class FakeClient:
    def __init__(self, pages=None):
        self.pages = pages
        self.token = "t"
        self.database_id = "db"

    def query_database(self, filter_=None, page_size=100, sorts=None, limit=None):
        return self.pages


class FakeSync:
    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.added = []

    def add_item(self, item, display_title=""):
        if item.id in self.fail_ids:
            return False
        self.added.append((item.id, display_title))
        return True


def _ok(items):
    return lambda *_: (items, True)


def _fail(*_):
    return [], False


class TestCollectItems:
    def test_gathers_from_every_source_kind(self):
        collected, failures = collect_items(
            [{"name": "rss"}], [{"name": "web"}], ["acct"],
            _ok([make_item("a")]), _ok([make_item("b")]), _ok([make_item("c")]),
        )
        assert {item.id for item, _ in collected} == {"a", "b", "c"}
        assert failures == []

    def test_duplicate_ids_collapsed(self):
        """共用 group 的來源大量重疊，同一則不該被建立兩次。"""
        collected, _ = collect_items(
            [], [{"name": "x"}, {"name": "y"}], [],
            _fail, _ok([make_item("dup")]), _fail,
        )
        assert len(collected) == 1

    def test_failed_source_recorded_not_raised(self):
        collected, failures = collect_items(
            [{"name": "rss"}], [], [], _fail, _fail, _fail,
        )
        assert collected == []
        assert failures == ["rss"]

    def test_one_failure_does_not_stop_the_rest(self):
        collected, failures = collect_items(
            [{"name": "rss"}], [{"name": "web"}], [],
            _fail, _ok([make_item("b")]), _fail,
        )
        assert [item.id for item, _ in collected] == ["b"]
        assert failures == ["rss"]

    def test_translate_flag_carried_through(self):
        collected, _ = collect_items(
            [], [{"name": "toy", "translate": False}], [],
            _fail, _ok([make_item("a")]), _fail,
        )
        assert collected[0][1] is False

    def test_translate_defaults_to_true(self):
        collected, _ = collect_items(
            [], [{"name": "x"}], [], _fail, _ok([make_item("a")]), _fail,
        )
        assert collected[0][1] is True

    def test_unregistered_scraper_is_a_failure_not_a_crash(self):
        def boom(_):
            raise ValueError("沒有對應的爬蟲")

        collected, failures = collect_items([], [{"name": "bad"}], [], _fail, boom, _fail)
        assert collected == []
        assert failures == ["bad"]

    def test_items_without_id_dropped(self):
        collected, _ = collect_items(
            [], [{"name": "x"}], [], _fail, _ok([make_item("")]), _fail,
        )
        assert collected == []


class TestExistingItemIds:
    def test_reads_item_id_property(self):
        backfill = NotionBackfill(sync=FakeSync(), client=FakeClient([_page("a"), _page("b")]))
        assert backfill.existing_item_ids() == {"a", "b"}

    def test_query_failure_returns_none(self):
        """回歸測試：查詢失敗不能當成「資料庫是空的」，否則會整個灌一次。"""
        backfill = NotionBackfill(sync=FakeSync(), client=FakeClient(None))
        assert backfill.existing_item_ids() is None

    def test_empty_database_is_empty_set_not_none(self):
        backfill = NotionBackfill(sync=FakeSync(), client=FakeClient([]))
        assert backfill.existing_item_ids() == set()


class TestRun:
    def _backfill(self, pages, fail_ids=()):
        sync = FakeSync(fail_ids)
        return NotionBackfill(sync=sync, client=FakeClient(pages)), sync

    def test_creates_missing_items(self):
        backfill, sync = self._backfill([])
        assert backfill.run([(make_item("a"), False)]) == (1, 0, 0)
        assert sync.added == [("a", "標題")]

    def test_skips_items_already_in_database(self):
        backfill, sync = self._backfill([_page("a")])
        assert backfill.run([(make_item("a"), False)]) == (0, 1, 0)
        assert sync.added == []

    def test_aborts_when_existing_cannot_be_read(self):
        backfill, sync = self._backfill(None)
        assert backfill.run([(make_item("a"), False)]) == (0, 0, 0)
        assert sync.added == []

    def test_counts_failures_separately(self):
        backfill, _ = self._backfill([], fail_ids={"a"})
        assert backfill.run([(make_item("a"), False), (make_item("b"), False)]) == (1, 0, 1)

    def test_translation_applied_only_when_requested(self):
        backfill, sync = self._backfill([])
        backfill.run(
            [(make_item("a", title="EN"), True), (make_item("b", title="中文"), False)],
            translate=lambda text: f"譯:{text}",
        )
        assert sync.added == [("a", "譯:EN"), ("b", "中文")]

    def test_dry_run_writes_nothing(self):
        backfill, sync = self._backfill([])
        created, skipped, failed = backfill.run([(make_item("a"), False)], dry_run=True)
        assert (created, skipped, failed) == (1, 0, 0)
        assert sync.added == []

    def test_dry_run_still_respects_existing(self):
        backfill, _ = self._backfill([_page("a")])
        assert backfill.run([(make_item("a"), False)], dry_run=True) == (0, 1, 0)

    def test_created_items_not_recreated_within_one_run(self):
        """同一輪若有重複 ID，第二次要算略過而不是再建一頁。"""
        backfill, sync = self._backfill([])
        created, skipped, _ = backfill.run([(make_item("a"), False), (make_item("a"), False)])
        assert (created, skipped) == (1, 1)
        assert len(sync.added) == 1
