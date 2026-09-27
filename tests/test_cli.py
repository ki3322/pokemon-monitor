import os

import pytest

from src import cli
from src.article.brief import article_path, brief_path, build_brief, slug_for, write_brief
from src.notion import schema
from src.notion.reader import SelectedItem

ITEM = SelectedItem(
    page_id="1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
    title="測試標題",
    link="https://a.example/1",
    source="Serebii.net",
    category="文章",
    status="待處理",
)


def _item(page_id):
    return SelectedItem(
        page_id=page_id, title="標題", link="https://a.example/1",
        source="Serebii.net", category="文章", status="待處理",
    )


class TestBrief:
    def test_slug_strips_dashes(self):
        assert "-" not in slug_for(ITEM)

    def test_slug_keeps_the_whole_page_id(self):
        assert slug_for(ITEM) == ITEM.page_id.replace("-", "")

    def test_slug_is_stable(self):
        assert slug_for(ITEM) == slug_for(ITEM)

    def test_pages_sharing_a_long_prefix_get_different_slugs(self):
        """回歸測試：同一個資料庫相近時間建立的頁面，ID 前綴幾乎完全相同。

        截短成前 12 碼會讓不同文章共用檔名——實機上這兩個真實 ID 就撞在
        一起，後產生的 brief 直接蓋掉前一篇，稿件也可能被發布到錯的頁面。
        """
        a = _item("3b8d2e5b-f409-81ef-bef7-cffc1a76c487")
        b = _item("3b8d2e5b-f409-81f0-ad0a-d33b97b86d1e")

        assert a.page_id[:14] == b.page_id[:14]  # 前綴確實相同
        assert slug_for(a) != slug_for(b)

    def test_colliding_pages_write_to_different_files(self, tmp_path):
        a = _item("3b8d2e5b-f409-81ef-bef7-cffc1a76c487")
        b = _item("3b8d2e5b-f409-81f0-ad0a-d33b97b86d1e")

        assert brief_path(str(tmp_path), a) != brief_path(str(tmp_path), b)
        assert article_path(str(tmp_path), a) != article_path(str(tmp_path), b)

    def test_second_write_does_not_clobber_the_first(self, tmp_path):
        a = _item("3b8d2e5b-f409-81ef-bef7-cffc1a76c487")
        b = _item("3b8d2e5b-f409-81f0-ad0a-d33b97b86d1e")

        write_brief(str(tmp_path), a, "第一篇的原文")
        write_brief(str(tmp_path), b, "第二篇的原文")

        with open(brief_path(str(tmp_path), a), encoding="utf-8") as f:
            assert "第一篇的原文" in f.read()

    def test_empty_page_id_falls_back(self):
        assert slug_for(_item("")) == "untitled"

    def test_paths_differ_between_brief_and_article(self, tmp_path):
        assert brief_path(str(tmp_path), ITEM) != article_path(str(tmp_path), ITEM)

    def test_brief_carries_page_id_and_link(self):
        brief = build_brief(ITEM, "原文內容")

        assert f"page_id: {ITEM.page_id}" in brief
        assert f"link: {ITEM.link}" in brief
        assert "原文內容" in brief

    def test_brief_notes_missing_content(self):
        assert "無法自動抓取原文" in build_brief(ITEM, None)

    def test_write_brief_creates_directory(self, tmp_path):
        target = tmp_path / "nested" / "drafts"
        path = write_brief(str(target), ITEM, "內容")

        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            assert "測試標題" in f.read()


class FakeReader:
    def __init__(self, items, blocked=()):
        self.items = items
        self.blocked = list(blocked)
        self.client = type("C", (), {"is_configured": lambda self: True})()

    def pending_items(self):
        return self.items

    def blocked_items(self):
        return self.blocked


class FakeWriter:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def publish(self, page_id, markdown, link="", wordpress_url="", replace=True, status=""):
        self.calls.append(
            {
                "page_id": page_id, "markdown": markdown, "link": link,
                "replace": replace, "status": status,
            }
        )
        return self.ok


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(
        cli, "NotionClient", lambda: type("C", (), {
            "is_configured": lambda self: True,
            "retrieve_page": lambda self, pid: {"id": pid, "properties": {}},
        })()
    )


