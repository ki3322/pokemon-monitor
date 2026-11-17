import pytest
import requests

from src import translator
from src.translator import detect_language, split_for_limit, translate_title


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


class FakeGet:
    """依網址回應：值可以是 FakeResponse、例外，或接收 params 的函式。"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        route = self.routes.get(url)
        if route is None:
            raise AssertionError(f"unexpected request to {url}")
        if isinstance(route, Exception):
            raise route
        return route(kwargs.get("params", {})) if callable(route) else route

    def calls_to(self, url):
        return [kwargs for called, kwargs in self.calls if called == url]


def mymemory_payload(text, status=200, quota_finished=False):
    return {
        "responseData": {"translatedText": text},
        "responseStatus": status,
        "quotaFinished": quota_finished,
    }


def google_payload(*segments):
    """Google 翻譯回傳的形狀：第一層第 0 項是各句的 [譯文, 原文, ...]。"""
    return [[[translated, "source", None, None, 3] for translated in segments], None, "en"]


MYMEMORY = translator.MYMEMORY_ENDPOINT
GOOGLE = translator.GOOGLE_ENDPOINT
NETWORK_DOWN = requests.ConnectionError("network down")


@pytest.fixture(autouse=True)
def no_mymemory_email(monkeypatch):
    monkeypatch.delenv(translator.MYMEMORY_EMAIL_ENV, raising=False)


class TestDetectLanguage:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("New Pokemon GO event", "en"),
            ("ポケモンカードの新弾", "ja"),
            ("新弾発売", "zh-CN"),
            ("포켓몬 GO 이벤트", "ko"),
            ("🔥 2026 #PokemonGO", "en"),
        ],
    )
    def test_detects_by_script(self, text, expected):
        assert detect_language(text) == expected

    def test_kana_wins_over_kanji(self):
        """日文標題大多混用漢字，有假名就是日文，不能被漢字誤判成中文。"""
        assert detect_language("新弾の発売日") == "ja"


class TestSplitForLimit:
    def test_short_text_is_one_chunk(self):
        assert split_for_limit("Short title.", 500) == ["Short title."]

    def test_splits_at_sentence_boundaries(self):
        text = "第一句。第二句。第三句。"
        chunks = split_for_limit(text, 9)

        assert chunks == ["第一句。第二句。", "第三句。"]

    def test_every_chunk_fits_and_nothing_is_lost(self):
        text = "Sentence one is here. " * 40 + "ポケモン！" * 60
        chunks = split_for_limit(text, 100)

        assert all(len(chunk) <= 100 for chunk in chunks)
        assert "".join(chunks) == text

    def test_hard_splits_a_sentence_longer_than_the_limit(self):
        chunks = split_for_limit("x" * 250, 100)
        assert chunks == ["x" * 100, "x" * 100, "x" * 50]


class TestMyMemory:
    def test_returns_translation(self):
        get = FakeGet({MYMEMORY: FakeResponse(mymemory_payload("翻譯後"))})
        assert translate_title("original", get=get) == "翻譯後"

    def test_sends_detected_language_pair(self):
        get = FakeGet({MYMEMORY: FakeResponse(mymemory_payload("譯文"))})

        translate_title("ポケモンの新弾", get=get)

        (kwargs,) = get.calls_to(MYMEMORY)
        assert kwargs["params"]["langpair"] == "ja|zh-TW"
        assert kwargs["params"]["q"] == "ポケモンの新弾"
        assert "de" not in kwargs["params"]
        assert kwargs["timeout"] > 0

    def test_passes_email_when_configured(self, monkeypatch):
        """設定 email 後每日額度從 5,000 字提高到 50,000 字。"""
        monkeypatch.setenv(translator.MYMEMORY_EMAIL_ENV, "someone@example.com")
        get = FakeGet({MYMEMORY: FakeResponse(mymemory_payload("譯文"))})

        translate_title("original", get=get)

        (kwargs,) = get.calls_to(MYMEMORY)
        assert kwargs["params"]["de"] == "someone@example.com"

    def test_unescapes_html_entities(self):
        get = FakeGet({MYMEMORY: FakeResponse(mymemory_payload("寶可夢 &amp; 朋友&#39;s"))})
        assert translate_title("Pokemon & Friends", get=get) == "寶可夢 & 朋友's"

    def test_strips_zero_width_characters(self):
        get = FakeGet({MYMEMORY: FakeResponse(mymemory_payload("活動下​週開始"))})
        assert translate_title("Event next week", get=get) == "活動下週開始"

    def test_long_title_is_sent_in_chunks_and_joined(self):
        text = "一。" * 300  # 600 字，超過單次 500 字的上限
        get = FakeGet({MYMEMORY: lambda params: FakeResponse(mymemory_payload(f"[{len(params['q'])}]"))})

        result = translate_title(text, get=get)

        sizes = [len(kwargs["params"]["q"]) for kwargs in get.calls_to(MYMEMORY)]
        assert all(size <= translator.MYMEMORY_MAX_CHARS for size in sizes)
        assert sum(sizes) == len(text)
        assert result == "".join(f"[{size}]" for size in sizes)


class TestFallbackToGoogle:
    @pytest.mark.parametrize(
        "mymemory",
        [
            NETWORK_DOWN,
            FakeResponse(status=503),
            FakeResponse(mymemory_payload("QUERY LENGTH LIMIT EXCEEDED", status="403")),
            FakeResponse(mymemory_payload("MYMEMORY WARNING: YOU USED ALL", status=429)),
            FakeResponse(mymemory_payload("用完了", quota_finished=True)),
            FakeResponse(mymemory_payload("")),
            FakeResponse({"unexpected": "shape"}),
        ],
        ids=["network", "http-503", "status-403", "status-429", "quota", "blank", "bad-shape"],
    )
    def test_uses_google_when_mymemory_fails(self, mymemory):
        """MyMemory 的錯誤常以 HTTP 200 回來，錯誤訊息放在譯文欄位，絕不能當成譯文。"""
        get = FakeGet({MYMEMORY: mymemory, GOOGLE: FakeResponse(google_payload("谷歌譯文"))})
        assert translate_title("original", get=get) == "谷歌譯文"

    def test_google_joins_multi_sentence_translation(self):
        get = FakeGet(
            {MYMEMORY: NETWORK_DOWN, GOOGLE: FakeResponse(google_payload("第一句。", "第二句。"))}
        )
        assert translate_title("One. Two.", get=get) == "第一句。第二句。"

    def test_google_requests_traditional_chinese(self):
        get = FakeGet({MYMEMORY: NETWORK_DOWN, GOOGLE: FakeResponse(google_payload("譯文"))})

        translate_title("original", get=get)

        (kwargs,) = get.calls_to(GOOGLE)
        assert kwargs["params"]["tl"] == "zh-TW"
        assert kwargs["params"]["q"] == "original"


class TestFallbackToOriginal:
    def test_empty_input_returned_as_is(self):
        get = FakeGet({})
        assert translate_title("", get=get) == ""
        assert get.calls == []

    @pytest.mark.parametrize(
        "google",
        [
            NETWORK_DOWN,
            FakeResponse(status=429),
            FakeResponse(json_error=ValueError("not json")),
            FakeResponse(None),
            FakeResponse([[["", "source"]]]),
        ],
        ids=["network", "http-429", "bad-json", "none", "blank"],
    )
    def test_returns_original_when_every_service_fails(self, google, capsys):
        """翻譯服務不穩定不可以中斷整輪監控。"""
        get = FakeGet({MYMEMORY: NETWORK_DOWN, GOOGLE: google})

        assert translate_title("original", get=get) == "original"

        out = capsys.readouterr().out
        assert "[Warning]" in out
        assert "MyMemory" in out and "Google" in out
