from src.article.markdown import Span, parse_markdown
from src.notion import blocks as nb


class TestChunkText:
    def test_short_text_single_chunk(self):
        assert nb.chunk_text("abc") == ["abc"]

    def test_empty_text_no_chunks(self):
        assert nb.chunk_text("") == []

    def test_long_text_split_at_limit(self):
        chunks = nb.chunk_text("a" * 4500, size=2000)
        assert [len(c) for c in chunks] == [2000, 2000, 500]

    def test_chunks_rejoin_to_original(self):
        text = "寶" * 3000
        assert "".join(nb.chunk_text(text)) == text


class TestRichText:
    def test_respects_notion_length_limit(self):
        """回歸測試：單一 rich_text 項目超過 2000 字元會被 Notion 拒絕。"""
        items = nb.rich_text("a" * 5000)
        assert all(len(i["text"]["content"]) <= nb.MAX_RICH_TEXT_LENGTH for i in items)

    def test_link_attached_to_every_chunk(self):
        items = nb.rich_text("a" * 3000, href="https://a.example")
        assert all(i["text"]["link"] == {"url": "https://a.example"} for i in items)

    def test_no_annotations_key_when_plain(self):
        assert "annotations" not in nb.rich_text("純文字")[0]


class TestRenderSpans:
    def test_bold_annotation(self):
        assert nb.render_spans([Span("粗", bold=True)])[0]["annotations"] == {"bold": True}

    def test_italic_and_code(self):
        items = nb.render_spans([Span("斜", italic=True), Span("c", code=True)])
        assert items[0]["annotations"] == {"italic": True}
        assert items[1]["annotations"] == {"code": True}

    def test_link_span(self):
        item = nb.render_spans([Span("連結", href="https://a.example")])[0]
        assert item["text"]["link"]["url"] == "https://a.example"


class TestRenderBlocks:
    def test_block_type_matches_key(self):
        block = nb.render_blocks(parse_markdown("## 標題"))[0]
        assert block["type"] == "heading_2"
        assert "heading_2" in block

    def test_divider_has_no_rich_text(self):
        block = nb.render_blocks(parse_markdown("---"))[0]
        assert block["divider"] == {}

    def test_list_items_render_individually(self):
        rendered = nb.render_blocks(parse_markdown("- 一\n- 二"))
        assert [b["type"] for b in rendered] == ["bulleted_list_item"] * 2


class TestCodeBlock:
    def test_language_and_content(self):
        block = nb.code_block("<p>hi</p>")
        assert block["code"]["language"] == "html"
        assert block["code"]["rich_text"][0]["text"]["content"] == "<p>hi</p>"

    def test_long_html_is_chunked(self):
        block = nb.code_block("<p>x</p>" * 1000)
        assert len(block["code"]["rich_text"]) > 1
        assert all(
            len(i["text"]["content"]) <= nb.MAX_RICH_TEXT_LENGTH
            for i in block["code"]["rich_text"]
        )


class TestBatched:
    def test_respects_request_limit(self):
        """回歸測試：Notion 單次最多附加 100 個區塊。"""
        batches = list(nb.batched([{"i": i} for i in range(250)]))
        assert [len(b) for b in batches] == [100, 100, 50]

    def test_empty_input_yields_nothing(self):
        assert list(nb.batched([])) == []

    def test_all_blocks_preserved_in_order(self):
        source = [{"i": i} for i in range(150)]
        flattened = [b for batch in nb.batched(source) for b in batch]
        assert flattened == source


class TestNotionTable:
    TABLE = "| 項目 | 內容 |\n|---|---|\n| 售價 | 300 日圓 |"

    def _block(self):
        return nb.render_blocks(parse_markdown(self.TABLE))[0]

    def test_table_width_matches_header(self):
        assert self._block()["table"]["table_width"] == 2

    def test_column_header_flagged(self):
        assert self._block()["table"]["has_column_header"] is True

    def test_every_row_has_table_width_cells(self):
        """回歸測試：Notion 會拒絕儲存格數量不一致的列。"""
        table = self._block()["table"]
        assert all(len(r["table_row"]["cells"]) == table["table_width"] for r in table["children"])

    def test_rows_are_table_row_blocks(self):
        assert all(r["type"] == "table_row" for r in self._block()["table"]["children"])
