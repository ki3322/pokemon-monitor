from src.notion import schema
from src.notion.upgrade import NotionUpgrade, build_patch, describe


def _database(properties=None, icon=None, description=""):
    return {
        "id": "db",
        "title": [{"plain_text": "Pokemon 新聞待撰稿"}],
        "description": [{"plain_text": description}] if description else [],
        "icon": icon,
        "properties": properties if properties is not None else {},
    }


def _full_properties():
    return {name: {} for name in schema.database_properties()}


class TestMissingProperties:
    def test_reports_all_when_empty(self):
        assert set(schema.missing_properties({})) == set(schema.database_properties())

    def test_reports_none_when_complete(self):
        assert schema.missing_properties(_full_properties()) == {}

    def test_existing_properties_never_resent(self):
        """回歸測試：PATCH 送出同名欄位會覆寫設定，把使用者的調整打回預設。"""
        existing = {schema.STATUS: {}, schema.TITLE: {}}
        missing = schema.missing_properties(existing)
        assert schema.STATUS not in missing
        assert schema.TITLE not in missing

    def test_new_fields_are_the_added_ones(self):
        missing = schema.missing_properties(
            {
                schema.TITLE: {}, schema.LINK: {}, schema.SOURCE: {}, schema.CATEGORY: {},
                schema.FOUND_AT: {}, schema.SELECTED: {}, schema.STATUS: {},
                schema.ITEM_ID: {}, schema.WORDPRESS_URL: {},
            }
        )
        assert set(missing) == {schema.ORIGINAL_TITLE, schema.FRESHNESS, schema.PUBLISHED}

    def test_handles_none_input(self):
        assert set(schema.missing_properties(None)) == set(schema.database_properties())


class TestFormulas:
    def test_freshness_reads_found_at(self):
        assert f'prop("{schema.FOUND_AT}")' in schema.FRESHNESS_FORMULA

    def test_freshness_handles_empty_date(self):
        assert "empty(" in schema.FRESHNESS_FORMULA

    def test_published_derives_from_wordpress_url(self):
        assert f'prop("{schema.WORDPRESS_URL}")' in schema.PUBLISHED_FORMULA
        assert "未上稿" in schema.PUBLISHED_FORMULA
        assert "已上稿" in schema.PUBLISHED_FORMULA

    def test_formula_properties_declared_as_formula(self):
        properties = schema.database_properties()
        assert "formula" in properties[schema.FRESHNESS]
        assert "formula" in properties[schema.PUBLISHED]

    def test_parentheses_balanced(self):
        for expression in (schema.FRESHNESS_FORMULA, schema.PUBLISHED_FORMULA):
            assert expression.count("(") == expression.count(")")


class TestBuildPatch:
    def test_empty_database_gets_everything(self):
        patch = build_patch(_database())
        assert "properties" in patch and "icon" in patch and "description" in patch

    def test_complete_database_needs_no_patch(self):
        database = _database(
            properties=_full_properties(),
            icon={"type": "emoji", "emoji": "📰"},
            description="已經有說明",
        )
        assert build_patch(database) == {}

    def test_existing_icon_not_replaced(self):
        database = _database(_full_properties(), icon={"type": "emoji", "emoji": "🎮"})
        assert "icon" not in build_patch(database)

    def test_existing_description_not_replaced(self):
        database = _database(_full_properties(), description="使用者自己寫的")
        assert "description" not in build_patch(database)

    def test_only_missing_properties_included(self):
        existing = {name: {} for name in schema.database_properties() if name != schema.FRESHNESS}
        patch = build_patch(_database(existing))
        assert list(patch["properties"]) == [schema.FRESHNESS]


class TestDescribe:
    def test_lists_new_fields(self):
        changes = describe({"properties": {"新鮮度": {}}})
        assert changes == ["新增欄位「新鮮度」"]

    def test_mentions_icon_and_description(self):
        changes = describe({"icon": {}, "description": []})
        assert any("圖示" in c for c in changes)
        assert any("說明" in c for c in changes)

    def test_empty_patch_has_no_changes(self):
        assert describe({}) == []


