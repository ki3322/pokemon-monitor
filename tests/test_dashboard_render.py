import re

from src.dashboard import theme
from src.dashboard.css import stylesheet
from src.dashboard.render import render_page, tilt
from src.dashboard.stats import Dashboard, DraftStat, GroupStat, KIND_TWITTER, KIND_WEBSITE, NewsStat
from src.state import MAX_ITEMS_PER_SOURCE, STATE_VERSION

NEWS = (
    NewsStat(
        title="皮卡丘新聞",
        link="https://news.example/pikachu?a=1&b=2",
        source="Serebii.net",
        status="待處理",
        selected=True,
        days_old=0,
    ),
    NewsStat(
        title="伊布新聞",
        link="https://news.example/eevee",
        source="PokeBeach",
        status="已完成",
        selected=True,
        days_old=5,
    ),
)

DASHBOARD = Dashboard(
    generated_at="2026-08-10 09:00",
    state_version=STATE_VERSION,
    notion_configured=True,
    groups=(
        GroupStat("Serebii.net", KIND_WEBSITE, ("Serebii.net",), telegram=42, notion=40),
        GroupStat("玩具人", KIND_WEBSITE, ("玩具人 寶可夢", "玩具人 寶可夢中心"), telegram=14),
        GroupStat("twitter_PokemonGoApp", KIND_TWITTER, ("@PokemonGoApp",)),
    ),
    drafts=(DraftStat("3b8d2e5bf409", True, True),),
    news=NEWS,
)


class TestThemeTokens:
    def test_brand_colors_present(self):
        css = stylesheet()
        assert "--bg: #FFC900;" in css
        assert "--ink: #000000;" in css
        assert "--muted: #7A7A7A;" in css

    def test_type_scale_matches_pack(self):
        css = stylesheet()
        assert "--type-display: 123px;" in css
        assert "--type-h1: 34px;" in css
        assert "--type-body: 26px;" in css
        assert "--type-small: 9px;" in css

    def test_radius_and_border_match_pack(self):
        css = stylesheet()
        assert "--radius-md: 17px;" in css
        assert "--radius-pill: 429px;" in css
        assert "--border: 1px solid black;" in css

    def test_motion_tokens_match_pack(self):
        css = stylesheet()
        assert "--duration-medium: 600ms;" in css
        assert "cubic-bezier(0.19, 1, 0.22, 1)" in css

    def test_spacing_scale_emitted(self):
        css = stylesheet()
        assert all(f"--space-{step}: {step}px;" in css for step in theme.SPACING_SCALE)


class TestForbiddenPatterns:
    """禁用清單的可自動檢查項目。"""

    CSS = stylesheet()

    def test_no_white_or_dark_page_background(self):
        body = self.CSS.split("body {")[1].split("}")[0]
        assert "background: var(--bg);" in body

    def test_no_serif_fonts(self):
        assert "serif" not in theme.FONT_STACK.replace("sans-serif", "")

    def test_no_shadows(self):
        """spec 的 shadows 是空陣列：深度只靠邊框與重疊。"""
        assert theme.SHADOWS == ()
        assert "box-shadow" not in self.CSS

    def test_no_sharp_corners_on_containers(self):
        assert "border-radius: 0" not in self.CSS

    def test_reduced_motion_respected(self):
        assert "prefers-reduced-motion" in self.CSS


