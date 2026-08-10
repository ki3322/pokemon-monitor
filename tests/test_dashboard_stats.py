from datetime import datetime

from src.dashboard.stats import (
    KIND_TWITTER,
    KIND_WEBSITE,
    Dashboard,
    DraftStat,
    GroupStat,
    NewsStat,
    build_drafts,
    build_groups,
    build_news,
)
from src.notion import schema
from src.notion.reader import SelectedItem
from src.state import MAX_ITEMS_PER_SOURCE

RSS = [{"name": "GO Hub", "url": "https://a.example/feed"}]
SCRAPE = [
    {"name": "Serebii.net", "url": "https://b.example"},
    {"name": "玩具人 寶可夢", "url": "https://c.example", "group": "玩具人"},
    {"name": "玩具人 寶可夢中心", "url": "https://d.example", "group": "玩具人"},
]
TWITTER = ["PokemonGoApp"]

DELIVERED = {
    "telegram": {"GO Hub": ["a", "b"], "玩具人": ["x"]},
    "notion": {"玩具人": ["x", "y", "z"]},
}


class TestBuildGroups:
    def test_shared_group_merged_into_one_entry(self):
        """回歸測試：共用 group 的來源已讀記錄是共用的，不該重複計算。"""
        groups = build_groups(RSS, SCRAPE, TWITTER, DELIVERED)
        toys = [g for g in groups if g.group == "玩具人"]
        assert len(toys) == 1
        assert toys[0].members == ("玩具人 寶可夢", "玩具人 寶可夢中心")

    def test_group_defaults_to_source_name(self):
        groups = build_groups(RSS, [], [], {})
        assert groups[0].group == "GO Hub"

    def test_twitter_group_id_matches_monitor(self):
        """main.py 用 twitter_<帳號> 當群組鍵，這裡必須一致才對得上記錄。"""
        groups = build_groups([], [], ["PokemonGoApp"], {})
        assert groups[0].group == "twitter_PokemonGoApp"
        assert groups[0].kind == KIND_TWITTER

    def test_counts_read_from_each_sink(self):
        groups = {g.group: g for g in build_groups(RSS, SCRAPE, TWITTER, DELIVERED)}
        assert groups["玩具人"].telegram == 1
        assert groups["玩具人"].notion == 3

    def test_missing_records_count_as_zero(self):
        groups = {g.group: g for g in build_groups(RSS, SCRAPE, TWITTER, DELIVERED)}
        assert groups["Serebii.net"].tracked == 0
        assert not groups["Serebii.net"].is_bootstrapped

    def test_config_order_preserved(self):
        groups = build_groups(RSS, SCRAPE, TWITTER, {})
        assert [g.group for g in groups] == [
            "GO Hub",
            "Serebii.net",
            "玩具人",
            "twitter_PokemonGoApp",
        ]

    def test_website_kind_assigned_to_rss_and_scrape(self):
        groups = build_groups(RSS, SCRAPE, [], {})
        assert all(g.kind == KIND_WEBSITE for g in groups)

    def test_malformed_delivered_does_not_crash(self):
        """狀態檔可能被手動編輯壞掉，儀表板不該因此爆掉。"""
        groups = build_groups(RSS, [], [], {"telegram": "not-a-dict"})
        assert groups[0].tracked == 0

    def test_group_initialized_with_zero_items_counts_as_bootstrapped(self):
        """回歸測試：初始化當下若沒有符合時間範圍的內容，會留下空清單。

        那已經初始化完成，下一輪就會正常投遞；判斷必須看鍵存不存在，
        看筆數會把它誤報成「待初始化」，使用者以為監控壞了。
        """
        groups = build_groups(RSS, [], [], {"telegram": {"GO Hub": []}})
        assert groups[0].tracked == 0
        assert groups[0].is_bootstrapped

    def test_group_absent_from_records_is_not_bootstrapped(self):
        groups = build_groups(RSS, [], [], {"telegram": {}})
        assert not groups[0].is_bootstrapped

    def test_initialization_tracked_per_sink(self):
        """新啟用的目的地要能看出自己還沒初始化，即使另一個已經有記錄。"""
        groups = build_groups(RSS, [], [], {"telegram": {"GO Hub": ["a"]}})
        assert groups[0].telegram_initialized
        assert not groups[0].notion_initialized


class TestGroupStat:
    def test_tracked_takes_larger_sink(self):
        assert GroupStat("g", KIND_WEBSITE, telegram=2, notion=5).tracked == 5

    def test_saturated_at_record_limit(self):
        assert GroupStat("g", KIND_WEBSITE, telegram=MAX_ITEMS_PER_SOURCE).is_saturated

    def test_not_saturated_below_limit(self):
        assert not GroupStat("g", KIND_WEBSITE, telegram=MAX_ITEMS_PER_SOURCE - 1).is_saturated