class TestListCommand:
    def test_reports_when_nothing_selected(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "NotionReader", lambda: FakeReader([]))

        assert cli.main(["list"]) == 0
        assert "沒有勾選待寫的項目" in capsys.readouterr().out

    def test_lists_selected_items(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "NotionReader", lambda: FakeReader([ITEM]))

        assert cli.main(["list"]) == 0
        out = capsys.readouterr().out
        assert "測試標題" in out
        assert ITEM.page_id in out

    def test_query_failure_returns_nonzero(self, monkeypatch, capsys):
        """回歸測試：Notion 查詢失敗不能被回報成「目前沒有勾選待寫的項目」。"""
        monkeypatch.setattr(cli, "NotionReader", lambda: FakeReader(None))

        assert cli.main(["list"]) == 1
        assert "[Error]" in capsys.readouterr().out

    def test_fails_clearly_when_unconfigured(self, monkeypatch, capsys):
        reader = FakeReader([])
        reader.client = type("C", (), {"is_configured": lambda self: False})()
        monkeypatch.setattr(cli, "NotionReader", lambda: reader)

        assert cli.main(["list"]) == 1
        assert "NOTION_TOKEN" in capsys.readouterr().out


class TestPendingCommand:
    def test_writes_brief_per_item(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(cli, "NotionReader", lambda: FakeReader([ITEM]))
        monkeypatch.setattr(cli, "fetch_content", lambda url: "抓到的原文")

        assert cli.main(["pending", "--dir", str(tmp_path)]) == 0
        assert os.path.exists(brief_path(str(tmp_path), ITEM))
        assert "1 則成功抓到原文" in capsys.readouterr().out

    def test_query_failure_returns_nonzero(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(cli, "NotionReader", lambda: FakeReader(None))

        assert cli.main(["pending", "--dir", str(tmp_path)]) == 1
        assert "[Error]" in capsys.readouterr().out

    def test_brief_still_written_when_fetch_fails(self, monkeypatch, tmp_path, capsys):
        """抓不到原文也要留下摘要檔，讓人工補內容。"""
        monkeypatch.setattr(cli, "NotionReader", lambda: FakeReader([ITEM]))
        monkeypatch.setattr(cli, "fetch_content", lambda url: None)

        assert cli.main(["pending", "--dir", str(tmp_path)]) == 0
        assert os.path.exists(brief_path(str(tmp_path), ITEM))
        assert "1 則需人工確認" in capsys.readouterr().out


class TestPublishCommand:
    def _article(self, tmp_path, text="# 標題\n\n內文\n"):
        path = tmp_path / "a.article.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_publishes_article(self, monkeypatch, tmp_path, configured, capsys):
        writer = FakeWriter()
        monkeypatch.setattr(cli, "NotionWriter", lambda client: writer)

        code = cli.main(["publish", "page-1", "--file", self._article(tmp_path)])

        assert code == 0
        assert writer.calls[0]["page_id"] == "page-1"
        assert "已寫入 Notion" in capsys.readouterr().out

    def test_missing_file_reports_error(self, monkeypatch, configured, capsys):
        monkeypatch.setattr(cli, "NotionWriter", lambda client: FakeWriter())

        assert cli.main(["publish", "p", "--file", "/nope/missing.md"]) == 1
        assert "無法讀取稿件" in capsys.readouterr().out

    def test_empty_file_rejected(self, monkeypatch, tmp_path, configured, capsys):
        monkeypatch.setattr(cli, "NotionWriter", lambda client: FakeWriter())

        code = cli.main(["publish", "p", "--file", self._article(tmp_path, "   \n")])

        assert code == 1
        assert "是空的" in capsys.readouterr().out

    def test_publish_failure_returns_nonzero(self, monkeypatch, tmp_path, configured):
        monkeypatch.setattr(cli, "NotionWriter", lambda client: FakeWriter(ok=False))

        assert cli.main(["publish", "p", "--file", self._article(tmp_path)]) == 1

    def test_append_flag_disables_replace(self, monkeypatch, tmp_path, configured):
        writer = FakeWriter()
        monkeypatch.setattr(cli, "NotionWriter", lambda client: writer)

        cli.main(["publish", "p", "--file", self._article(tmp_path), "--append"])

        assert writer.calls[0]["replace"] is False

    def test_default_publish_marks_done(self, monkeypatch, tmp_path, configured):
        writer = FakeWriter()
        monkeypatch.setattr(cli, "NotionWriter", lambda client: writer)

        cli.main(["publish", "p", "--file", self._article(tmp_path)])

        assert writer.calls[0]["status"] == schema.STATUS_DONE

    def test_draft_flag_marks_writing_for_review(self, monkeypatch, tmp_path, configured):
        """自動撰稿的稿子要停在「撰寫中」，人工審過才算完成。"""
        writer = FakeWriter()
        monkeypatch.setattr(cli, "NotionWriter", lambda client: writer)

        cli.main(["publish", "p", "--file", self._article(tmp_path), "--draft"])

        assert writer.calls[0]["status"] == schema.STATUS_WRITING

    def test_explicit_link_used_without_lookup(self, monkeypatch, tmp_path, configured):
        writer = FakeWriter()
        monkeypatch.setattr(cli, "NotionWriter", lambda client: writer)

        cli.main([
            "publish", "p", "--file", self._article(tmp_path), "--link", "https://b.example",
        ])

        assert writer.calls[0]["link"] == "https://b.example"


class FakeCleanupClient:
    """假的 NotionClient，記錄封存過哪些頁面。"""

    def __init__(self, pages=None, query_fails=False):
        self.pages = pages if pages is not None else []
        self.query_fails = query_fails
        self.archived = []

    def is_configured(self):
        return True

    def query_database(self, filter_=None, page_size=100, sorts=None, limit=None):
        return None if self.query_fails else self.pages

    def archive_page(self, page_id):
        self.archived.append(page_id)
        return True


def _cleanup_page(page_id="p1", title="舊推文", source="@UniteVids", status="待處理"):
    from src.notion import schema

    return {
        "id": page_id,
        "properties": {
            schema.TITLE: {"title": [{"plain_text": title}]},
            schema.SOURCE: {"rich_text": [{"plain_text": source}]},
            schema.STATUS: {"select": {"name": status}},
        },
    }


class TestNotionCleanupCommand:
    def _patch(self, monkeypatch, client):
        monkeypatch.setattr("src.cli.NotionClient", lambda: client)

    def test_dry_run_is_the_default(self, monkeypatch, capsys):
        """破壞性指令預設只是預覽：沒有 --yes 就什麼都不動。"""
        client = FakeCleanupClient([_cleanup_page()])
        self._patch(monkeypatch, client)

        assert cli.main(["notion-cleanup", "--excluded"]) == 0

        assert client.archived == []
        out = capsys.readouterr().out
        assert "舊推文" in out
        assert "--yes" in out

    def test_yes_archives(self, monkeypatch, capsys):
        client = FakeCleanupClient([_cleanup_page("p1"), _cleanup_page("p2")])
        self._patch(monkeypatch, client)

        assert cli.main(["notion-cleanup", "--excluded", "--yes"]) == 0
        assert client.archived == ["p1", "p2"]
        assert "已移到垃圾桶 2 筆" in capsys.readouterr().out

    def test_nothing_to_clean(self, monkeypatch, capsys):
        self._patch(monkeypatch, FakeCleanupClient([]))

        assert cli.main(["notion-cleanup", "--excluded", "--yes"]) == 0
        assert "沒有要清理的項目" in capsys.readouterr().out

    def test_query_failure_exits_nonzero(self, monkeypatch, capsys):
        """查詢失敗不能報成功，否則使用者以為清乾淨了。"""
        self._patch(monkeypatch, FakeCleanupClient(query_fails=True))

        assert cli.main(["notion-cleanup", "--excluded"]) == 1
        assert "[Error]" in capsys.readouterr().out

    def test_defaults_to_skipped_status(self, monkeypatch, capsys):
        """不給條件時清「略過」，與 README 的說明一致。"""
        from src.notion import schema

        client = FakeCleanupClient([_cleanup_page(status=schema.STATUS_SKIPPED)])
        self._patch(monkeypatch, client)

        assert cli.main(["notion-cleanup", "--yes"]) == 0
        assert client.archived == ["p1"]

    def test_unconfigured_notion_exits_nonzero(self, monkeypatch, capsys):
        class Unconfigured:
            def is_configured(self):
                return False

        self._patch(monkeypatch, Unconfigured())
        assert cli.main(["notion-cleanup"]) == 1
        assert "Notion 未設定" in capsys.readouterr().out

    def test_stale_flag_only_targets_unchecked_pending(self, monkeypatch):
        """--stale 的三個護欄要真的送到 Notion：沒勾選、待處理、夠舊。"""
        from src.notion import schema

        captured = {}

        class Recording(FakeCleanupClient):
            def query_database(self, filter_=None, page_size=100, sorts=None, limit=None):
                captured["filter"] = filter_
                return []

        self._patch(monkeypatch, Recording())
        assert cli.main(["notion-cleanup", "--status", "", "--stale", "2"]) == 0

        conditions = captured["filter"]["or"][0]["and"]
        assert {"property": schema.SELECTED, "checkbox": {"equals": False}} in conditions
        assert {
            "property": schema.STATUS,
            "select": {"equals": schema.STATUS_PENDING},
        } in conditions
        assert any(c.get("property") == schema.FOUND_AT for c in conditions)

    def test_stale_reason_shown_in_preview(self, monkeypatch, capsys):
        client = FakeCleanupClient([_cleanup_page(title="沒人要的新聞", status="待處理")])
        self._patch(monkeypatch, client)

        assert cli.main(["notion-cleanup", "--status", "", "--stale", "2"]) == 0
        assert "超過 2 天未勾選" in capsys.readouterr().out


class FakeListReader:
    """假的 NotionReader，分別控制佇列與卡住項目。"""

    def __init__(self, pending=(), blocked=(), pending_fails=False, blocked_fails=False):
        self.pending = list(pending)
        self.blocked = list(blocked)
        self.pending_fails = pending_fails
        self.blocked_fails = blocked_fails
        self.client = self

    def is_configured(self):
        return True

    def pending_items(self):
        return None if self.pending_fails else self.pending

    def blocked_items(self):
        return None if self.blocked_fails else self.blocked


def _list_item(title="標題", status="待處理", selected=True):
    return SelectedItem(
        page_id="p1",
        title=title,
        link="https://a.example/1",
        source="玩具人 寶可夢",
        category="文章",
        status=status,
        selected=selected,
    )


class TestListBlockedWarning:
    def _patch(self, monkeypatch, reader):
        monkeypatch.setattr("src.cli.NotionReader", lambda: reader)

    def test_warns_when_checked_item_is_not_pending(self, monkeypatch, capsys):
        """回歸測試：勾選了但狀態不是「待處理」的項目不會被撿走，
        以前完全沒有提示，使用者只會看到「沒有勾選待寫的項目」。"""
        reader = FakeListReader(blocked=[_list_item("卡住的", status=schema.STATUS_WRITING)])
        self._patch(monkeypatch, reader)

        assert cli.main(["list"]) == 0

        out = capsys.readouterr().out
        assert "卡住的" in out
        assert schema.STATUS_WRITING in out
        assert schema.STATUS_PENDING in out  # 要說明怎麼救

    def test_warning_shows_even_when_queue_is_empty(self, monkeypatch, capsys):
        """最關鍵的情況：佇列空的時候更需要這個提示。"""
        self._patch(monkeypatch, FakeListReader(pending=[], blocked=[_list_item("卡住的", status="已完成")]))

        assert cli.main(["list"]) == 0
        out = capsys.readouterr().out
        assert "目前沒有勾選待寫的項目" in out
        assert "卡住的" in out

    def test_no_warning_when_nothing_blocked(self, monkeypatch, capsys):
        self._patch(monkeypatch, FakeListReader(pending=[_list_item()], blocked=[]))

        assert cli.main(["list"]) == 0
        assert "不會被撿走" not in capsys.readouterr().out

    def test_blocked_query_failure_does_not_break_list(self, monkeypatch, capsys):
        """卡住項目只是附加資訊，查不到不該讓整個指令失敗。"""
        self._patch(monkeypatch, FakeListReader(pending=[_list_item()], blocked_fails=True))

        assert cli.main(["list"]) == 0
        assert "標題" in capsys.readouterr().out


class TestStaleArgValidation:
    """回歸測試：--stale 的邊界檢查要在解析階段就擋下來。"""

    def test_negative_exits_with_usage_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["notion-cleanup", "--stale", "-1"])
        assert exc.value.code == 2
        assert "至少 1 天" in capsys.readouterr().err

    def test_zero_exits_with_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["notion-cleanup", "--stale", "0"])
        assert exc.value.code == 2

    def test_positive_accepted(self):
        assert cli.build_parser().parse_args(["notion-cleanup", "--stale", "2"]).stale == 2

    def test_omitted_defaults_to_off(self):
        assert cli.build_parser().parse_args(["notion-cleanup"]).stale == 0
