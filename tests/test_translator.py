import pytest
import requests

from src import translator
from src.translator import translate_title


class FakeResponse:
    def __init__(self, payload=None, status=200, json_error=None):
        self._payload = payload
        self.status_code = status
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


def fake_get(response=None, error=None, calls=None):
    def get(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        if error:
            raise error
        return response

    return get


def google_payload(*segments):
    """Google 翻譯回傳的形狀：第一層第 0 項是各句的 [譯文, 原文, ...]。"""
    return [[[translated, "source", None, None, 3] for translated in segments], None, "en"]


class TestTranslateTitle:
    def test_returns_translation(self):
        get = fake_get(FakeResponse(google_payload("翻譯後")))
        assert translate_title("original", get=get) == "翻譯後"

    def test_joins_multi_sentence_translation(self):
        """長標題會被拆成多句回傳，必須全部接回來，不能只取第一句。"""
        get = fake_get(FakeResponse(google_payload("第一句。", "第二句。")))
        assert translate_title("One. Two.", get=get) == "第一句。第二句。"

    def test_strips_zero_width_characters(self):
        """Google 會在中文譯文裡夾零寬空白，留著會讓 Notion 搜尋與比對失準。"""
        get = fake_get(FakeResponse(google_payload("活動下​​週開始")))
        assert translate_title("Event next week", get=get) == "活動下週開始"

    def test_requests_traditional_chinese(self):
        calls = []
        get = fake_get(FakeResponse(google_payload("譯文")), calls=calls)

        translate_title("original", get=get)

        (url, kwargs), = calls
        assert url == translator.ENDPOINT
        assert kwargs["params"]["tl"] == "zh-TW"
        assert kwargs["params"]["q"] == "original"
        assert kwargs["timeout"] > 0

    def test_empty_input_returned_as_is(self):
        get = fake_get(error=AssertionError("should not call the service"))
        assert translate_title("", get=get) == ""

    @pytest.mark.parametrize(
        "get",
        [
            fake_get(error=requests.ConnectionError("network down")),
            fake_get(FakeResponse(status=429)),
            fake_get(FakeResponse(json_error=ValueError("not json"))),
        ],
        ids=["network", "http-429", "bad-json"],
    )
    def test_falls_back_to_original_on_error(self, get, capsys):
        """翻譯服務不穩定不可以中斷整輪監控。"""
        assert translate_title("original", get=get) == "original"
        assert "[Warning]" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "payload",
        [None, [], [None], [[]], [[["", "source"]]], {"unexpected": "shape"}],
        ids=["none", "empty", "no-segments", "empty-segments", "blank", "dict"],
    )
    def test_falls_back_when_translation_is_unusable(self, payload):
        get = fake_get(FakeResponse(payload))
        assert translate_title("original", get=get) == "original"