class TestBuildDrafts:
    def test_pairs_brief_and_article_by_slug(self):
        drafts = build_drafts(["abc.brief.md", "abc.article.md"])
        assert len(drafts) == 1
        assert drafts[0].has_brief and drafts[0].has_article

    def test_brief_without_article_is_writing(self):
        assert build_drafts(["abc.brief.md"])[0].status == "撰寫中"

    def test_article_present_is_done(self):
        assert build_drafts(["abc.brief.md", "abc.article.md"])[0].status == "已成稿"

    def test_unrelated_files_ignored(self):
        assert build_drafts(["dashboard.html", "notes.txt", ".DS_Store"]) == ()

    def test_sorted_by_slug(self):
        drafts = build_drafts(["b.brief.md", "a.brief.md"])
        assert [d.slug for d in drafts] == ["a", "b"]


class TestDashboard:
    def _dashboard(self):
        return Dashboard(
            generated_at="2026-08-10 09:00",
            state_version=3,
            groups=build_groups(RSS, SCRAPE, TWITTER, DELIVERED),
            drafts=(DraftStat("a", True, True), DraftStat("b", True, False)),
        )

    def test_totals_sum_across_groups(self):
        assert self._dashboard().total_tracked == 2 + 0 + 3 + 0

    def test_kind_partitions_are_disjoint_and_complete(self):
        dashboard = self._dashboard()
        assert len(dashboard.website_groups) + len(dashboard.twitter_groups) == len(dashboard.groups)

    def test_pending_groups_are_the_uninitialized_ones(self):
        pending = {g.group for g in self._dashboard().pending_groups}
        assert pending == {"Serebii.net", "twitter_PokemonGoApp"}

    def test_stage_counts(self):
        stages = {s.label: s.count for s in self._dashboard().stages}
        assert stages["監控來源"] == 4
        assert stages["Telegram 記錄"] == 3
        assert stages["Notion 記錄"] == 3
        assert stages["撰寫中"] == 1
        assert stages["已成稿"] == 1

    def test_empty_dashboard_is_all_zero(self):
        dashboard = Dashboard(generated_at="now")
        assert dashboard.total_tracked == 0
        assert all(s.count == 0 for s in dashboard.stages)


def _selected_item(title="標題", selected=False, status="待處理", found_at=""):
    return SelectedItem(
        page_id="p",
        title=title,
        link="https://a.example/1",
        source="Serebii.net",
        category="文章",
        status=status,
        selected=selected,
        found_at=found_at,
    )


NOW = datetime(2026, 8, 10, 12, 0)


class TestBuildNews:
    def test_maps_fields(self):
        news = build_news([_selected_item(found_at="2026-08-10T09:00:00")], now=NOW)

        assert len(news) == 1
        assert news[0].title == "標題"
        assert news[0].link == "https://a.example/1"
        assert news[0].source == "Serebii.net"
        assert news[0].status == "待處理"

    def test_freshness_buckets(self):
        def freshness(found_at):
            return build_news([_selected_item(found_at=found_at)], now=NOW)[0].freshness

        assert freshness("2026-08-10T01:00:00") == "🔥 今天"
        assert freshness("2026-08-08T12:00:00") == "🟡 3 天內"
        assert freshness("2026-08-04T12:00:00") == "⚪ 一週內"
        assert freshness("2026-07-01T12:00:00") == "🕓 較舊"
        assert freshness("") == "—"

    def test_yesterday_is_not_today(self):
        """回歸測試：Notion 公式的 <=1 會把昨天標成「今天」，網頁版要按日曆日算。"""
        assert build_news(
            [_selected_item(found_at="2026-08-09T23:00:00")], now=NOW
        )[0].freshness == "🟡 3 天內"

    def test_timezone_aware_found_at_handled(self):
        news = build_news([_selected_item(found_at="2026-08-10T02:31:00.000+00:00")], now=NOW)
        assert news[0].freshness in ("🔥 今天", "🟡 3 天內")  # 依本機時區可能落在昨天

    def test_unparsable_found_at_is_unknown(self):
        assert build_news([_selected_item(found_at="not-a-date")], now=NOW)[0].freshness == "—"


class TestNewsOnDashboard:
    def _dashboard(self):
        return Dashboard(
            generated_at="now",
            news=build_news(
                [
                    _selected_item(title="勾選待寫", selected=True, status="待處理"),
                    _selected_item(title="已完成的", selected=True, status=schema.STATUS_DONE),
                    _selected_item(title="沒勾的", selected=False, status="待處理"),
                    _selected_item(title="撰寫中的", selected=True, status=schema.STATUS_WRITING),
                ],
                now=NOW,
            ),
        )

    def test_queue_is_selected_and_not_done(self):
        assert [n.title for n in self._dashboard().queue] == ["勾選待寫", "撰寫中的"]

    def test_status_counts_follow_schema_order_and_skip_zero(self):
        assert self._dashboard().news_status_counts == (
            ("待處理", 2),
            (schema.STATUS_WRITING, 1),
            (schema.STATUS_DONE, 1),
        )

    def test_no_news_means_empty_queue(self):
        dashboard = Dashboard(generated_at="now")
        assert dashboard.news is None
        assert dashboard.queue == ()
        assert dashboard.news_status_counts == ()
