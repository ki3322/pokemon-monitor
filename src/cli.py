#!/usr/bin/env python3
"""撰稿流程的指令列介面。

典型流程：
    python -m src.cli pending              # 抓出勾選的新聞與原文，產生摘要檔
    (在 Claude Code 依 pokemonhubscom-writer 規範寫稿，存成 .article.md)
    python -m src.cli publish <page_id> --file drafts/xxx.article.md
"""
import argparse
import os
import sys
from typing import List, Optional

from config import DRAFTS_DIR, STATE_FILE
from src.article.brief import article_path, write_brief
from src.article.extractor import fetch_content
from src.dashboard.collect import build_dashboard
from src.dashboard.render import render_page
from src.notion.client import NotionClient
from src.notion.dashboard import NotionDashboard
from src.notion.ids import page_url, parse_page_id
from src.notion.reader import NotionReader, SelectedItem, to_selected_item
from src.notion.upgrade import NotionUpgrade
from src.notion.writer import NotionWriter

DEFAULT_DASHBOARD = os.path.join(DRAFTS_DIR, "dashboard.html")


def _require_notion(client: NotionClient) -> bool:
    if client.is_configured():
        return True
    print(
        "[Error] Notion 未設定。請設定環境變數：\n"
        "  export NOTION_TOKEN=secret_...\n"
        "  export NOTION_DATABASE_ID=..."
    )
    return False


def command_list(args: argparse.Namespace) -> int:
    reader = NotionReader()
    if not _require_notion(reader.client):
        return 1

    items = reader.pending_items()
    if items is None:
        print("[Error] Notion 查詢失敗，請稍後再試（確認 token 與資料庫分享設定）")
        return 1
    if not items:
        print("目前沒有勾選待寫的項目。")
        return 0

    print(f"勾選待寫的項目（{len(items)} 則）：\n")
    for item in items:
        print(f"  [{item.status}] {item.title}")
        print(f"      page_id: {item.page_id}")
        print(f"      來源: {item.source}  |  {item.link}\n")
    return 0


def command_pending(args: argparse.Namespace) -> int:
    """抓出勾選項目的原文，寫成摘要檔供撰稿使用。"""
    reader = NotionReader()
    if not _require_notion(reader.client):
        return 1

    items: Optional[List[SelectedItem]] = reader.pending_items()
    if items is None:
        print("[Error] Notion 查詢失敗，請稍後再試（確認 token 與資料庫分享設定）")
        return 1
    if not items:
        print("目前沒有勾選待寫的項目。")
        return 0

    print(f"找到 {len(items)} 則勾選項目，開始抓取原文...\n")
    failures = 0

    for item in items:
        print(f"  - {item.title}")
        content = fetch_content(item.link)
        if content is None:
            failures += 1
            print("      (原文抓取失敗，摘要檔仍會建立)")

        path = write_brief(args.dir, item, content)
        print(f"      摘要: {path}")
        print(f"      稿件請存成: {article_path(args.dir, item)}\n")

    print(f"完成。{len(items) - failures} 則成功抓到原文，{failures} 則需人工確認。")
    print(f"寫好稿後執行：python -m src.cli publish <page_id> --file <稿件路徑>")
    return 0


def command_publish(args: argparse.Namespace) -> int:
    client = NotionClient()
    if not _require_notion(client):
        return 1

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            markdown = f.read()
    except OSError as error:
        print(f"[Error] 無法讀取稿件 {args.file}: {error}")
        return 1

    if not markdown.strip():
        print(f"[Error] 稿件 {args.file} 是空的")
        return 1

    link = args.link
    if not link:
        page = client.retrieve_page(args.page_id)
        if page is None:
            print("[Error] 找不到該 Notion 頁面，請確認 page_id")
            return 1
        link = to_selected_item(page).link

    writer = NotionWriter(client)
    if not writer.publish(
        args.page_id,
        markdown,
        link=link,
        wordpress_url=args.wordpress_url,
        replace=not args.append,
    ):
        return 1

    print("已寫入 Notion，狀態設為「已完成」。")
    print("在 Notion 頁面展開「WordPress HTML」，點複製鈕即可貼進 WordPress。")
    return 0


