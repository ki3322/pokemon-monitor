import json
import os
from datetime import datetime, timedelta, timezone

from src.state import SINK_NOTION, SINK_TELEGRAM, STATE_VERSION, StateManager

TG = SINK_TELEGRAM
NOTION = SINK_NOTION


def write_state(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


class TestLoad:
    def test_missing_file_starts_empty(self, state_file):
        assert StateManager(state_file).state["delivered"] == {}

    def test_corrupt_file_recovers_instead_of_crashing(self, state_file, capsys):
        """回歸測試：截斷的狀態檔必須被大聲回報，而不是無聲重置。"""
        with open(state_file, "w", encoding="utf-8") as f:
            f.write('{"version": 3, "delivered": {"telegram": {"A": ["x"')

        state = StateManager(state_file)

        assert state.state["delivered"] == {}
        assert "[Error]" in capsys.readouterr().out

    def test_non_dict_payload_recovers(self, state_file):
        write_state(state_file, ["not", "a", "dict"])
        assert StateManager(state_file).state["delivered"] == {}

    def test_old_version_is_discarded_and_reinitialized(self, state_file):
        """舊版結構不可沿用，否則新舊記錄對不起來會全部重發。"""
        write_state(state_file, {"version": 2, "seen_items": {"A": ["old-id"]}})

        state = StateManager(state_file)

        assert state.state["delivered"] == {}
        assert not state.is_initialized(TG, "A")

    def test_current_version_is_preserved(self, state_file):
        write_state(
            state_file,
            {"version": STATE_VERSION, "delivered": {TG: {"A": ["x"]}}},
        )
        assert StateManager(state_file).is_delivered(TG, "A", "x")

    def test_delivered_of_wrong_type_recovers(self, state_file, capsys):
        """回歸測試：state.json 由 CI 提交、rebase 合併，內容不可信任；
        delivered 不是 dict 時要大聲重置，不能等到 _sink_records 才炸掉。"""
        write_state(state_file, {"version": STATE_VERSION, "delivered": [], "alerts": {}})

        state = StateManager(state_file)

        assert state.state["delivered"] == {}
        assert "[Error]" in capsys.readouterr().out

    def test_sink_records_of_wrong_type_recover(self, state_file, capsys):
        write_state(state_file, {"version": STATE_VERSION, "delivered": {TG: ["x"]}})

        state = StateManager(state_file)

        assert state.state["delivered"] == {}
        assert "[Error]" in capsys.readouterr().out

    def test_group_items_of_wrong_type_recover(self, state_file, capsys):
        write_state(state_file, {"version": STATE_VERSION, "delivered": {TG: {"A": "x"}}})

        state = StateManager(state_file)

        assert state.state["delivered"] == {}
        assert "[Error]" in capsys.readouterr().out

    def test_alerts_of_wrong_type_recover(self, state_file, capsys):
        write_state(
            state_file,
            {"version": STATE_VERSION, "delivered": {}, "alerts": {"k": 123}},
        )

        state = StateManager(state_file)

        assert state.state["alerts"] == {}
        assert "[Error]" in capsys.readouterr().out


class TestSave:
    def test_roundtrip(self, state_file):
        state = StateManager(state_file)
        state.mark_delivered(TG, "來源", "id-1")
        state.save()

        assert StateManager(state_file).is_delivered(TG, "來源", "id-1")

    def test_save_is_atomic_and_leaves_no_temp_files(self, state_file):
        state = StateManager(state_file)
        state.mark_delivered(TG, "A", "1")
        state.save()

        leftovers = [n for n in os.listdir(os.path.dirname(state_file)) if n.startswith(".state-")]
        assert leftovers == []

    def test_writes_valid_json_with_version(self, state_file):
        StateManager(state_file).save()
        with open(state_file, encoding="utf-8") as f:
            assert json.load(f)["version"] == STATE_VERSION


class TestDelivery:
    def test_is_initialized_only_after_first_record(self, state_file):
        state = StateManager(state_file)
        assert not state.is_initialized(TG, "A")

        state.mark_all_delivered(TG, "A", [])

        assert state.is_initialized(TG, "A")

    def test_sinks_track_independently(self, state_file):
        """回歸測試：Telegram 成功不代表 Notion 也成功。"""
        state = StateManager(state_file)
        state.mark_delivered(TG, "A", "x")

        assert state.is_delivered(TG, "A", "x")
        assert not state.is_delivered(NOTION, "A", "x")

    def test_initializing_one_sink_does_not_initialize_another(self, state_file):
        state = StateManager(state_file)
        state.mark_all_delivered(TG, "A", ["x"])

        assert state.is_initialized(TG, "A")
        assert not state.is_initialized(NOTION, "A")

    def test_mark_delivered_is_idempotent(self, state_file):
        state = StateManager(state_file)
        state.mark_delivered(TG, "A", "x")
        state.mark_delivered(TG, "A", "x")

        assert state.state["delivered"][TG]["A"] == ["x"]

    def test_prunes_to_max_items_keeping_newest(self, state_file):
        state = StateManager(state_file)
        for i in range(10):
            state.mark_delivered(TG, "A", f"id-{i}", max_items=3)

        assert state.state["delivered"][TG]["A"] == ["id-7", "id-8", "id-9"]

    def test_empty_ids_are_ignored(self, state_file):
        state = StateManager(state_file)
        state.mark_all_delivered(TG, "A", ["", "x", ""])

        assert state.state["delivered"][TG]["A"] == ["x"]

    def test_updates_do_not_mutate_previous_state_object(self, state_file):
        state = StateManager(state_file)
        before = state.state
        state.mark_delivered(TG, "A", "x")

        assert before.get("delivered", {}) == {}


class TestAlertCooldown:
    def test_first_alert_is_allowed(self, state_file):
        assert StateManager(state_file).should_alert("k", 12)

    def test_suppressed_within_cooldown(self, state_file):
        state = StateManager(state_file)
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        state.record_alert("k", now=now)

        assert not state.should_alert("k", 12, now=now + timedelta(hours=1))

    def test_allowed_after_cooldown(self, state_file):
        state = StateManager(state_file)
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        state.record_alert("k", now=now)

        assert state.should_alert("k", 12, now=now + timedelta(hours=13))

    def test_unparsable_timestamp_allows_alert(self, state_file):
        write_state(state_file, {"version": STATE_VERSION, "alerts": {"k": "garbage"}})
        assert StateManager(state_file).should_alert("k", 12)
