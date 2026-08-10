from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.monitors import web_scraper
from src.monitors.web_scraper import (
    extract_title,
    find_scraper,
    get_scraped_items,
    scrape_pokemon_infomation,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")


@pytest.fixture
def infomation_page(monkeypatch):
    monkeypatch.setattr(
        web_scraper, "fetch_page", lambda url: load_fixture("pokemon_infomation.html")
    )


class TestExtractTitle:
    def test_prefers_inner_heading_over_full_text(self):
        """回歸測試：整張卡片的 get_text 會把更新日期與分類黏進標題。"""
        tag = BeautifulSoup(
            '<a href="/x"><h3>真正的標題</h3><time>2026-06-02</time><span>分類</span></a>',
            "html.parser",
        ).find("a")

        assert extract_title(tag) == "真正的標題"

    def test_falls_back_to_full_text_without_heading(self):
        tag = BeautifulSoup('<a href="/x">純文字標題</a>', "html.parser").find("a")
        assert extract_title(tag) == "純文字標題"

    def test_ignores_empty_heading(self):
        tag = BeautifulSoup('<a href="/x"><h3></h3>備援標題</a>', "html.parser").find("a")
        assert extract_title(tag) == "備援標題"


class TestScrapePokemonInfomation:
    def test_title_excludes_date_and_category(self, infomation_page):
        items, success = scrape_pokemon_infomation({"name": "PI", "url": "https://x"})

        assert success
        assert items[0].title == "【2026年最新】ポケモンカードの再販いつ？ 再販情報まとめ【ポケカ】"
        assert "2026-06-02" not in items[0].title
        assert "再販・抽選情報" not in items[0].title

    def test_excludes_navigation_and_category_links(self, infomation_page):
        items, _ = scrape_pokemon_infomation({"name": "PI", "url": "https://x"})
        links = [i.link for i in items]

        assert "https://pokemon-infomation.com/" not in links
        assert not any("/category/" in link for link in links)
        assert not any("/contact/" in link for link in links)

    def test_id_is_stable_when_title_changes(self, monkeypatch):
        """同一個 URL 更新日期後，ID 必須不變，才不會重複通知。"""
        source = {"name": "PI", "url": "https://x"}

        monkeypatch.setattr(
            web_scraper, "fetch_page", lambda url: load_fixture("pokemon_infomation.html")
        )
        first, _ = scrape_pokemon_infomation(source)

        edited = load_fixture("pokemon_infomation.html")
        # 換成一樣夠長的標題，避免被最短長度過濾掉而比對到不同文章
        edited.find("h3").string = "【2026年最新】ポケモンカードの再販いつ？ 内容が更新されました"
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: edited)
        second, _ = scrape_pokemon_infomation(source)

        assert first[0].id == second[0].id

    def test_fetch_failure_reports_unsuccessful(self, monkeypatch):
        """回歸測試：抓取失敗必須與「沒有新內容」區分開來。"""
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: None)

        items, success = scrape_pokemon_infomation({"name": "PI", "url": "https://x"})

        assert items == []
        assert success is False


class TestScrapeSerebii:
    @pytest.fixture(autouse=True)
    def page(self, monkeypatch):
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: load_fixture("serebii.html"))

    def test_relative_links_made_absolute(self):
        items, success = web_scraper.scrape_serebii({"name": "S", "url": "https://x"})

        assert success
        assert items[0].link == "https://www.serebii.net/news/2026/09-August-2026.shtml"

    def test_absolute_links_left_alone(self):
        items, _ = web_scraper.scrape_serebii({"name": "S", "url": "https://x"})
        assert items[2].link == "https://www.serebii.net/news/2026/07-August-2026.shtml"

    def test_headings_without_usable_link_skipped(self):
        items, _ = web_scraper.scrape_serebii({"name": "S", "url": "https://x"})
        assert len(items) == 3

    def test_daily_digest_id_stable_as_headline_grows(self):
        """Serebii 的當日標題會整天累加，同一天只能通知一次。"""
        source = {"name": "S", "url": "https://x"}
        first, _ = web_scraper.scrape_serebii(source)

        assert first[0].id == web_scraper.generate_item_id(first[0].link)

    def test_fetch_failure_reports_unsuccessful(self, monkeypatch):
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: None)
        assert web_scraper.scrape_serebii({"name": "S", "url": "https://x"}) == ([], False)


