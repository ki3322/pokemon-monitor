#!/usr/bin/env python3
"""Pokemon Monitor 主程式。

執行方式：python -m src.main
"""
import sys
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from config import NOTION_EXCLUDED_GROUPS, RSS_SOURCES, SCRAPE_SOURCES, TWITTER_ACCOUNTS
from src.models import FeedItem, source_group, twitter_group
from src.monitors.rss_monitor import get_rss_items, get_twitter_items
from src.monitors.web_scraper import find_scraper, get_scraped_items
from src.notifier import TelegramNotifier
from src.notion.sync import NotionSync
from src.sinks import build_sinks
from src.state import StateManager
from src.translator import translate_title

TWITTER_ALERT_KEY = "twitter_failure"
SCRAPE_ALERT_KEY = "scrape_failure"
ALERT_COOLDOWN_HOURS = 12


@dataclass(frozen=True)
class Totals:
    sent: int = 0
    failed: int = 0

    def __add__(self, other: "Totals") -> "Totals":
        return Totals(self.sent + other.sent, self.failed + other.failed)


class MonitorRun:
    """單次執行的流程與統計。"""

    def __init__(self, state: StateManager, notifier: TelegramNotifier, sinks: List):
        self.state = state
        self.notifier = notifier
        self.sinks = sinks
        # 依目的地分開計數：合併計數會讓「Telegram 全掛、Notion 正常」看起來像部分失敗
        self.sink_totals: Dict[str, Totals] = {}
        # 本輪已初始化的 (目的地, 群組)。同群組的第二個來源必須繼續走初始化流程，
        # 否則它獨有的項目會在第一輪就全部湧出。
        self.bootstrapped: Set[Tuple[str, str]] = set()

    @property
    def totals(self) -> Totals:
        return sum(self.sink_totals.values(), Totals())

    def dead_sinks(self) -> Tuple[str, ...]:
        """本輪有嘗試投遞、卻一則都沒送成功的目的地（例如 token 失效）。"""
        return tuple(
            sink.label
            for sink in self.sinks
            if (result := self.sink_totals.get(sink.name)) and result.failed and not result.sent
        )

    def process(self, group_id: str, items: List[FeedItem], translate: bool = True) -> str:
        """處理一個來源抓回的項目，回傳要印出的結果說明。"""
        if not self.sinks:
            return "(無可用的投遞目的地)"

        # 不收這個來源的目的地整個跳過：不初始化、不投遞、不留記錄。
        # 之後若取消排除，它會像新來源一樣先初始化而不是湧出整頁舊內容。
        accepting = [sink for sink in self.sinks if sink.accepts(group_id)]
        if not accepting:
            return "(此來源不投遞到任何目的地)"

        notes: List[str] = []
        active = []

        for sink in accepting:
            if self._needs_bootstrap(sink, group_id):
                self.state.mark_all_delivered(sink.name, group_id, [item.id for item in items])
                self.bootstrapped.add((sink.name, group_id))
                notes.append(f"{sink.label} 初始化 {len(items)} 則")
            else:
                active.append(sink)

        pending = {
            sink.name: [
                item for item in items
                if not self.state.is_delivered(sink.name, group_id, item.id)
            ]
            for sink in active
        }

        titles = self._translate_needed(items, pending, translate)

        for sink in active:
            queued = pending[sink.name]
            if not queued:
                continue
            result = self._deliver_all(sink, group_id, queued, titles)
            self.sink_totals = {
                **self.sink_totals,
                sink.name: self.sink_totals.get(sink.name, Totals()) + result,
            }
            notes.append(self._describe(sink.label, result))

        return f"({'，'.join(notes)})" if notes else "(無新內容)"

    def _needs_bootstrap(self, sink, group_id: str) -> bool:
        return (
            (sink.name, group_id) in self.bootstrapped
            or not self.state.is_initialized(sink.name, group_id)
        )

    @staticmethod
    def _translate_needed(
        items: List[FeedItem],
        pending: Dict[str, List[FeedItem]],
        translate: bool,
    ) -> Dict[str, str]:
        """只翻譯真的要投遞的標題，而且每則只翻一次（多個目的地共用）。"""
        needed = {item.id for queued in pending.values() for item in queued}
        return {
            item.id: (translate_title(item.title) if translate else item.title)
            for item in items
            if item.id in needed
        }

    def _deliver_all(self, sink, group_id: str, items: List[FeedItem], titles: Dict[str, str]) -> Totals:
        sent = failed = 0

        for item in items:
            if sink.deliver(item, titles.get(item.id, item.title)):
                # 只有成功送出才記錄已投遞，失敗的項目下次執行會重試
                self.state.mark_delivered(sink.name, group_id, item.id)
                sent += 1
            else:
                failed += 1

        return Totals(sent, failed)

    @staticmethod
    def _describe(label: str, result: Totals) -> str:
        if result.failed:
            return f"{label} {result.sent} 則，{result.failed} 則待重試"
        return f"{label} {result.sent} 則"


