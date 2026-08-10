from datetime import datetime, timezone

import pytest

from src.notion import schema
from src.notion.reader import NotionReader, pending_filter, to_selected_item
from src.notion.sync import NotionSync, _properties
from src.notion.writer import NotionWriter, build_page_blocks
from tests.conftest import make_item


class FakeNotionClient:
    """記錄呼叫的假 Notion 用戶端。"""

    def __init__(self, fail=False, pages=None, children=None, query_fails=False, list_fails=False):
        self.fail = fail
        self.pages = pages or []
        self.children = children or []
        self.query_fails = query_fails
        self.list_fails = list_fails
        self.created = []
        self.appended = []
        self.updated = []
        self.deleted = []

    def is_configured(self):
        return True

    def create_page(self, properties, children=None):
        if self.fail:
            return None
        self.created.append({"properties": properties, "children": children})
        return {"id": "page-1"}

    def query_database(self, filter_=None, page_size=100, sorts=None, limit=None):
        self.last_filter = filter_
        self.last_sorts = sorts
        self.last_limit = limit
        return None if self.query_fails else self.pages

    def list_children(self, page_id):
        return None if self.list_fails else self.children

    def delete_block(self, block_id):
        if self.fail:
            return False
        self.deleted.append(block_id)
        return True

    def append_blocks(self, page_id, children):
        if self.fail:
            return False
        self.appended.append(children)
        return True

    def update_page(self, page_id, properties):
        if self.fail:
            return None
        self.updated.append(properties)
        return {"id": page_id}


class TestSyncProperties:
    def test_maps_every_field(self):
        item = make_item("abc", title="標題", link="https://a.example/1", source="Serebii.net")
        props = _properties(item, now=datetime(2026, 8, 10, tzinfo=timezone.utc))

        assert props[schema.TITLE]["title"][0]["text"]["content"] == "標題"
        assert props[schema.LINK]["url"] == "https://a.example/1"
        assert props[schema.ITEM_ID]["rich_text"][0]["text"]["content"] == "abc"
        assert props[schema.STATUS]["select"]["name"] == schema.STATUS_PENDING
        assert props[schema.SELECTED]["checkbox"] is False

    def test_tweet_gets_tweet_category(self):
        item = make_item("t1", source_type="twitter")
        assert _properties(item)[schema.CATEGORY]["select"]["name"] == schema.CATEGORY_TWEET

    def test_empty_link_sent_as_null(self):
        """Notion 的 url 屬性不接受空字串。"""
        assert _properties(make_item("x", link=""))[schema.LINK]["url"] is None

    def test_original_title_recorded_alongside_title(self):
        """回歸測試：發布時 TITLE 會被換成定稿標題，原文標題只有這裡留得住。"""
        props = _properties(make_item("abc", title="來源原始標題"))
        assert props[schema.ORIGINAL_TITLE]["rich_text"][0]["text"]["content"] == "來源原始標題"

    def test_display_title_never_overwrites_original_title(self):
        """回歸測試：TITLE 用翻譯後的標題（列表才可讀），
        但「原始標題」必須是監控抓到的原文——翻譯後就再也還原不了。"""
        props = _properties(make_item("abc", title="Original Title"), display_title="翻譯後標題")

        assert props[schema.TITLE]["title"][0]["text"]["content"] == "翻譯後標題"
        assert props[schema.ORIGINAL_TITLE]["rich_text"][0]["text"]["content"] == "Original Title"


class TestSyncAddItem:
    def test_returns_true_on_success(self):
        sync = NotionSync(FakeNotionClient())
        assert sync.add_item(make_item("1")) is True

    def test_returns_false_on_failure(self):
        """回歸測試：失敗必須回報，呼叫端才不會標記為已投遞。"""
        sync = NotionSync(FakeNotionClient(fail=True))
        assert sync.add_item(make_item("1")) is False

    def test_source_link_added_as_first_block(self):
        client = FakeNotionClient()
        NotionSync(client).add_item(make_item("1", link="https://a.example/1"))

        children = client.created[0]["children"]
        assert children[0]["paragraph"]["rich_text"][0]["text"]["link"]["url"] == "https://a.example/1"

    def test_no_children_when_link_missing(self):
        client = FakeNotionClient()
        NotionSync(client).add_item(make_item("1", link=""))
        assert client.created[0]["children"] == []

    def test_display_title_passed_through_to_properties(self):
        client = FakeNotionClient()
        NotionSync(client).add_item(make_item("1", title="Original"), display_title="翻譯")

        props = client.created[0]["properties"]
        assert props[schema.TITLE]["title"][0]["text"]["content"] == "翻譯"
        assert props[schema.ORIGINAL_TITLE]["rich_text"][0]["text"]["content"] == "Original"


