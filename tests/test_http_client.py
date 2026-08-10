import requests

from src import http_client
from src.http_client import fetch


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(str(self.status_code))
            error.response = self
            raise error


def patch_get(monkeypatch, side_effects):
    """依序回傳（或拋出）side_effects 中的項目，並記錄呼叫次數。"""
    calls = {"count": 0}

    def fake_get(url, headers, timeout):
        index = min(calls["count"], len(side_effects) - 1)
        calls["count"] += 1
        result = side_effects[index]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


class TestFetch:
    def test_returns_response_on_success(self, monkeypatch):
        patch_get(monkeypatch, [FakeResponse()])
        assert fetch("https://x").text == "ok"

    def test_retries_transient_failure_then_succeeds(self, monkeypatch):
        calls = patch_get(monkeypatch, [requests.ConnectionError("boom"), FakeResponse()])

        result = fetch("https://x", sleep=lambda s: None)

        assert result is not None
        assert calls["count"] == 2

    def test_gives_up_after_max_attempts(self, monkeypatch, capsys):
        calls = patch_get(monkeypatch, [requests.Timeout("slow")])

        result = fetch("https://x", max_attempts=3, sleep=lambda s: None)

        assert result is None
        assert calls["count"] == 3
        assert "[Error]" in capsys.readouterr().out

    def test_does_not_retry_client_errors(self, monkeypatch):
        """404/403 重試也不會變好，不該浪費時間。"""
        calls = patch_get(monkeypatch, [FakeResponse(status_code=404)])

        result = fetch("https://x", sleep=lambda s: None)

        assert result is None
        assert calls["count"] == 1

    def test_retries_rate_limit(self, monkeypatch):
        calls = patch_get(monkeypatch, [FakeResponse(status_code=429), FakeResponse()])

        fetch("https://x", sleep=lambda s: None)

        assert calls["count"] == 2

    def test_retries_server_errors(self, monkeypatch):
        calls = patch_get(monkeypatch, [FakeResponse(status_code=503), FakeResponse()])

        fetch("https://x", sleep=lambda s: None)

        assert calls["count"] == 2

    def test_backoff_grows_between_attempts(self, monkeypatch):
        waits = []
        patch_get(monkeypatch, [requests.ConnectionError("boom")])

        fetch("https://x", max_attempts=3, backoff=2, sleep=waits.append)

        assert waits == [2, 4]

    def test_default_backoff_constant_is_used(self):
        assert http_client.BACKOFF_SECONDS > 0
        assert http_client.MAX_ATTEMPTS >= 2
