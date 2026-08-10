import requests

from src.notifier import TelegramNotifier


class TestConfiguration:
    def test_not_configured_without_credentials(self):
        assert not TelegramNotifier(bot_token="", chat_id="").is_configured()

    def test_unconfigured_send_returns_false(self):
        assert TelegramNotifier(bot_token="", chat_id="").send_message("hi") is False


class TestEscaping:
    def test_escapes_html_special_chars(self):
        assert TelegramNotifier._escape_html("a & b <c>") == "a &amp; b &lt;c&gt;"

    def test_ampersand_escaped_first_no_double_escaping(self):
        assert TelegramNotifier._escape_html("<") == "&lt;"

    def test_link_is_escaped(self, monkeypatch):
        """回歸測試：舊版只跳脫標題與來源，連結中的 & 會讓 Telegram 回 400。"""
        captured = {}

        def fake_post(url, json, timeout):
            captured["text"] = json["text"]
            return _ok_response()

        monkeypatch.setattr(requests, "post", fake_post)

        TelegramNotifier(bot_token="t", chat_id="c").notify_new_item(
            title="標題",
            link="https://example.com/?a=1&b=2",
            source="來源",
        )

        assert "a=1&amp;b=2" in captured["text"]
        assert "a=1&b=2" not in captured["text"]


class TestSendFailures:
    def test_returns_false_on_request_exception(self, monkeypatch, capsys):
        def boom(*args, **kwargs):
            raise requests.ConnectionError("network down")

        monkeypatch.setattr(requests, "post", boom)

        result = TelegramNotifier(bot_token="t", chat_id="c").send_message("hi")

        assert result is False
        assert "[Error]" in capsys.readouterr().out

    def test_returns_false_on_http_error(self, monkeypatch):
        monkeypatch.setattr(requests, "post", lambda *a, **k: _error_response(400))
        assert TelegramNotifier(bot_token="t", chat_id="c").send_message("hi") is False

    def test_returns_true_on_success(self, monkeypatch):
        monkeypatch.setattr(requests, "post", lambda *a, **k: _ok_response())
        assert TelegramNotifier(bot_token="t", chat_id="c").send_message("hi") is True

    def test_error_output_never_leaks_bot_token(self, monkeypatch, capsys):
        """回歸測試：requests 的例外字串內含請求 URL（也就是 bot token），
        原樣印出會把 token 寫進 CI log。"""
        token = "123456789:SECRET-BOT-TOKEN"

        def boom(url, **kwargs):
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

        monkeypatch.setattr(requests, "post", boom)
        TelegramNotifier(bot_token=token, chat_id="c").send_message("hi")

        out = capsys.readouterr().out
        assert "[Error]" in out
        assert token not in out


class TestMessageFormat:
    def test_twitter_items_use_tweet_label(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            requests, "post", lambda url, json, timeout: (captured.update(json) or _ok_response())
        )

        TelegramNotifier(bot_token="t", chat_id="c").notify_new_item(
            title="推文內容", link="https://x.com/a/1", source="@a", source_type="twitter"
        )

        assert "新推文" in captured["text"]


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code}")
            error.response = self
            raise error


def _ok_response():
    return _Response(200)


def _error_response(status):
    return _Response(status)
