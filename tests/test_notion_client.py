import pytest
import requests

from src.notion.client import NOTION_VERSION, NotionClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(str(self.status_code))
            error.response = self
            raise error


def patch_request(monkeypatch, responses):
    """依序回傳 responses；記錄每次呼叫的參數。"""
    calls = []

    def fake_request(method, url, headers, json, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "json": json})
        result = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(requests, "request", fake_request)
    return calls


@pytest.fixture
def client():
    return NotionClient(token="secret_x", database_id="db-1")


class TestConfiguration:
    def test_not_configured_without_credentials(self):
        assert not NotionClient(token="", database_id="").is_configured()

    def test_not_configured_without_database(self):
        assert not NotionClient(token="t", database_id="").is_configured()

    def test_has_token_ignores_database(self):
        """setup 腳本要建立資料庫，此時還沒有 database_id。"""
        assert NotionClient(token="t", database_id="").has_token()

    def test_configured_with_both(self, client):
        assert client.is_configured()


class TestHeaders:
    def test_sends_auth_and_version(self, client, monkeypatch):
        calls = patch_request(monkeypatch, [FakeResponse(payload={"id": "p"})])
        client.retrieve_page("p")

        headers = calls[0]["headers"]
        assert headers["Authorization"] == "Bearer secret_x"
        assert headers["Notion-Version"] == NOTION_VERSION


class TestErrorHandling:
    def test_http_error_returns_none_and_logs(self, client, monkeypatch, capsys):
        patch_request(monkeypatch, [FakeResponse(status_code=400, text="validation error")])

        assert client.create_page({}) is None
        out = capsys.readouterr().out
        assert "[Error]" in out
        assert "validation error" in out

    def test_connection_error_returns_none(self, client, monkeypatch, capsys):
        patch_request(monkeypatch, [requests.ConnectionError("down")])

        assert client.retrieve_page("p") is None
        assert "[Error]" in capsys.readouterr().out

    def test_append_blocks_reports_false_on_failure(self, client, monkeypatch):
        patch_request(monkeypatch, [FakeResponse(status_code=500)])
        assert client.append_blocks("p", [{"x": 1}]) is False

    def test_delete_block_reports_false_on_failure(self, client, monkeypatch):
        patch_request(monkeypatch, [FakeResponse(status_code=404)])
        assert client.delete_block("b") is False


class TestQueryDatabase:
    def test_returns_results(self, client, monkeypatch):
        patch_request(
            monkeypatch,
            [FakeResponse(payload={"results": [{"id": "a"}], "has_more": False})],
        )
        assert client.query_database() == [{"id": "a"}]

    def test_follows_pagination(self, client, monkeypatch):
        """回歸測試：不翻頁會靜默漏掉第 100 筆之後的項目。"""
        calls = patch_request(
            monkeypatch,
            [
                FakeResponse(payload={"results": [{"id": "a"}], "has_more": True, "next_cursor": "c1"}),
                FakeResponse(payload={"results": [{"id": "b"}], "has_more": False}),
            ],
        )

        assert client.query_database() == [{"id": "a"}, {"id": "b"}]
        assert calls[1]["json"]["start_cursor"] == "c1"

    def test_includes_filter_when_given(self, client, monkeypatch):
        calls = patch_request(monkeypatch, [FakeResponse(payload={"results": []})])
        client.query_database({"property": "x", "checkbox": {"equals": True}})

        assert calls[0]["json"]["filter"]["property"] == "x"

    def test_includes_sorts_when_given(self, client, monkeypatch):
        calls = patch_request(monkeypatch, [FakeResponse(payload={"results": []})])
        client.query_database(sorts=[{"property": "發現時間", "direction": "descending"}])

        assert calls[0]["json"]["sorts"][0]["property"] == "發現時間"

    def test_limit_stops_pagination_early(self, client, monkeypatch):
        """儀表板只要最近 N 筆，不該為了翻完整個資料庫打一堆請求。"""
        calls = patch_request(
            monkeypatch,
            [
                FakeResponse(
                    payload={"results": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "has_more": True, "next_cursor": "c1"}
                ),
            ],
        )

        assert client.query_database(limit=2) == [{"id": "a"}, {"id": "b"}]
        assert len(calls) == 1

    def test_returns_none_on_mid_pagination_failure(self, client, monkeypatch):
        """回歸測試：翻頁途中失敗不可回傳半套結果——呼叫端會把
        「不完整」誤判成「就這麼多」（例如回填時漏掉後半的項目）。"""
        patch_request(
            monkeypatch,
            [
                FakeResponse(payload={"results": [{"id": "a"}], "has_more": True, "next_cursor": "c1"}),
                FakeResponse(status_code=500),
            ],
        )
        assert client.query_database() is None

    def test_returns_none_on_failure(self, client, monkeypatch):
        patch_request(monkeypatch, [FakeResponse(status_code=500)])
        assert client.query_database() is None


class TestListChildren:
    def test_follows_pagination(self, client, monkeypatch):
        calls = patch_request(
            monkeypatch,
            [
                FakeResponse(payload={"results": [{"id": "b1"}], "has_more": True, "next_cursor": "c1"}),
                FakeResponse(payload={"results": [{"id": "b2"}], "has_more": False}),
            ],
        )

        assert client.list_children("p") == [{"id": "b1"}, {"id": "b2"}]
        assert "start_cursor=c1" in calls[1]["url"]

    def test_returns_none_on_failure(self, client, monkeypatch):
        """回歸測試：清除頁面前的讀取失敗必須被辨識出來，
        否則 clear_page 會「刪掉零個區塊」後回報成功，內容疊成兩份。"""
        patch_request(monkeypatch, [FakeResponse(status_code=500)])
        assert client.list_children("p") is None

    def test_returns_none_on_mid_pagination_failure(self, client, monkeypatch):
        patch_request(
            monkeypatch,
            [
                FakeResponse(payload={"results": [{"id": "b1"}], "has_more": True, "next_cursor": "c1"}),
                FakeResponse(status_code=500),
            ],
        )
        assert client.list_children("p") is None


class TestPageOperations:
    def test_create_page_targets_database(self, client, monkeypatch):
        calls = patch_request(monkeypatch, [FakeResponse(payload={"id": "p"})])
        client.create_page({"標題": {}})

        assert calls[0]["json"]["parent"] == {"database_id": "db-1"}

    def test_create_page_omits_children_when_empty(self, client, monkeypatch):
        calls = patch_request(monkeypatch, [FakeResponse(payload={"id": "p"})])
        client.create_page({}, [])

        assert "children" not in calls[0]["json"]

    def test_update_page_uses_patch(self, client, monkeypatch):
        calls = patch_request(monkeypatch, [FakeResponse(payload={"id": "p"})])
        client.update_page("p", {"狀態": {}})

        assert calls[0]["method"] == "PATCH"

    def test_create_database_targets_parent_page(self, client, monkeypatch):
        calls = patch_request(monkeypatch, [FakeResponse(payload={"id": "db"})])
        client.create_database("parent-1", "標題", {"名稱": {"title": {}}})

        assert calls[0]["json"]["parent"] == {"type": "page_id", "page_id": "parent-1"}