class TestScrapePokebeach:
    @pytest.fixture(autouse=True)
    def page(self, monkeypatch):
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: load_fixture("pokebeach.html"))

    def test_only_entry_title_articles_collected(self):
        items, success = web_scraper.scrape_pokebeach({"name": "PB", "url": "https://x"})

        assert success
        assert [i.title for i in items] == [
            "Meowth and Its Illustration Rare",
            "2027 Exclusive Regionals Merchandise",
        ]

    def test_fetch_failure_reports_unsuccessful(self, monkeypatch):
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: None)
        assert web_scraper.scrape_pokebeach({"name": "PB", "url": "https://x"}) == ([], False)


class TestScrapeToyPeople:
    @pytest.fixture(autouse=True)
    def page(self, monkeypatch):
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: load_fixture("toy_people.html"))

    def test_relative_links_made_absolute(self):
        items, success = web_scraper.scrape_toy_people({"name": "TP", "url": "https://x"})

        assert success
        assert items[0].link == "https://www.toy-people.com/?p=112961"

    def test_malformed_cards_skipped(self):
        items, _ = web_scraper.scrape_toy_people({"name": "TP", "url": "https://x"})
        assert len(items) == 2

    def test_same_article_from_both_tags_shares_one_id(self):
        """兩個標籤頁的重疊文章 URL 相同，ID 也必須相同才能去重。"""
        from_tag_a, _ = web_scraper.scrape_toy_people({"name": "玩具人 寶可夢", "url": "https://x"})
        from_tag_b, _ = web_scraper.scrape_toy_people({"name": "玩具人 寶可夢中心", "url": "https://y"})

        assert from_tag_a[0].id == from_tag_b[0].id

    def test_fetch_failure_reports_unsuccessful(self, monkeypatch):
        monkeypatch.setattr(web_scraper, "fetch_page", lambda url: None)
        assert web_scraper.scrape_toy_people({"name": "TP", "url": "https://x"}) == ([], False)


class TestFetchPage:
    def test_returns_none_when_http_fails(self, monkeypatch):
        monkeypatch.setattr(web_scraper, "fetch", lambda url: None)
        assert web_scraper.fetch_page("https://x") is None

    def test_parses_html_on_success(self, monkeypatch):
        class R:
            text = "<html><h1>hi</h1></html>"

        monkeypatch.setattr(web_scraper, "fetch", lambda url: R())

        assert web_scraper.fetch_page("https://x").find("h1").get_text() == "hi"


class TestDispatch:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.serebii.net/index2.shtml",
            "https://pokemon-infomation.com/",
            "https://www.pokebeach.com/",
            "https://www.toy-people.com/?tag=x",
        ],
    )
    def test_known_domains_have_scrapers(self, url):
        assert find_scraper(url) is not None

    def test_unknown_domain_has_no_scraper(self):
        assert find_scraper("https://unknown.example/") is None

    def test_unknown_domain_raises_instead_of_silently_returning_empty(self):
        """回歸測試：設定錯誤不可以無聲讓該來源永遠不被監控。"""
        with pytest.raises(ValueError, match="沒有對應的爬蟲"):
            get_scraped_items({"name": "X", "url": "https://unknown.example/"})


class TestConfiguredSources:
    def test_every_configured_source_is_handled(self):
        from config import SCRAPE_SOURCES

        unhandled = [s["url"] for s in SCRAPE_SOURCES if find_scraper(s["url"]) is None]
        assert unhandled == []
