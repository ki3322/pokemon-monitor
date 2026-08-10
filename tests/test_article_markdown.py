from src.article.markdown import (
    Span,
    extract_title,
    parse_inline,
    parse_markdown,
    strip_title,
)


class TestParseInline:
    def test_plain_text(self):
        assert parse_inline("純文字") == (Span("純文字"),)

    def test_bold(self):
        assert parse_inline("**重點**") == (Span("重點", bold=True),)

    def test_italic(self):
        assert parse_inline("*強調*") == (Span("強調", italic=True),)

    def test_bold_not_parsed_as_double_italic(self):
        """回歸測試：** 必須先於 * 比對，否則粗體會被拆成兩個斜體。"""
        assert parse_inline("**粗體**") == (Span("粗體", bold=True),)

    def test_inline_code(self):
        assert parse_inline("`code`") == (Span("code", code=True),)

    def test_link(self):
        assert parse_inline("[寶可夢](https://a.example)") == (
            Span("寶可夢", href="https://a.example"),
        )

    def test_mixed_content_keeps_order(self):
        spans = parse_inline("前 **粗** 中 [連結](https://x) 後")
        assert [s.text for s in spans] == ["前 ", "粗", " 中 ", "連結", " 後"]
        assert spans[1].bold
        assert spans[3].href == "https://x"

    def test_code_wins_over_inner_symbols(self):
        """程式碼內的 * 不該被當成斜體。"""
        assert parse_inline("`a*b*c`") == (Span("a*b*c", code=True),)

    def test_empty_spans_dropped(self):
        assert parse_inline("") == ()


class TestParseMarkdown:
    def test_headings_map_to_notion_levels(self):
        blocks = parse_markdown("## 二階\n### 三階")
        assert [b.kind for b in blocks] == ["heading_2", "heading_3"]

    def test_paragraph_lines_joined(self):
        blocks = parse_markdown("第一行\n第二行")
        assert len(blocks) == 1
        assert blocks[0].spans[0].text == "第一行 第二行"

    def test_blank_line_separates_paragraphs(self):
        blocks = parse_markdown("段一\n\n段二")
        assert [b.kind for b in blocks] == ["paragraph", "paragraph"]

    def test_bulleted_list(self):
        blocks = parse_markdown("- 一\n- 二")
        assert [b.kind for b in blocks] == ["bulleted_list_item"] * 2

    def test_numbered_list(self):
        blocks = parse_markdown("1. 一\n2. 二")
        assert [b.kind for b in blocks] == ["numbered_list_item"] * 2

    def test_quote_and_divider(self):
        blocks = parse_markdown("> 引用\n\n---")
        assert [b.kind for b in blocks] == ["quote", "divider"]

    def test_divider_not_confused_with_bullet(self):
        """--- 是分隔線，- 開頭才是清單。"""
        assert parse_markdown("---")[0].kind == "divider"
        assert parse_markdown("- 項目")[0].kind == "bulleted_list_item"

    def test_paragraph_flushed_before_heading(self):
        blocks = parse_markdown("段落\n## 標題")
        assert [b.kind for b in blocks] == ["paragraph", "heading_2"]

    def test_empty_input(self):
        assert parse_markdown("") == []


class TestTitle:
    def test_extract_h1(self):
        assert extract_title("# 標題\n\n內文") == "標題"

    def test_extract_returns_empty_without_h1(self):
        assert extract_title("## 只有 H2") == ""

    def test_h2_not_mistaken_for_title(self):
        assert extract_title("## 二階標題") == ""

    def test_strip_removes_only_h1(self):
        assert strip_title("# 標題\n\n## 二階\n內文") == "## 二階\n內文"

    def test_strip_is_noop_without_h1(self):
        assert strip_title("## 二階") == "## 二階"


TABLE_MD = "| 項目 | 內容 |\n|---|---|\n| 售價 | 300 日圓 |\n| 發售 | 2026 年 8 月 |"


class TestTable:
    def test_parsed_as_table_block(self):
        blocks = parse_markdown(TABLE_MD)
        assert [b.kind for b in blocks] == ["table"]

    def test_header_and_rows_captured(self):
        table = parse_markdown(TABLE_MD)[0]
        assert table.has_header
        assert len(table.rows) == 3
        assert table.rows[0][0][0].text == "項目"
        assert table.rows[1][1][0].text == "300 日圓"

    def test_separator_not_mistaken_for_divider(self):
        """回歸測試：|---|---| 也符合分隔線樣式，表格必須先判斷。"""
        assert "divider" not in [b.kind for b in parse_markdown(TABLE_MD)]

    def test_short_rows_padded_to_header_width(self):
        """Notion 要求每列寬度一致。"""
        table = parse_markdown("| a | b |\n|---|---|\n| only |")[0]
        assert all(len(row) == 2 for row in table.rows)

    def test_long_rows_truncated_to_header_width(self):
        table = parse_markdown("| a | b |\n|---|---|\n| 1 | 2 | 3 |")[0]
        assert all(len(row) == 2 for row in table.rows)

    def test_inline_styles_work_inside_cells(self):
        table = parse_markdown("| a |\n|---|\n| **粗** |")[0]
        assert table.rows[1][0][0].bold

    def test_content_after_table_still_parsed(self):
        blocks = parse_markdown(TABLE_MD + "\n\n## 之後的標題")
        assert [b.kind for b in blocks] == ["table", "heading_2"]

    def test_pipe_line_without_separator_is_paragraph(self):
        assert parse_markdown("| 這不是表格 |")[0].kind == "paragraph"