class TestReader:
    def test_filter_requires_checked_and_not_done(self):
        conditions = pending_filter()["and"]
        assert {"property": schema.SELECTED, "checkbox": {"equals": True}} in conditions
        assert {
            "property": schema.STATUS,
            "select": {"does_not_equal": schema.STATUS_DONE},
        } in conditions

    def test_parses_page_into_selected_item(self):
        page = {
            "id": "page-1",
            "properties": {
                schema.TITLE: {"title": [{"plain_text": "標題"}]},
                schema.LINK: {"url": "https://a.example/1"},
                schema.SOURCE: {"rich_text": [{"plain_text": "Serebii.net"}]},
                schema.CATEGORY: {"select": {"name": schema.CATEGORY_ARTICLE}},
                schema.STATUS: {"select": {"name": schema.STATUS_PENDING}},
            },
        }
        item = to_selected_item(page)

        assert item.page_id == "page-1"
        assert item.title == "標題"
        assert item.link == "https://a.example/1"
        assert item.source == "Serebii.net"

    def test_missing_properties_become_empty_strings(self):
        item = to_selected_item({"id": "p", "properties": {}})
        assert (item.title, item.link, item.source, item.status) == ("", "", "", "")

    def test_null_select_handled(self):
        page = {"id": "p", "properties": {schema.STATUS: {"select": None}}}
        assert to_selected_item(page).status == ""

    def test_pending_items_uses_filter(self):
        client = FakeNotionClient(pages=[{"id": "p", "properties": {}}])
        items = NotionReader(client).pending_items()

        assert len(items) == 1
        assert client.last_filter == pending_filter()

    def test_pending_items_reports_query_failure(self):
        """回歸測試：查詢失敗必須與「沒有勾選項目」區分開來，
        否則 API 掛掉會被當成一切正常。"""
        assert NotionReader(FakeNotionClient(query_fails=True)).pending_items() is None

    def test_parses_selected_and_found_at(self):
        page = {
            "id": "p",
            "properties": {
                schema.SELECTED: {"checkbox": True},
                schema.FOUND_AT: {"date": {"start": "2026-08-10T02:31:00.000+00:00"}},
            },
        }
        item = to_selected_item(page)

        assert item.selected is True
        assert item.found_at == "2026-08-10T02:31:00.000+00:00"

    def test_missing_selected_and_found_at_have_defaults(self):
        item = to_selected_item({"id": "p", "properties": {}})
        assert item.selected is False
        assert item.found_at == ""

    def test_recent_items_sorted_by_found_at_desc(self):
        client = FakeNotionClient(pages=[{"id": "p", "properties": {}}])
        items = NotionReader(client).recent_items(limit=30)

        assert len(items) == 1
        assert client.last_filter is None
        assert client.last_sorts == [{"property": schema.FOUND_AT, "direction": "descending"}]
        assert client.last_limit == 30

    def test_recent_items_reports_query_failure(self):
        assert NotionReader(FakeNotionClient(query_fails=True)).recent_items(limit=30) is None


class TestWriter:
    ARTICLE = "# 標題\n\n## 段落\n\n內文含 **重點**。\n"

    def test_page_starts_with_source_then_html_toggle(self):
        page_blocks = build_page_blocks(self.ARTICLE, link="https://a.example/1")

        assert page_blocks[0]["type"] == "paragraph"
        assert page_blocks[1]["type"] == "toggle"

    def test_html_toggle_contains_code_block(self):
        toggle = build_page_blocks(self.ARTICLE)[0]
        code = toggle["toggle"]["children"][0]

        assert code["code"]["language"] == "html"
        assert "<h2>段落</h2>" in code["code"]["rich_text"][0]["text"]["content"]

    def test_html_excludes_the_h1_title(self):
        toggle = build_page_blocks(self.ARTICLE)[0]
        html = toggle["toggle"]["children"][0]["code"]["rich_text"][0]["text"]["content"]
        assert "<h1>" not in html

    def test_native_blocks_follow_the_html(self):
        kinds = [b["type"] for b in build_page_blocks(self.ARTICLE)]
        assert "heading_2" in kinds
        assert kinds.index("divider") < kinds.index("heading_2")

    def test_publish_clears_then_writes_then_updates(self):
        client = FakeNotionClient(children=[{"id": "old-1"}, {"id": "old-2"}])
        assert NotionWriter(client).publish("page-1", self.ARTICLE) is True

        assert client.deleted == ["old-1", "old-2"]
        assert client.appended
        assert client.updated[0][schema.STATUS]["select"]["name"] == schema.STATUS_DONE

    def test_publish_syncs_title_from_h1(self):
        client = FakeNotionClient()
        NotionWriter(client).publish("page-1", self.ARTICLE)

        assert client.updated[0][schema.TITLE]["title"][0]["text"]["content"] == "標題"

    def test_publish_skips_clearing_when_appending(self):
        client = FakeNotionClient(children=[{"id": "old-1"}])
        NotionWriter(client).publish("page-1", self.ARTICLE, replace=False)
        assert client.deleted == []

    def test_publish_aborts_when_children_unreadable(self, capsys):
        """回歸測試：讀不到既有內容時不能當成「頁面是空的」，
        照樣附加會讓文章疊成兩份。"""
        client = FakeNotionClient(list_fails=True)
        assert NotionWriter(client).publish("page-1", self.ARTICLE) is False

        assert client.appended == []
        assert "[Error]" in capsys.readouterr().out

    def test_publish_returns_false_on_failure(self):
        client = FakeNotionClient(fail=True)
        assert NotionWriter(client).publish("page-1", self.ARTICLE) is False

    def test_publish_records_wordpress_url(self):
        client = FakeNotionClient()
        NotionWriter(client).publish("p", self.ARTICLE, wordpress_url="https://hub/x")
        assert client.updated[0][schema.WORDPRESS_URL]["url"] == "https://hub/x"

    def test_long_article_split_into_batches(self):
        """回歸測試：Notion 單次最多 100 個區塊。"""
        long_article = "# 標題\n\n" + "\n\n".join(f"第 {i} 段。" for i in range(250))
        client = FakeNotionClient()
        NotionWriter(client).publish("page-1", long_article)

        assert len(client.appended) > 1
        assert all(len(batch) <= 100 for batch in client.appended)
