from src.article import extractor
from src.article.extractor import extract_content, fetch_content

LONG = "這是一段夠長的內文，用來通過最短長度檢查。" * 20


def page(body: str) -> str:
    return f"<html><body>{body}</body></html>"


class TestExtractContent:
    def test_prefers_entry_content(self):
        html = page(
            f'<nav>導覽列文字</nav><div class="entry-content"><p>{LONG}</p></div>'
        )
        content = extract_content(html)

        assert LONG[:20] in content
        assert "導覽列文字" not in content

    def test_falls_back_to_article_tag(self):
        assert LONG[:20] in extract_content(page(f"<article><p>{LONG}</p></article>"))

    def test_falls_back_to_body_when_no_container(self):
        assert LONG[:20] in extract_content(page(f"<p>{LONG}</p>"))

    def test_strips_scripts_and_styles(self):
        html = page(f"<script>alert('x')</script><style>.a{{}}</style><p>{LONG}</p>")
        content = extract_content(html)

        assert "alert" not in content
        assert ".a{" not in content

    def test_removes_share_widgets(self):
        html = page(
            f'<article><div class="share_button">分享到 Facebook 分享到 LINE</div>'
            f"<p>{LONG}</p></article>"
        )
        content = extract_content(html)

        assert "分享到 Facebook" not in content
        assert LONG[:20] in content

    def test_layout_class_containing_sidebar_is_kept(self):
        """回歸測試：`p-body-main--withSidebar` 是版面 class，誤刪會整段內文消失。"""
        html = page(f'<div class="p-body-main--withSidebar"><p>{LONG}</p></div>')
        assert LONG[:20] in extract_content(html)

    def test_body_class_containing_sidebar_is_kept(self):
        """回歸測試：body 帶 `-sidebar-on` 時，整個 body 曾被誤刪導致抽取到 0 字。"""
        html = f'<html><body class="wp-theme-swell -sidebar-on"><p>{LONG}</p></body></html>'
        assert LONG[:20] in extract_content(html)

    def test_large_noise_matching_element_is_kept(self):
        """疑似雜訊的元素若裝著大半頁面文字，那是版面容器，不能刪。"""
        html = page(f'<div class="related"><p>{LONG}</p></div>')
        assert LONG[:20] in extract_content(html)

    def test_small_noise_element_removed_alongside_content(self):
        html = page(
            f'<article><p>{LONG}</p><div class="related">相關文章連結</div></article>'
        )
        content = extract_content(html)

        assert "相關文章連結" not in content
        assert LONG[:20] in content

    def test_duplicated_paragraphs_collapsed(self):
        """回歸測試：不少網站把正文輸出兩次，重複會白白吃掉撰稿上下文。"""
        duplicated = "售價為每轉 300 日圓，預計 2026 年 8 月下旬發售。"
        html = page(f"<article><p>{LONG}</p><p>{duplicated}</p><p>{duplicated}</p></article>")

        assert extract_content(html).count(duplicated) == 1

    def test_distinct_paragraphs_all_kept(self):
        html = page(f"<article><p>{LONG}</p><p>第一段</p><p>第二段</p></article>")
        content = extract_content(html)

        assert "第一段" in content and "第二段" in content

    def test_short_container_skipped_for_longer_one(self):
        """內文容器抓到的內容太短時，應該退回更寬鬆的策略。"""
        html = page(f'<div class="entry-content">短</div><article><p>{LONG}</p></article>')
        assert LONG[:20] in extract_content(html)

    def test_paragraphs_separated_by_blank_lines(self):
        html = page(f"<article><p>{LONG}</p><p>第二段</p></article>")
        assert "\n\n第二段" in extract_content(html)

    def test_headings_retained(self):
        html = page(f"<article><h2>小標</h2><p>{LONG}</p></article>")
        assert "小標" in extract_content(html)

    def test_output_capped_at_max_length(self):
        html = page(f"<article><p>{'字' * 50000}</p></article>")
        assert len(extract_content(html)) <= extractor.MAX_CONTENT_LENGTH

    def test_empty_html(self):
        assert extract_content("<html></html>") == ""


class TestFetchContent:
    def test_returns_none_without_url(self):
        assert fetch_content("") is None

    def test_returns_none_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(extractor, "fetch", lambda url: None)
        assert fetch_content("https://x") is None

    def test_returns_extracted_text(self, monkeypatch):
        response = type("R", (), {"text": page(f"<article><p>{LONG}</p></article>")})()
        monkeypatch.setattr(extractor, "fetch", lambda url: response)

        assert LONG[:20] in fetch_content("https://x")

    def test_warns_when_content_is_short(self, monkeypatch, capsys):
        response = type("R", (), {"text": page("<p>太短</p>")})()
        monkeypatch.setattr(extractor, "fetch", lambda url: response)

        fetch_content("https://x")

        assert "[Warning]" in capsys.readouterr().out

    def test_empty_extraction_returns_none(self, monkeypatch):
        response = type("R", (), {"text": "<html></html>"})()
        monkeypatch.setattr(extractor, "fetch", lambda url: response)

        assert fetch_content("https://x") is None
