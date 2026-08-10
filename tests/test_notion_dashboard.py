from src.dashboard.stats import KIND_TWITTER, KIND_WEBSITE, Dashboard, DraftStat, GroupStat
from src.notion import blocks as nb
from src.notion import dashboard as nd
from src.notion.ids import page_url, parse_page_id
from src.state import MAX_ITEMS_PER_SOURCE, STATE_VERSION

DASHBOARD = Dashboard(
    generated_at="2026-08-10 09:00",
    state_version=STATE_VERSION,
    notion_configured=True,
    groups=(
        GroupStat("Serebii.net", KIND_WEBSITE, ("Serebii.net",), telegram=42, notion=40),
        GroupStat("twitter_PokemonGoApp", KIND_TWITTER, ("@PokemonGoApp",), telegram=8),
    ),
    drafts=(DraftStat("3b8d2e5bf409", True, True),),
)


def _types(blocks):
    return [b["type"] for b in blocks]


def _all_text(blocks):
    """把巢狀區塊裡所有 plain text 攤平，方便斷言內容有出現。"""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                found.append(node["text"]["content"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    return "".join(found)


class TestParsePageId:
    def test_from_share_url(self):
        assert parse_page_id("https://app.notion.com/p/0123456789abcdef0123456789abcdef") == (
            "0123456789abcdef0123456789abcdef"
        )

    def test_from_hyphenated_id(self):
        value = "0123456789abcdef0123456789abcdef"
        assert parse_page_id(value) == value

    def test_url_with_query_string(self):
        assert parse_page_id(
            "https://app.notion.com/p/0123456789abcdef0123456789abcdef?source=copy_link"
        ) == "0123456789abcdef0123456789abcdef"

    def test_rejects_garbage(self):
        assert parse_page_id("not a page") == ""

    def test_handles_empty_input(self):
        assert parse_page_id("") == ""

    def test_page_url_strips_hyphens(self):
        assert page_url("01234567-89ab-cdef-0123-456789abcdef").endswith(
            "0123456789abcdef0123456789abcdef"
        )


class TestMeter:
    def test_empty_when_zero(self):
        assert nd.meter(0) == nd.METER_EMPTY * nd.METER_CELLS

    def test_full_at_ceiling(self):
        assert nd.meter(MAX_ITEMS_PER_SOURCE) == nd.METER_FULL * nd.METER_CELLS

    def test_never_overflows_above_ceiling(self):
        assert len(nd.meter(MAX_ITEMS_PER_SOURCE * 5)) == nd.METER_CELLS

    def test_proportional_in_between(self):
        assert nd.meter(50) == nd.METER_FULL * 5 + nd.METER_EMPTY * 5

    def test_zero_ceiling_does_not_divide_by_zero(self):
        assert nd.meter(3, ceiling=0) == nd.METER_EMPTY * nd.METER_CELLS


class TestTextTable:
    def test_width_from_header(self):
        table = nb.text_table([("a", "b"), ("1", "2")])
        assert table["table"]["table_width"] == 2

    def test_short_rows_padded(self):
        """回歸測試：Notion 拒絕儲存格數量與 table_width 不符的列。"""
        table = nb.text_table([("a", "b", "c"), ("1",)])
        assert all(
            len(r["table_row"]["cells"]) == 3 for r in table["table"]["children"]
        )

    def test_long_rows_truncated(self):
        table = nb.text_table([("a",), ("1", "2", "3")])
        assert all(
            len(r["table_row"]["cells"]) == 1 for r in table["table"]["children"]
        )


class TestColumnList:
    def test_wraps_each_group_in_a_column(self):
        block = nb.column_list_block([[nb.paragraph_block("a")], [nb.paragraph_block("b")]])
        children = block["column_list"]["children"]
        assert _types(children) == ["column", "column"]

    def test_column_children_preserved(self):
        block = nb.column_list_block([[nb.paragraph_block("a")], [nb.paragraph_block("b")]])
        first = block["column_list"]["children"][0]["column"]["children"]
        assert _all_text(first) == "a"


class TestCallout:
    def test_emoji_and_color(self):
        block = nb.callout_block("hi", emoji="📡", color="yellow_background")
        assert block["callout"]["icon"] == {"type": "emoji", "emoji": "📡"}
        assert block["callout"]["color"] == "yellow_background"

    def test_omits_optional_keys_when_unset(self):
        block = nb.callout_block("hi")
        assert "icon" not in block["callout"]
        assert "color" not in block["callout"]

    def test_children_nested_under_callout(self):
        block = nb.callout_block("hi", children=[nb.paragraph_block("inner")])
        assert _all_text(block["callout"]["children"]) == "inner"

    def test_heading_accepts_color(self):
        assert nb.heading_block("x", color="gray")["heading_2"]["color"] == "gray"


class TestBuildBlocks:
    BLOCKS = nd.build_blocks(DASHBOARD)

    def test_starts_with_summary_callout(self):
        assert self.BLOCKS[0]["type"] == "callout"
        assert "2026-08-10 09:00" in _all_text([self.BLOCKS[0]])

    def test_funnel_uses_columns(self):
        assert "column_list" in _types(self.BLOCKS)

    def test_funnel_column_count_within_notion_limits(self):
        columns = next(b for b in self.BLOCKS if b["type"] == "column_list")
        count = len(columns["column_list"]["children"])
        assert nd.MIN_COLUMNS <= count <= nd.MAX_COLUMNS

    def test_group_tables_present(self):
        assert _types(self.BLOCKS).count("table") == 3  # 網站 / Twitter / 稿件

    def test_twitter_prefix_stripped(self):
        text = _all_text(self.BLOCKS)
        assert "twitter_PokemonGoApp" not in text
        assert "@PokemonGoApp" in text

    def test_meter_rendered_in_table(self):
        assert nd.METER_FULL in _all_text(self.BLOCKS)

    def test_design_credit_present(self):
        assert "Antoniouve" in _all_text(self.BLOCKS)

    def test_every_block_has_matching_type_key(self):
        """Notion 會拒絕 type 與內容鍵不一致的區塊。"""
        assert all(block["type"] in block for block in self.BLOCKS)

    def test_fits_in_one_append_request(self):
        assert len(list(nb.batched(self.BLOCKS))) == 1


class TestWarnings:
    def test_legacy_state_warned(self):
        text = _all_text(nd.build_blocks(Dashboard("now", state_version=1)))
        assert "重新初始化" in text

    def test_pending_groups_listed(self):
        blocks = nd.build_blocks(
            Dashboard("now", state_version=STATE_VERSION,
                      groups=(GroupStat("Serebii.net", KIND_WEBSITE),))
        )
        assert "待初始化" in _all_text(blocks)
        assert "Serebii.net" in _all_text(blocks)

    def test_unconfigured_notion_warned(self):
        blocks = nd.build_blocks(Dashboard("now", state_version=STATE_VERSION))
        assert "NOTION_DATABASE_ID" in _all_text(blocks)

    def test_warning_is_scoped_to_local_environment(self):
        """這個旗標讀不到 GitHub Secrets，不能講成「監控端沒設定」。"""
        text = _all_text(nd.build_blocks(Dashboard("now", state_version=STATE_VERSION)))
        assert "產生這頁的環境" in text
        assert "監控本身還沒設定" not in text

    def test_configured_notion_not_warned(self):
        assert "NOTION_DATABASE_ID" not in _all_text(nd.build_blocks(DASHBOARD))

    def test_empty_dashboard_still_builds(self):
        blocks = nd.build_blocks(Dashboard("now"))
        assert blocks and all(b["type"] in b for b in blocks)


class FakeClient:
    """記錄呼叫的假用戶端，避免測試打真的 Notion API。"""

    def __init__(self, children=None, create_result=None, fail_append=False, list_fails=False):
        self.children = children if children is not None else []
        self.create_result = create_result
        self.fail_append = fail_append
        self.list_fails = list_fails
        self.appended = []
        self.deleted = []
        self.created = []

    def list_children(self, page_id):
        return None if self.list_fails else self.children

    def delete_block(self, block_id):
        self.deleted.append(block_id)
        return True

    def create_child_page(self, parent_page_id, title, children=None):
        self.created.append((parent_page_id, title))
        return self.create_result

    def append_blocks(self, page_id, children):
        if self.fail_append:
            return False
        self.appended.append((page_id, children))
        return True


def _child_page(page_id, title):
    return {"id": page_id, "type": "child_page", "child_page": {"title": title}}


class TestFindChildPage:
    def test_matches_by_title(self):
        client = FakeClient([_child_page("abc", nd.PAGE_TITLE)])
        assert nd.find_child_page(client, "parent", nd.PAGE_TITLE) == "abc"

    def test_ignores_other_titles(self):
        client = FakeClient([_child_page("abc", "別的頁")])
        assert nd.find_child_page(client, "parent", nd.PAGE_TITLE) == ""

    def test_ignores_non_page_blocks(self):
        client = FakeClient([{"id": "x", "type": "paragraph", "paragraph": {}}])
        assert nd.find_child_page(client, "parent", nd.PAGE_TITLE) == ""


class TestPublish:
    def test_creates_page_when_absent(self):
        client = FakeClient(create_result={"id": "new-page"})
        assert nd.NotionDashboard(client).publish("parent", DASHBOARD) == "new-page"
        assert client.created == [("parent", nd.PAGE_TITLE)]

    def test_reuses_existing_page(self):
        """回歸測試：重複執行必須更新同一頁，不能每次長出新頁。"""
        client = FakeClient([_child_page("existing", nd.PAGE_TITLE)])
        assert nd.NotionDashboard(client).publish("parent", DASHBOARD) == "existing"
        assert client.created == []

    def test_aborts_when_children_unreadable(self, capsys):
        """回歸測試：讀不到父頁的子頁清單時必須中止——當成「沒有這一頁」
        會另外長出一頁新儀表板，疊成兩份。"""
        client = FakeClient(list_fails=True)

        assert nd.NotionDashboard(client).publish("parent", DASHBOARD) is None
        assert client.created == []
        assert client.appended == []
        assert "[Error]" in capsys.readouterr().out

    def test_existing_page_cleared_before_write(self):
        client = FakeClient([_child_page("existing", nd.PAGE_TITLE)])
        nd.NotionDashboard(client).publish("parent", DASHBOARD)
        assert client.deleted == ["existing"]

    def test_new_page_is_not_cleared(self):
        client = FakeClient(create_result={"id": "new-page"})
        nd.NotionDashboard(client).publish("parent", DASHBOARD)
        assert client.deleted == []

    def test_returns_none_when_creation_fails(self):
        assert nd.NotionDashboard(FakeClient(create_result=None)).publish("p", DASHBOARD) is None

    def test_returns_none_when_append_fails(self):
        client = FakeClient(create_result={"id": "new"}, fail_append=True)
        assert nd.NotionDashboard(client).publish("p", DASHBOARD) is None

    def test_aborts_without_writing_when_clear_fails(self):
        """回歸測試：清不掉舊內容就寫入，會疊出兩份儀表板。"""

        class StubbornClient(FakeClient):
            def delete_block(self, block_id):
                return False

        client = StubbornClient([_child_page("existing", nd.PAGE_TITLE)])
        assert nd.NotionDashboard(client).publish("parent", DASHBOARD) is None
        assert client.appended == []


class TestFunnelGuard:
    def test_too_few_stages_falls_back_to_text(self, monkeypatch):
        """欄位數不足兩欄時 Notion 會拒絕 column_list，必須改用純文字。"""
        monkeypatch.setattr(nd, "MAX_COLUMNS", 1)
        blocks = nd.funnel_blocks(DASHBOARD)
        assert _types(blocks) == ["paragraph"]
        assert "column_list" not in _types(blocks)
