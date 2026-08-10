from src.article.html import escape_attribute, escape_text, markdown_to_html


class TestEscaping:
    def test_escapes_text_nodes(self):
        assert escape_text("a & b <c>") == "a &amp; b &lt;c&gt;"

    def test_ampersand_escaped_first(self):
        assert escape_text("<") == "&lt;"

    def test_attribute_escapes_quotes(self):
        assert escape_attribute('a"b') == "a&quot;b"

    def test_title_text_is_escaped_in_output(self):
        html = markdown_to_html("## R&D <測試>")
        assert html == "<h2>R&amp;D &lt;測試&gt;</h2>"


class TestMarkdownToHtml:
    def test_headings(self):
        assert markdown_to_html("## 二階\n\n### 三階") == "<h2>二階</h2>\n<h3>三階</h3>"

    def test_paragraph(self):
        assert markdown_to_html("內文") == "<p>內文</p>"

    def test_bold_and_italic(self):
        assert markdown_to_html("**粗** 與 *斜*") == "<p><strong>粗</strong> 與 <em>斜</em></p>"

    def test_link(self):
        assert markdown_to_html("[寶可夢](https://a.example)") == (
            '<p><a href="https://a.example">寶可夢</a></p>'
        )

    def test_link_url_is_attribute_escaped(self):
        html = markdown_to_html("[x](https://a.example/?a=1&b=2)")
        assert 'href="https://a.example/?a=1&amp;b=2"' in html

    def test_consecutive_bullets_share_one_list(self):
        html = markdown_to_html("- 一\n- 二")
        assert html == "<ul>\n<li>一</li>\n<li>二</li>\n</ul>"
        assert html.count("<ul>") == 1

    def test_numbered_list_uses_ol(self):
        html = markdown_to_html("1. 一\n2. 二")
        assert html.startswith("<ol>") and html.endswith("</ol>")

    def test_switching_list_type_closes_previous(self):
        html = markdown_to_html("- 一\n\n1. 二")
        assert "</ul>" in html
        assert html.index("</ul>") < html.index("<ol>")

    def test_list_closed_before_heading(self):
        html = markdown_to_html("- 一\n\n## 標題")
        assert html.index("</ul>") < html.index("<h2>")

    def test_list_closed_at_end_of_document(self):
        assert markdown_to_html("- 一").endswith("</ul>")

    def test_h1_dropped_by_default(self):
        """WordPress 標題另外填，正文不該重複出現 H1。"""
        html = markdown_to_html("# 文章標題\n\n內文")
        assert "文章標題" not in html
        assert html == "<p>內文</p>"

    def test_h1_kept_when_requested(self):
        assert "文章標題" in markdown_to_html("# 文章標題\n\n內文", drop_title=False)

    def test_no_classes_or_styles_emitted(self):
        """輸出必須乾淨，樣式交給 WordPress 佈景主題。"""
        html = markdown_to_html("## 標題\n\n內文\n\n- 一\n\n> 引用")
        assert "class=" not in html
        assert "style=" not in html
        assert "<div" not in html

    def test_divider_and_quote(self):
        html = markdown_to_html("> 引用\n\n---")
        assert "<blockquote>引用</blockquote>" in html
        assert "<hr />" in html

    def test_full_article_shape(self):
        markdown = (
            "# 標題\n\n"
            "## 重點\n\n"
            "- 第一點\n"
            "- 第二點\n\n"
            "詳細說明含 **重點** 與 [連結](https://a.example)。\n"
        )
        html = markdown_to_html(markdown)
        assert html == (
            "<h2>重點</h2>\n"
            "<ul>\n<li>第一點</li>\n<li>第二點</li>\n</ul>\n"
            '<p>詳細說明含 <strong>重點</strong> 與 <a href="https://a.example">連結</a>。</p>'
        )


class TestTableHtml:
    TABLE = "| 項目 | 內容 |\n|---|---|\n| 售價 | 300 日圓 |"

    def test_renders_thead_and_tbody(self):
        html = markdown_to_html(self.TABLE)
        assert html == (
            "<table>\n<thead>\n<tr><th>項目</th><th>內容</th></tr>\n</thead>\n"
            "<tbody>\n<tr><td>售價</td><td>300 日圓</td></tr>\n</tbody>\n</table>"
        )

    def test_no_classes_on_table(self):
        assert "class=" not in markdown_to_html(self.TABLE)

    def test_cell_text_is_escaped(self):
        assert "&amp;" in markdown_to_html("| a |\n|---|\n| R&D |")

    def test_header_only_table_omits_tbody(self):
        assert "<tbody>" not in markdown_to_html("| a | b |\n|---|---|")
