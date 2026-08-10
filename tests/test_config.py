"""設定檔的環境變數解析。

這些值在模組載入時就決定，因此測試必須 reload 才看得到不同的環境。
"""
import importlib

import config


def _reload(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RSSHUB_INSTANCE", raising=False)
    else:
        monkeypatch.setenv("RSSHUB_INSTANCE", value)
    return importlib.reload(config)


class TestRsshubInstance:
    def test_empty_env_var_falls_back_to_default(self, monkeypatch):
        """回歸測試：GitHub Actions 在 vars.X 未定義時仍會把環境變數設成空字串。

        os.environ.get("X", 預設) 遇到空字串不會用預設值，網址會變成
        沒有 scheme 的 /twitter/user/xxx，所有 Twitter 來源整批失敗。
        """
        assert _reload(monkeypatch, "").RSSHUB_INSTANCE.startswith("https://")

    def test_unset_env_var_uses_default(self, monkeypatch):
        assert _reload(monkeypatch, None).RSSHUB_INSTANCE.startswith("https://")

    def test_explicit_value_wins(self, monkeypatch):
        assert _reload(monkeypatch, "https://rss.example").RSSHUB_INSTANCE == "https://rss.example"

    def test_trailing_slash_stripped(self, monkeypatch):
        """網址會直接串接 /twitter/user/xxx，尾端斜線會產生雙斜線。"""
        assert _reload(monkeypatch, "https://rss.example/").RSSHUB_INSTANCE == "https://rss.example"

    def test_whitespace_only_falls_back(self, monkeypatch):
        reloaded = _reload(monkeypatch, "   ")
        assert reloaded.RSSHUB_INSTANCE.startswith("https://")

    def teardown_method(self):
        # 還原成測試程序原本的環境，避免影響其他測試模組
        importlib.reload(config)
