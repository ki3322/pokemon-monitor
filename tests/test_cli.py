import os

import pytest

from src import cli
from src.article.brief import article_path, brief_path, build_brief, slug_for, write_brief
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
    def __init__(self, items):
        self.items = items
        self.client = type("C", (), {"is_configured": lambda self: True})()

    def pending_items(self):
        return self.items


class FakeWriter:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def publish(self, page_id, markdown, link="", wordpress_url="", replace=True):
        self.calls.append(
            {"page_id": page_id, "markdown": markdown, "link": link, "replace": replace}
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

    def test_explicit_link_used_without_lookup(self, monkeypatch, tmp_path, configured):
        writer = FakeWriter()
        monkeypatch.setattr(cli, "NotionWriter", lambda client: writer)

        cli.main([
            "publish", "p", "--file", self._article(tmp_path), "--link", "https://b.example",
        ])

        assert writer.calls[0]["link"] == "https://b.example"
