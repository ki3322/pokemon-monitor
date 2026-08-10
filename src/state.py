"""投遞記錄與警告冷卻的持久化狀態。

一則內容可能要送到多個目的地（Telegram、Notion），各自的成功與失敗互不相干，
因此投遞記錄以「目的地 → 來源群組 → 項目 ID」三層結構分開存放。
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from config import STATE_FILE

# 狀態格式版本。投遞記錄的結構或項目 ID 的算法改變時要遞增，
# 舊記錄會被捨棄並在下一輪重新初始化（不會發送通知）。
STATE_VERSION = 3

# 每個來源群組保留的投遞記錄上限
MAX_ITEMS_PER_SOURCE = 100

# 目的地代號
SINK_TELEGRAM = "telegram"
SINK_NOTION = "notion"


class StateManager:
    """管理 state.json。

    所有更新都以「產生新物件再重新綁定」的方式進行，不就地修改既有結構。
    """

    def __init__(self, state_file: str = STATE_FILE):
        self.state_file = state_file
        self.state = self._load()

    # ------------------------------------------------------------------ 載入 / 儲存

    @staticmethod
    def _empty_state() -> dict:
        return {"version": STATE_VERSION, "delivered": {}, "alerts": {}}

    def _load(self) -> dict:
        if not os.path.exists(self.state_file):
            print(f"[Info] 找不到狀態檔 {self.state_file}，以空狀態啟動")
            return self._empty_state()

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError) as error:
            # 絕對不能無聲重置：空狀態會讓所有來源重新初始化，
            # 必須在 log 中留下明確痕跡才查得出來。
            print(
                f"[Error] 狀態檔 {self.state_file} 損毀或無法讀取 ({error})。"
                "將以空狀態啟動，本輪所有來源會重新初始化且不發送通知。"
            )
            return self._empty_state()

        if not isinstance(loaded, dict):
            print(f"[Error] 狀態檔格式不正確（預期 object，實際為 {type(loaded).__name__}），以空狀態啟動")
            return self._empty_state()

        version = loaded.get("version")
        if version != STATE_VERSION:
            print(
                f"[Info] 狀態格式由 v{version} 升級至 v{STATE_VERSION}，"
                "捨棄舊的投遞記錄並重新初始化（本輪不發送通知）"
            )
            return self._empty_state()

        # 只有「缺欄位」可以補成空 dict；型別錯誤（例如空 list）必須走大聲重置
        delivered = loaded.get("delivered")
        delivered = {} if delivered is None else delivered
        alerts = loaded.get("alerts")
        alerts = {} if alerts is None else alerts
        if not self._valid_delivered(delivered) or not self._valid_alerts(alerts):
            # 狀態檔由 CI 提交、rebase 合併，內容不可信任；
            # 結構不對要在載入時大聲重置，不能等到讀取記錄時才炸掉。
            print(
                f"[Error] 狀態檔 {self.state_file} 結構不正確，"
                "將以空狀態啟動，本輪所有來源會重新初始化且不發送通知。"
            )
            return self._empty_state()

        return {
            "version": STATE_VERSION,
            "delivered": delivered,
            "alerts": alerts,
        }

    @staticmethod
    def _valid_delivered(delivered: object) -> bool:
        """delivered 必須是「目的地 → 來源群組 → 項目 ID 清單」的三層結構。"""
        if not isinstance(delivered, dict):
            return False
        for records in delivered.values():
            if not isinstance(records, dict):
                return False
            if not all(isinstance(items, list) for items in records.values()):
                return False
        return True

    @staticmethod
    def _valid_alerts(alerts: object) -> bool:
        return isinstance(alerts, dict) and all(isinstance(v, str) for v in alerts.values())

    def save(self) -> None:
        """原子寫入狀態檔。

        先寫入同目錄的暫存檔並 fsync，再用 os.replace 換上；
        這樣即使流程在寫入途中被中斷，也不會留下被截斷的 state.json。
        """
        directory = os.path.dirname(os.path.abspath(self.state_file))
        os.makedirs(directory, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # ------------------------------------------------------------------ 投遞記錄

    def _sink_records(self, sink: str) -> Dict[str, List[str]]:
        return self.state.get("delivered", {}).get(sink, {})

    def is_initialized(self, sink: str, group_id: str) -> bool:
        """該目的地對這個來源群組是否已經有過一輪記錄。

        未初始化的組合（新來源、新目的地、或狀態檔重置後）應該只記錄現況而不投遞，
        否則會一次湧出整個頁面的內容。
        """
        return group_id in self._sink_records(sink)

    def is_delivered(self, sink: str, group_id: str, item_id: str) -> bool:
        return item_id in self._sink_records(sink).get(group_id, [])

    def mark_delivered(
        self,
        sink: str,
        group_id: str,
        item_id: str,
        max_items: int = MAX_ITEMS_PER_SOURCE,
    ) -> None:
        self.mark_all_delivered(sink, group_id, [item_id], max_items=max_items)

    def mark_all_delivered(
        self,
        sink: str,
        group_id: str,
        item_ids: Iterable[str],
        max_items: int = MAX_ITEMS_PER_SOURCE,
    ) -> None:
        """記錄一批項目為已投遞；即使清單為空也會建立該群組的記錄。"""
        delivered = self.state.get("delivered", {})
        sink_records = delivered.get(sink, {})
        current: List[str] = sink_records.get(group_id, [])

        merged = list(current)
        for item_id in item_ids:
            if item_id and item_id not in merged:
                merged.append(item_id)

        self.state = {
            **self.state,
            "delivered": {
                **delivered,
                sink: {**sink_records, group_id: merged[-max_items:]},
            },
        }

    # ------------------------------------------------------------------ 警告冷卻

    def should_alert(self, key: str, cooldown_hours: float, now: Optional[datetime] = None) -> bool:
        """距離上次同類警告是否已超過冷卻時間。"""
        now = now or datetime.now(timezone.utc)
        last = self.state.get("alerts", {}).get(key)
        if not last:
            return True

        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return True

        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)

        return now - last_dt >= timedelta(hours=cooldown_hours)

    def record_alert(self, key: str, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        alerts = self.state.get("alerts", {})
        self.state = {
            **self.state,
            "alerts": {**alerts, key: now.isoformat()},
        }