def validate_config() -> None:
    """啟動時檢查設定，設定錯誤要立刻失敗而不是無聲略過。"""
    unhandled = [s["url"] for s in SCRAPE_SOURCES if find_scraper(s.get("url", "")) is None]
    if unhandled:
        raise ValueError(
            "以下 SCRAPE_SOURCES 沒有對應的爬蟲，請在 web_scraper.SCRAPERS 中註冊：\n  "
            + "\n  ".join(unhandled)
        )

    known = {source_group(s) for s in list(RSS_SOURCES) + list(SCRAPE_SOURCES)}
    known |= {twitter_group(username) for username in TWITTER_ACCOUNTS}

    unknown = sorted(set(NOTION_EXCLUDED_GROUPS) - known)
    if unknown:
        raise ValueError(
            "NOTION_EXCLUDED_GROUPS 中的群組不存在，請確認拼字"
            "（網站用 name／group，Twitter 用 twitter_<帳號>）：\n  "
            + "\n  ".join(unknown)
            + "\n目前可用的群組：\n  "
            + "\n  ".join(sorted(known))
        )


def monitor_rss(run: MonitorRun) -> None:
    print("📡 檢查 RSS 來源...")
    for source in RSS_SOURCES:
        print(f"  - {source['name']}", end=" ")
        items, success = get_rss_items(source)
        if not success:
            print("(連接失敗)")
            continue
        print(run.process(source_group(source), items, source.get("translate", True)))


def monitor_scrapers(run: MonitorRun) -> List[str]:
    """回傳抓取失敗的來源名稱。"""
    print("\n🌐 檢查網頁來源...")
    failures = []

    for source in SCRAPE_SOURCES:
        print(f"  - {source['name']}", end=" ")
        items, success = get_scraped_items(source)
        if not success:
            print("(連接失敗)")
            failures.append(source["name"])
            continue
        print(run.process(source_group(source), items, source.get("translate", True)))

    return failures


def monitor_twitter(run: MonitorRun) -> List[str]:
    """回傳抓取失敗的帳號名稱。"""
    print("\n🐦 檢查 Twitter 帳號...")
    failures = []

    for username in TWITTER_ACCOUNTS:
        print(f"  - @{username}", end=" ")
        items, success = get_twitter_items(username)
        if not success:
            print("(連接失敗)")
            failures.append(username)
            continue
        print(run.process(twitter_group(username), items))

    return failures


def _send_alert(run: MonitorRun, key: str, message: str, failures: List[str], total: int) -> None:
    """統一的失效警告：達門檻才發，並以冷卻時間避免重複轟炸。"""
    if len(failures) < max(1, total // 2):
        return

    if not run.state.should_alert(key, ALERT_COOLDOWN_HOURS):
        print(f"\n[Info] {key} 異常（{len(failures)} 項），冷卻中不重複通知")
        return

    if run.notifier.send_message(message):
        run.state.record_alert(key)


def alert_twitter_failures(run: MonitorRun, failures: List[str]) -> None:
    _send_alert(
        run,
        TWITTER_ALERT_KEY,
        "⚠️ <b>Twitter 監控警告</b>\n\n"
        f"有 {len(failures)}/{len(TWITTER_ACCOUNTS)} 個帳號無法取得資料。\n"
        "可能是 X Cookie 已過期，請更新 Zeabur 的環境變數：\n"
        "• TWITTER_AUTH_TOKEN\n"
        "• TWITTER_CT0",
        failures,
        len(TWITTER_ACCOUNTS),
    )


def alert_scrape_failures(run: MonitorRun, failures: List[str]) -> None:
    _send_alert(
        run,
        SCRAPE_ALERT_KEY,
        "⚠️ <b>網頁監控警告</b>\n\n"
        f"有 {len(failures)}/{len(SCRAPE_SOURCES)} 個網頁來源無法取得資料：\n"
        + "\n".join(f"• {name}" for name in failures)
        + "\n\n可能是網站改版或暫時無法連線。",
        failures,
        len(SCRAPE_SOURCES),
    )


def main() -> int:
    print("=== Pokemon Monitor 開始執行 ===\n")
    validate_config()

    state = StateManager()
    notifier = TelegramNotifier()
    sinks = build_sinks(notifier, NotionSync())

    if not sinks:
        print("[Warning] 沒有任何已設定的投遞目的地，本次為試跑\n")
    else:
        print()

    run = MonitorRun(state, notifier, sinks)

    monitor_rss(run)
    scrape_failures = monitor_scrapers(run)
    twitter_failures = monitor_twitter(run)

    alert_scrape_failures(run, scrape_failures)
    alert_twitter_failures(run, twitter_failures)

    state.save()
    return finish(run)


def finish(run: MonitorRun) -> int:
    """印出總結並回傳結束碼。

    某個目的地整輪全數失敗時回傳 1，讓排程顯示失敗。
    通常是設定壞掉（token 失效、權限被撤），等下一輪也不會自己好；
    只印在日誌裡的話，排程照樣顯示成功，沒有人會發現。
    """
    summary = f"\n=== 執行完成：投遞 {run.totals.sent} 則"
    if run.totals.failed:
        summary += f"，{run.totals.failed} 則失敗待下次重試"
    print(summary + " ===")

    dead = run.dead_sinks()
    if not dead:
        return 0

    print(
        f"[Error] {'、'.join(dead)} 本輪全部投遞失敗，請檢查憑證或權限"
        "（例如 GitHub Secrets 的 token）。失敗的項目已保留，修好後下一輪會重送。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