class TestRenderPage:
    HTML = render_page(DASHBOARD)

    def test_is_self_contained(self):
        """發布環境會擋外部資源，頁面必須零外部依賴。

        新聞列表的 <a href> 是使用者點了才開的連結，不算外部資源；
        擋的是頁面載入時就會抓的東西（樣式、字型、腳本、圖片）。
        """
        assert "<style>" in self.HTML
        assert "<link" not in self.HTML
        assert "<script" not in self.HTML
        without_anchors = re.sub(r'href="[^"]*"', "", self.HTML)
        assert "https://" not in without_anchors

    def test_has_lang_and_viewport(self):
        assert 'lang="zh-Hant"' in self.HTML
        assert 'name="viewport"' in self.HTML

    def test_hero_shows_total(self):
        assert '<div class="hero__figure">56<' in self.HTML

    def test_group_names_rendered(self):
        assert "Serebii.net" in self.HTML
        assert "玩具人 寶可夢中心" in self.HTML

    def test_twitter_group_prefix_stripped_for_display(self):
        assert "twitter_PokemonGoApp" not in self.HTML
        assert "@PokemonGoApp" in self.HTML

    def test_uninitialized_group_flagged(self):
        assert "待初始化" in self.HTML

    def test_draft_status_rendered(self):
        assert "3b8d2e5bf409" in self.HTML
        assert "已成稿" in self.HTML

    def test_design_pack_credited(self):
        assert "Antoniouve" in self.HTML
        assert theme.PACK_URL in self.HTML

    def test_news_queue_section_lists_pending_items(self):
        assert "待撰稿佇列" in self.HTML
        assert "皮卡丘新聞" in self.HTML

    def test_done_item_not_in_queue_but_in_recent_list(self):
        assert "最近新聞" in self.HTML
        assert "伊布新聞" in self.HTML  # 已完成：只出現在最近新聞
        assert self.HTML.index("伊布新聞") > self.HTML.index("最近新聞")

    def test_news_title_links_to_source(self):
        assert 'href="https://news.example/pikachu?a=1&amp;b=2"' in self.HTML

    def test_status_counts_in_note(self):
        assert "待處理 1" in self.HTML
        assert "已完成 1" in self.HTML


    def test_bar_width_is_proportional(self):
        widths = re.findall(r'bar__fill[^"]*" style="width:(\d+)%', self.HTML)
        assert "42" in widths  # Serebii 42/100
        assert "14" in widths  # 玩具人 14/100

    def test_bar_never_exceeds_full_width(self):
        html = render_page(
            Dashboard("now", groups=(GroupStat("g", KIND_WEBSITE, telegram=MAX_ITEMS_PER_SOURCE * 3),))
        )
        assert "width:100%" in html
        assert "width:300%" not in html


class TestNewsUnavailable:
    def test_unconfigured_notion_explained(self):
        html = render_page(Dashboard("now", notion_configured=False, news=None))
        assert "Notion 未設定" in html
        assert "待撰稿佇列" not in html

    def test_query_failure_explained(self):
        """回歸測試：查詢失敗與未設定要顯示不同訊息，使用者才知道要修什麼。"""
        html = render_page(Dashboard("now", notion_configured=True, news=None))
        assert "查詢失敗" in html

    def test_configured_but_empty_database(self):
        html = render_page(Dashboard("now", notion_configured=True, news=()))
        assert "待撰稿佇列" in html
        assert "沒有勾選待寫的項目" in html


class TestEscaping:
    def test_group_name_is_escaped(self):
        html = render_page(
            Dashboard("now", groups=(GroupStat("<script>x</script>", KIND_WEBSITE),))
        )
        assert "<script>" not in html

    def test_news_title_is_escaped(self):
        news = (
            NewsStat(
                title="<script>x</script>",
                link="",
                source="來源",
                status="待處理",
                selected=True,
                days_old=0,
            ),
        )
        html = render_page(Dashboard("now", news=news))
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_draft_slug_is_escaped(self):
        html = render_page(Dashboard("now", drafts=(DraftStat("a<b>&c", True),)))
        assert "a&lt;b&gt;&amp;c" in html


class TestEmptyStates:
    HTML = render_page(Dashboard("2026-08-10 09:00"))

    def test_renders_without_data(self):
        assert "<html" in self.HTML

    def test_empty_sections_explain_themselves(self):
        # 網站來源、Twitter、稿件，加上 Notion 新聞的未設定說明
        assert self.HTML.count('class="empty"') == 4

    def test_notion_unconfigured_flagged(self):
        assert "Notion 未設定" in self.HTML


class TestStateVersionWarning:
    def test_legacy_state_warns_about_reinitialization(self):
        html = render_page(Dashboard("now", state_version=1))
        assert "狀態 v1 → 下一輪重新初始化" in html

    def test_missing_version_reads_as_legacy_not_none(self):
        """回歸測試：v1 狀態檔沒有 version 欄位，不能印成「vNone」。"""
        html = render_page(Dashboard("now", state_version=None))
        assert "None" not in html
        assert "狀態 舊格式 → 下一輪重新初始化" in html

    def test_current_version_shows_no_warning(self):
        html = render_page(Dashboard("now", state_version=STATE_VERSION))
        assert "重新初始化" not in html


class TestTilt:
    def test_is_deterministic(self):
        """散佈感不能靠亂數，否則每次輸出都不同、也無法測試。"""
        assert [tilt(i) for i in range(8)] == [tilt(i) for i in range(8)]

    def test_cycles_through_sequence(self):
        assert tilt(0) == tilt(8)

    def test_stays_subtle(self):
        assert all(abs(tilt(i)) <= 2.0 for i in range(20))
