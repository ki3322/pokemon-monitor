import calendar
from datetime import datetime, timedelta, timezone

import pytest

from src.monitors import rss_monitor
from src.monitors.rss_monitor import get_rss_items, get_twitter_items, is_recent


def as_struct(dt):
    return dt.utctimetuple()


def entry(title="標題", link="https://example.com/1", guid=None, age_hours=0):
    published = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    data = {"title": title, "link": link, "published_parsed": as_struct(published)}
    if guid:
        data["id"] = guid
    return data


class FakeFeed:
    def __init__(self, entries):
        self.entries = entries


class TestIsRecent:
    def test_recent_entry_passes(self):
        assert is_recent(entry(age_hours=1), max_age_hours=24)

    def test_old_entry_filtered(self):
        assert not is_recent(entry(age_hours=48), max_age_hours=24)

    def test_missing_date_treated_as_new(self):
        assert is_recent({"title": "x"})

    def test_invalid_date_treated_as_new(self):
        assert is_recent({"published_parsed": "not a struct"})

    def test_falls_back_to_updated_parsed(self):
        published = datetime.now(timezone.utc) - timedelta(hours=1)
        assert is_recent({"updated_parsed": as_struct(published)}, max_age_hours=24)


class TestFetchFeed:
    def test_returns_none_when_http_fails(self, monkeypatch):
        monkeypatch.setattr(rss_monitor, "fetch", lambda url: None)
        assert rss_monitor.fetch_feed("https://x") is None

    def test_parses_valid_feed(self, monkeypatch):
        rss = (
            '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
            "<item><title>文章</title><link>https://a/1</link></item>"
            "</channel></rss>"
        )
        monkeypatch.setattr(rss_monitor, "fetch", lambda url: type("R", (), {"text": rss})())

        feed = rss_monitor.fetch_feed("https://x")

        assert len(feed.entries) == 1

    def test_unparsable_content_returns_none_with_reason(self, monkeypatch, capsys):
        """回歸測試：解析失敗要留下原因，不能無聲吞掉。"""
        monkeypatch.setattr(
            rss_monitor, "fetch", lambda url: type("R", (), {"text": "<<< not a feed"})()
        )

        assert rss_monitor.fetch_feed("https://x") is None
        assert "[Error]" in capsys.readouterr().out


class TestGetRssItems:
    def test_fetch_failure_reports_unsuccessful(self, monkeypatch):
        monkeypatch.setattr(rss_monitor, "fetch_feed", lambda url: None)

        items, success = get_rss_items({"name": "S", "url": "https://x"})

        assert items == []
        assert success is False

    def test_empty_feed_is_successful(self, monkeypatch):
        monkeypatch.setattr(rss_monitor, "fetch_feed", lambda url: FakeFeed([]))

        items, success = get_rss_items({"name": "S", "url": "https://x"})

        assert items == []
        assert success is True

    def test_old_entries_filtered_out(self, monkeypatch):
        monkeypatch.setattr(
            rss_monitor,
            "fetch_feed",
            lambda url: FakeFeed([entry(link="https://a/1", age_hours=1), entry(link="https://a/2", age_hours=100)]),
        )

        items, _ = get_rss_items({"name": "S", "url": "https://x"})

        assert [i.link for i in items] == ["https://a/1"]

    def test_id_ignores_title_changes(self, monkeypatch):
        """回歸測試：同一篇文章改標題後不可以變成新項目。"""
        source = {"name": "S", "url": "https://x"}

        monkeypatch.setattr(rss_monitor, "fetch_feed", lambda url: FakeFeed([entry(title="原標題")]))
        first, _ = get_rss_items(source)

        monkeypatch.setattr(rss_monitor, "fetch_feed", lambda url: FakeFeed([entry(title="改過的標題")]))
        second, _ = get_rss_items(source)

        assert first[0].id == second[0].id

    def test_entry_without_link_or_guid_is_skipped(self, monkeypatch):
        monkeypatch.setattr(rss_monitor, "fetch_feed", lambda url: FakeFeed([{"title": "無連結"}]))

        items, success = get_rss_items({"name": "S", "url": "https://x"})

        assert items == []
        assert success is True

    def test_guid_used_over_link_with_tracking_params(self, monkeypatch):
        source = {"name": "S", "url": "https://x"}

        monkeypatch.setattr(
            rss_monitor,
            "fetch_feed",
            lambda url: FakeFeed([entry(link="https://a/1?utm=a", guid="post-1")]),
        )
        first, _ = get_rss_items(source)

        monkeypatch.setattr(
            rss_monitor,
            "fetch_feed",
            lambda url: FakeFeed([entry(link="https://a/1?utm=b", guid="post-1")]),
        )
        second, _ = get_rss_items(source)

        assert first[0].id == second[0].id


class TestGetTwitterItems:
    def test_window_is_wide_enough_for_delayed_cron(self):
        """30 分鐘的 cron 常被延遲，1 小時視窗會漏推文。"""
        assert rss_monitor.TWITTER_MAX_AGE_HOURS >= 6

    def test_items_are_tagged_as_twitter(self, monkeypatch):
        monkeypatch.setattr(rss_monitor, "fetch_feed", lambda url: FakeFeed([entry()]))

        items, success = get_twitter_items("someone")

        assert success
        assert items[0].source == "@someone"
        assert items[0].source_type == "twitter"

    def test_fetch_failure_reports_unsuccessful(self, monkeypatch):
        monkeypatch.setattr(rss_monitor, "fetch_feed", lambda url: None)
        assert get_twitter_items("someone") == ([], False)

    def test_long_titles_truncated(self, monkeypatch):
        monkeypatch.setattr(
            rss_monitor, "fetch_feed", lambda url: FakeFeed([entry(title="長" * 300)])
        )

        items, _ = get_twitter_items("someone")

        assert len(items[0].title) == 100
