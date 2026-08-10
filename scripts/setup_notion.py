#!/usr/bin/env python3
"""一次性建立 Notion 資料庫。

用法：
    export NOTION_TOKEN=secret_...
    python scripts/setup_notion.py <父頁面ID或網址>

事前準備：
  1. 到 https://www.notion.so/my-integrations 建立 integration，取得 token
  2. 在 Notion 開一個頁面當容器，點右上「...」→ Connections → 加入該 integration
  3. 複製該頁面網址傳給本腳本
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notion.client import NotionClient
from src.notion.ids import parse_page_id
from src.notion.schema import database_properties

DATABASE_TITLE = "Pokemon 新聞待撰稿"


def preflight(client: NotionClient, parent_page_id: str) -> bool:
    """逐項確認前置條件，把「建立失敗」拆成明確的原因。"""
    print("[1/2] 驗證 NOTION_TOKEN...")
    identity = client.whoami()
    if identity is None:
        print(
            "\n[Error] token 無效或已撤銷。\n"
            "  到 https://www.notion.so/my-integrations 打開你的 integration，\n"
            "  複製「Internal Integration Secret」（ntn_ 或 secret_ 開頭）重試。"
        )
        return False

    name = identity.get("name") or identity.get("bot", {}).get("owner", {}).get("type", "?")
    print(f"      OK — integration：{name}")

    print(f"[2/2] 確認 integration 能存取頁面 {parent_page_id}...")
    page = client.retrieve_page(parent_page_id)
    if page is None:
        print(
            "\n[Error] 讀不到這個頁面。兩個可能原因：\n\n"
            "  1. 頁面沒有分享給 integration（最常見）\n"
            "     打開該 Notion 頁面 → 右上「⋯」→ Connections → 加入你的 integration\n"
            "     注意：integration 預設看不到 workspace 內任何內容，權限要逐頁授權。\n\n"
            "  2. 這個 ID 不是頁面，或屬於另一個 workspace\n"
            "     token 與頁面必須在同一個 workspace。"
        )
        return False

    if page.get("object") == "database" or page.get("parent", {}).get("type") == "database_id":
        print(
            "\n[Warning] 這看起來是資料庫或資料庫內的項目。\n"
            "  建議改用一般頁面當容器，避免巢狀資料庫造成混亂。"
        )

    print("      OK — 可以存取")
    return True


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1

    parent_page_id = parse_page_id(argv[1])
    if not parent_page_id:
        print(f"[Error] 無法從「{argv[1]}」解析出 Notion 頁面 ID")
        return 1

    client = NotionClient()
    if not client.has_token():
        print("[Error] 未設定 NOTION_TOKEN")
        return 1

    if not preflight(client, parent_page_id):
        return 1

    print(f"\n建立資料庫「{DATABASE_TITLE}」...")
    created = client.create_database(parent_page_id, DATABASE_TITLE, database_properties())

    if created is None:
        print(
            "\n[Error] 前置檢查都通過，但建立資料庫仍失敗。\n"
            "  請把上方那行 (HTTP xxx: ...) 的完整訊息貼出來以便判斷。"
        )
        return 1

    database_id = created.get("id", "")
    print("\n建立成功。請把下面這行加入環境變數 / GitHub Secrets：\n")
    print(f"  NOTION_DATABASE_ID={database_id}\n")
    print(f"資料庫網址：{created.get('url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
