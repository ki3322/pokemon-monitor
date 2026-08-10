from src import translator
from src.translator import translate_title


class FakeTranslator:
    def __init__(self, result=None, error=None, **kwargs):
        self._result = result
        self._error = error

    def translate(self, text):
        if self._error:
            raise self._error
        return self._result


def patch_translator(monkeypatch, **kwargs):
    monkeypatch.setattr(
        translator, "GoogleTranslator", lambda **_: FakeTranslator(**kwargs)
    )


class TestTranslateTitle:
    def test_returns_translation(self, monkeypatch):
        patch_translator(monkeypatch, result="翻譯後")
        assert translate_title("original") == "翻譯後"

    def test_empty_input_returned_as_is(self):
        assert translate_title("") == ""

    def test_falls_back_to_original_on_error(self, monkeypatch, capsys):
        """翻譯服務不穩定不可以中斷整輪監控。"""
        patch_translator(monkeypatch, error=RuntimeError("rate limited"))

        assert translate_title("original") == "original"
        assert "[Warning]" in capsys.readouterr().out

    def test_falls_back_when_translation_is_empty(self, monkeypatch):
        patch_translator(monkeypatch, result="")
        assert translate_title("original") == "original"

    def test_falls_back_when_translation_is_none(self, monkeypatch):
        patch_translator(monkeypatch, result=None)
        assert translate_title("original") == "original"
