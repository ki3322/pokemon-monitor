from src.models import generate_item_id, source_group, truncate_title


class TestGenerateItemId:
    def test_same_link_different_title_gives_same_id(self):
        """回歸測試：標題變動不可以產生新 ID。

        Serebii 的當日彙整標題會整天累加、Pokemon Information 的標題含更新日期，
        舊版把標題納入雜湊，導致同一篇文章被反覆通知。
        """
        first = generate_item_id("https://www.serebii.net/news/2026/09-August-2026.shtml")
        later = generate_item_id("https://www.serebii.net/news/2026/09-August-2026.shtml")
        assert first == later

    def test_different_links_give_different_ids(self):
        assert generate_item_id("https://a.example/1") != generate_item_id("https://a.example/2")

    def test_guid_takes_precedence_over_link(self):
        with_guid = generate_item_id("https://a.example/1?utm_source=x", guid="tag:post-1")
        assert with_guid == generate_item_id("https://a.example/other", guid="tag:post-1")

    def test_empty_input_returns_empty_string(self):
        assert generate_item_id("") == ""
        assert generate_item_id("", guid="  ") == ""

    def test_id_is_16_hex_chars(self):
        item_id = generate_item_id("https://a.example/1")
        assert len(item_id) == 16
        assert all(c in "0123456789abcdef" for c in item_id)


class TestTruncateTitle:
    def test_short_title_unchanged(self):
        assert truncate_title("短標題") == "短標題"

    def test_long_title_truncated_to_max_length(self):
        result = truncate_title("a" * 200, max_length=100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_exact_length_unchanged(self):
        assert truncate_title("a" * 100, max_length=100) == "a" * 100


class TestSourceGroup:
    def test_defaults_to_name(self):
        assert source_group({"name": "PokeBeach"}) == "PokeBeach"

    def test_explicit_group_wins(self):
        assert source_group({"name": "玩具人 寶可夢", "group": "玩具人"}) == "玩具人"
