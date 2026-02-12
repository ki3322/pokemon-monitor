#!/usr/bin/env python3
import sys
import os

# 確保可以 import 專案模組
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import RSS_SOURCES, SCRAPE_SOURCES, TWITTER_ACCOUNTS
from src.state import StateManager
from src.notifier import TelegramNotifier
from src.monitors.rss_monitor import get_rss_items, get_twitter_items
from src.monitors.web_scraper import get_scraped_items
from deep_translator import GoogleTranslator


def translate_title(text: str) -> str:
    """將標題翻譯成繁體中文，失敗時回傳原文"""
    if not text:
        return text
    try:
        result = GoogleTranslator(source="auto", target="zh-TW").translate(text)
        return result or text
    except Exception:
        return text


def main():
    print("=== Pokemon Monitor 開始執行 ===\n")

    state = StateManager()
    notifier = TelegramNotifier()
    new_items_count = 0

    # 檢查 Telegram 設定
    if not notifier.is_configured():
        print("[Warning] Telegram 未設定，將只顯示結果不發送通知\n")

    # 1. 監控 RSS 來源
    print("📡 檢查 RSS 來源...")
    for source in RSS_SOURCES:
        print(f"  - {source['name']}", end=" ")
        items, success = get_rss_items(source)

        if not success:
            print("(連接失敗)")
            continue

        if not items:
            print("(24小時內無新文章)")
            continue

        new_items = []
        for item in items:
            if not state.is_seen(source["name"], item.id):
                new_items.append(item)
                state.mark_seen(source["name"], item.id)

        print(f"(發現 {len(new_items)} 則新內容)")

        for item in new_items:
            notifier.notify_new_item(
                title=translate_title(item.title),
                link=item.link,
                source=item.source,
                source_type=item.source_type,
            )
            new_items_count += 1

    # 2. 監控網頁爬蟲來源
    print("\n🌐 檢查網頁來源...")
    for source in SCRAPE_SOURCES:
        print(f"  - {source['name']}", end=" ")
        items = get_scraped_items(source)

        if not items:
            print("(無法取得)")
            continue

        new_items = []
        for item in items:
            if not state.is_seen(source["name"], item.id):
                new_items.append(item)
                state.mark_seen(source["name"], item.id)

        print(f"(發現 {len(new_items)} 則新內容)")

        for item in new_items:
            notifier.notify_new_item(
                title=translate_title(item.title),
                link=item.link,
                source=item.source,
                source_type=item.source_type,
            )
            new_items_count += 1

    # 3. 監控 Twitter 帳號
    print("\n🐦 檢查 Twitter 帳號...")
    twitter_failures = []
    for username in TWITTER_ACCOUNTS:
        print(f"  - @{username}", end=" ")
        items, success = get_twitter_items(username)

        if not success:
            print("(連接失敗)")
            twitter_failures.append(username)
            continue

        if not items:
            print("(1小時內無新推文)")
            continue

        source_id = f"twitter_{username}"
        new_items = []
        for item in items:
            if not state.is_seen(source_id, item.id):
                new_items.append(item)
                state.mark_seen(source_id, item.id)

        print(f"(發現 {len(new_items)} 則新推文)")

        for item in new_items:
            notifier.notify_new_item(
                title=translate_title(item.title),
                link=item.link,
                source=item.source,
                source_type=item.source_type,
            )
            new_items_count += 1

    # 檢查 Twitter 監控是否失效
    if twitter_failures and len(twitter_failures) >= len(TWITTER_ACCOUNTS) // 2:
        notifier.send_message(
            "⚠️ <b>Twitter 監控警告</b>\n\n"
            f"有 {len(twitter_failures)}/{len(TWITTER_ACCOUNTS)} 個帳號無法取得資料。\n"
            "可能是 X Cookie 已過期，請更新 Zeabur 的環境變數：\n"
            "• TWITTER_AUTH_TOKEN\n"
            "• TWITTER_CT0"
        )

    # 儲存狀態
    state.save()

    print(f"\n=== 執行完成，共發送 {new_items_count} 則通知 ===")
    return new_items_count


if __name__ == "__main__":
    main()