class FakeClient:
    def __init__(self, database=None, rows=None, update_ok=True, page_update_ok=True, query_fails=False):
        self.token = "t"
        self.database_id = "db"
        self.database = database
        self.rows = rows or []
        self.update_ok = update_ok
        self.page_update_ok = page_update_ok
        self.query_fails = query_fails
        self.patches = []
        self.page_updates = []

    def retrieve_database(self, database_id=""):
        return self.database

    def update_database(self, database_id, patch):
        self.patches.append(patch)
        return {"ok": True} if self.update_ok else None

    def query_database(self, filter_=None, page_size=100):
        return None if self.query_fails else self.rows

    def update_page(self, page_id, properties):
        self.page_updates.append((page_id, properties))
        return {"ok": True} if self.page_update_ok else None


class TestRun:
    def test_applies_patch_and_reports_changes(self):
        client = FakeClient(_database())
        ok, changes = NotionUpgrade(client).run()
        assert ok and changes
        assert len(client.patches) == 1

    def test_no_patch_sent_when_already_current(self):
        client = FakeClient(
            _database(_full_properties(), icon={"type": "emoji", "emoji": "📰"}, description="x")
        )
        ok, changes = NotionUpgrade(client).run()
        assert ok and changes == []
        assert client.patches == []

    def test_unreadable_database_reports_reason(self):
        ok, problems = NotionUpgrade(FakeClient(None)).run()
        assert not ok
        assert "integration" in problems[0]

    def test_failed_write_reported(self):
        ok, problems = NotionUpgrade(FakeClient(_database(), update_ok=False)).run()
        assert not ok
        assert "未變更" in problems[0]

    def test_missing_database_id(self):
        client = FakeClient(_database())
        client.database_id = ""
        ok, problems = NotionUpgrade(client).run()
        assert not ok
        assert "NOTION_DATABASE_ID" in problems[0]


def _row(page_id, title, original=None):
    properties = {schema.TITLE: {"title": [{"plain_text": title}]}}
    if original is not None:
        properties[schema.ORIGINAL_TITLE] = {
            "rich_text": [{"plain_text": original}] if original else []
        }
    return {"id": page_id, "properties": properties}


class TestBackfill:
    def test_fills_empty_original_title(self):
        client = FakeClient(_database(), rows=[_row("p1", "來源標題")])
        filled, failed = NotionUpgrade(client).backfill_original_titles()
        assert (filled, failed) == (1, 0)
        written = client.page_updates[0][1][schema.ORIGINAL_TITLE]["rich_text"][0]
        assert written["text"]["content"] == "來源標題"

    def test_does_not_overwrite_existing(self):
        """已經有值的可能是使用者自己改的，不能蓋掉。"""
        client = FakeClient(_database(), rows=[_row("p1", "定稿標題", original="原始標題")])
        filled, _ = NotionUpgrade(client).backfill_original_titles()
        assert filled == 0
        assert client.page_updates == []

    def test_skips_rows_without_title(self):
        client = FakeClient(_database(), rows=[_row("p1", "")])
        assert NotionUpgrade(client).backfill_original_titles() == (0, 0)

    def test_counts_failures(self):
        client = FakeClient(_database(), rows=[_row("p1", "標題")], page_update_ok=False)
        assert NotionUpgrade(client).backfill_original_titles() == (0, 1)

    def test_reports_query_failure(self):
        """回歸測試：查詢失敗必須與「資料庫是空的」區分開來，
        否則回填會回報 0 筆補上、看起來一切正常。"""
        client = FakeClient(_database(), query_fails=True)
        assert NotionUpgrade(client).backfill_original_titles() is None

    def test_explicit_database_id_targets_that_database(self, monkeypatch):
        built = {}

        class Recorder(FakeClient):
            pass

        def fake_client(token=None, database_id=None):
            built["database_id"] = database_id
            return Recorder(_database(), rows=[])

        monkeypatch.setattr("src.notion.upgrade.NotionClient", fake_client)
        NotionUpgrade(FakeClient(_database())).backfill_original_titles("other-db")
        assert built["database_id"] == "other-db"