def _publish_notion_dashboard(dashboard, target: str) -> int:
    page_id = parse_page_id(target)
    if not page_id:
        print(f"[Error] 看不懂這個頁面：{target}\n  請貼 Notion 頁面網址，或 32 位的頁面 ID。")
        return 1

    client = NotionClient()
    if not client.has_token():
        print("[Error] 缺少 NOTION_TOKEN。請先 export NOTION_TOKEN=ntn_...")
        return 1

    published = NotionDashboard(client).publish(page_id, dashboard)
    if published is None:
        print(
            "[Error] 寫入 Notion 失敗。最常見的原因是那一頁沒有分享給 integration："
            "打開該頁 → 右上「⋯」→ Connections → 加入你的 integration。"
        )
        return 1

    print(f"Notion 儀表板已更新：{page_url(published)}")
    return 0


def command_dashboard(args: argparse.Namespace) -> int:
    """把目前的監控狀態渲染成儀表板（HTML 檔，或一頁 Notion）。"""
    dashboard = build_dashboard(
        state_file=args.state, drafts_dir=args.dir, news_reader=NotionReader()
    )

    if args.notion:
        return _publish_notion_dashboard(dashboard, args.notion)

    html = render_page(dashboard)

    directory = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(directory, exist_ok=True)

    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as error:
        print(f"[Error] 無法寫入 {args.output}: {error}")
        return 1

    print(f"儀表板已產生：{args.output}")
    print(
        f"  來源群組 {len(dashboard.groups)} 個"
        f"｜追蹤中 {dashboard.total_tracked} 則"
        f"｜稿件 {len(dashboard.drafts)} 份"
    )
    if dashboard.pending_groups:
        print(f"  待初始化 {len(dashboard.pending_groups)} 個群組（下一輪只記錄現況，不發通知）")
    return 0


def command_notion_upgrade(args: argparse.Namespace) -> int:
    """把既有資料庫補齊到目前的欄位定義（只補不改，可重複執行）。"""
    client = NotionClient()
    if not _require_notion(client):
        return 1

    upgrade = NotionUpgrade(client)
    ok, changes = upgrade.run()
    if not ok:
        for problem in changes:
            print(f"[Error] {problem}")
        return 1

    if changes:
        print("資料庫已更新：")
        for change in changes:
            print(f"  - {change}")
    else:
        print("資料庫已是最新，沒有要變更的欄位。")

    if args.backfill:
        result = upgrade.backfill_original_titles()
        if result is None:
            print("[Error] Notion 查詢失敗，回填未執行，請稍後再試")
            return 1
        filled, failed = result
        print(f"原始標題回填：{filled} 筆補上，{failed} 筆失敗。")
        if failed:
            return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.cli", description="PokemonHubs 撰稿流程")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="列出勾選待寫的項目")
    list_parser.set_defaults(func=command_list)

    pending_parser = subparsers.add_parser("pending", help="抓取勾選項目的原文並產生摘要檔")
    pending_parser.add_argument("--dir", default=DRAFTS_DIR, help="摘要與稿件的存放目錄")
    pending_parser.set_defaults(func=command_pending)

    publish_parser = subparsers.add_parser("publish", help="把寫好的稿件回寫 Notion")
    publish_parser.add_argument("page_id", help="Notion 頁面 ID")
    publish_parser.add_argument("--file", required=True, help="稿件 Markdown 路徑")
    publish_parser.add_argument("--link", default="", help="來源連結（預設從 Notion 讀取）")
    publish_parser.add_argument("--wordpress-url", default="", help="上稿後的 WordPress 網址")
    publish_parser.add_argument(
        "--append",
        action="store_true",
        help="保留頁面既有內容（預設會先清除，避免重複發布疊加兩份文章）",
    )
    publish_parser.set_defaults(func=command_publish)

    dashboard_parser = subparsers.add_parser("dashboard", help="產生監控狀態儀表板")
    dashboard_parser.add_argument(
        "--notion",
        default="",
        help="改為寫進 Notion：給定父頁面的網址或 ID，會在其底下建立／更新儀表板子頁",
    )
    dashboard_parser.add_argument("--output", default=DEFAULT_DASHBOARD, help="輸出的 HTML 路徑")
    dashboard_parser.add_argument("--state", default=STATE_FILE, help="狀態檔路徑")
    dashboard_parser.add_argument("--dir", default=DRAFTS_DIR, help="草稿目錄")
    dashboard_parser.set_defaults(func=command_dashboard)

    upgrade_parser = subparsers.add_parser(
        "notion-upgrade", help="把既有 Notion 資料庫補齊到目前的欄位定義"
    )
    upgrade_parser.add_argument(
        "--backfill",
        action="store_true",
        help="順便把既有項目的「原始標題」補上（只填空的，不覆寫）",
    )
    upgrade_parser.set_defaults(func=command_notion_upgrade)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
