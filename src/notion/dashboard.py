"""把監控狀態寫成一頁 Notion 儀表板。

Notion 沒有自訂 CSS，能表達設計語言的只有色塊、標題階層與版面分欄。
因此這裡把 Antoniouve 的語言收斂成 Notion 真的做得到的部分：
黃色為主的色塊表面、橘／粉作強調、巨大的數字、以及用字元畫出來的量表。
形狀（膠囊、17px 圓角）與傾斜、浮動圖形無法遷移，刻意不用圖片假造。
"""
from typing import Dict, List, Optional, Sequence

from src.dashboard.stats import Dashboard, DraftStat, GroupStat
from src.notion import blocks as nb
from src.notion.client import NotionClient
from src.state import MAX_ITEMS_PER_SOURCE, STATE_VERSION

PAGE_TITLE = "📊 監控儀表板"

# Notion 的區塊底色，對應設計系統的 bg / accent
BG = "yellow_background"
ACCENT_ORANGE = "orange_background"
ACCENT_PINK = "pink_background"
MUTED = "gray"

# 量表的格數。Notion 畫不出進度條，用字元表現是唯一不靠圖片的做法。
METER_CELLS = 10
METER_FULL = "█"
METER_EMPTY = "░"

# Notion 的分欄至少要兩欄，欄數過多會擠到看不清楚
MIN_COLUMNS = 2
MAX_COLUMNS = 5


def meter(count: int, ceiling: int = MAX_ITEMS_PER_SOURCE, cells: int = METER_CELLS) -> str:
    """用方塊字元畫出比例量表。"""
    if ceiling <= 0:
        return METER_EMPTY * cells
    filled = min(round(count / ceiling * cells), cells)
    return METER_FULL * filled + METER_EMPTY * (cells - filled)


def _status_text(group: GroupStat) -> str:
    if not group.is_bootstrapped:
        return "待初始化"
    return "記錄已滿" if group.is_saturated else "運作中"


def _display_name(group: GroupStat) -> str:
    return group.group.replace("twitter_", "@", 1)


def header_blocks(dashboard: Dashboard) -> List[Dict]:
    """頁首：一句話講完現況，異常另外用橘色標出來。"""
    summary = (
        f"更新於 {dashboard.generated_at}　｜　"
        f"{len(dashboard.groups)} 個來源群組　｜　"
        f"追蹤中 {dashboard.total_tracked} 則"
    )
    result = [nb.callout_block(summary, emoji="📡", color=BG)]

    if dashboard.state_version != STATE_VERSION:
        found = f"v{dashboard.state_version}" if dashboard.state_version else "舊格式"
        result.append(
            nb.callout_block(
                f"狀態檔是 {found}，與目前的 v{STATE_VERSION} 不符。"
                "下一輪會捨棄舊記錄並重新初始化，該輪不會發送通知。",
                emoji="⚠️",
                color=ACCENT_ORANGE,
            )
        )
    elif dashboard.pending_groups:
        names = "、".join(_display_name(g) for g in dashboard.pending_groups)
        result.append(
            nb.callout_block(
                f"{len(dashboard.pending_groups)} 個群組待初始化：{names}",
                emoji="🆕",
                color=ACCENT_ORANGE,
            )
        )

    if not dashboard.notion_configured:
        # 這個旗標只反映「產生儀表板的那個環境」，讀不到 GitHub Secrets，
        # 所以措辭必須限定在本機，不能講成監控端沒設定。
        result.append(
            nb.callout_block(
                "產生這頁的環境沒有完整的 NOTION_TOKEN / NOTION_DATABASE_ID，"
                "因此無法確認監控端的 Notion 同步狀態（GitHub Secrets 在這裡讀不到）。",
                emoji="🔌",
                color=MUTED,
            )
        )

    return result


def funnel_blocks(dashboard: Dashboard) -> List[Dict]:
    """流程漏斗：每一段一欄，數字用 heading_1 撐大。"""
    stages = list(dashboard.stages)[:MAX_COLUMNS]
    if len(stages) < MIN_COLUMNS:
        return [nb.paragraph_block("（沒有可顯示的流程資料）", color=MUTED)]

    columns = [
        [
            nb.heading_block(str(stage.count), level=1),
            nb.paragraph_block(stage.label),
            nb.paragraph_block(stage.note, color=MUTED),
        ]
        for stage in stages
    ]
    return [nb.heading_block("流程漏斗", level=2), nb.column_list_block(columns)]


def group_table(groups: Sequence[GroupStat], empty_text: str) -> List[Dict]:
    if not groups:
        return [nb.paragraph_block(empty_text, color=MUTED)]

    rows = [("來源", "追蹤", "進度", "Notion", "狀態")]
    rows += [
        (
            _display_name(group),
            str(group.tracked),
            meter(group.tracked),
            str(group.notion),
            _status_text(group),
        )
        for group in groups
    ]
    return [nb.text_table(rows)]


def draft_blocks(drafts: Sequence[DraftStat]) -> List[Dict]:
    if not drafts:
        return [
            nb.paragraph_block(
                "還沒有稿件。在資料庫勾選「寫成文章」後執行 python -m src.cli pending。",
                color=MUTED,
            )
        ]

    rows = [("稿件", "來源摘要", "稿件檔", "狀態")]
    rows += [
        (
            draft.slug,
            "✓" if draft.has_brief else "—",
            "✓" if draft.has_article else "—",
            draft.status,
        )
        for draft in drafts
    ]
    return [nb.text_table(rows)]


def build_blocks(dashboard: Dashboard) -> List[Dict]:
    """組出整頁的 Notion 區塊。"""
    return [
        *header_blocks(dashboard),
        *funnel_blocks(dashboard),
        nb.divider_block(),
        nb.heading_block("網站來源", level=2),
        nb.paragraph_block(f"每個群組最多保留 {MAX_ITEMS_PER_SOURCE} 筆記錄", color=MUTED),
        *group_table(dashboard.website_groups, "設定檔裡沒有網站來源。"),
        nb.heading_block("Twitter 帳號", level=2),
        nb.paragraph_block("透過 RSSHub 取得", color=MUTED),
        *group_table(dashboard.twitter_groups, "設定檔裡沒有 Twitter 帳號。"),
        nb.heading_block("撰稿進度", level=2),
        *draft_blocks(dashboard.drafts),
        nb.divider_block(),
        nb.paragraph_block(
            "由 python -m src.cli dashboard --notion 產生　｜　"
            "設計語言：Antoniouve（OpenDesign design-pack/v1）",
            color=MUTED,
        ),
    ]


def find_child_page(client: NotionClient, parent_page_id: str, title: str) -> Optional[str]:
    """在父頁面底下找同名子頁面，讓重複執行是更新而不是一直長新頁。

    找不到回傳空字串；讀取失敗回傳 None——失敗時不能當成「沒有這一頁」，
    否則會另外長出一頁新的，疊成兩份。
    """
    children = client.list_children(parent_page_id)
    if children is None:
        return None
    for block in children:
        if block.get("type") != "child_page":
            continue
        if (block.get("child_page") or {}).get("title") == title:
            return block.get("id", "")
    return ""


class NotionDashboard:
    def __init__(self, client: Optional[NotionClient] = None):
        self.client = client or NotionClient()

    def _clear(self, page_id: str) -> bool:
        children = self.client.list_children(page_id)
        if children is None:
            return False
        for block in children:
            if not self.client.delete_block(block.get("id", "")):
                return False
        return True

    def publish(self, parent_page_id: str, dashboard: Dashboard) -> Optional[str]:
        """建立或更新儀表板頁面，回傳頁面 ID；失敗回傳 None。"""
        page_blocks = build_blocks(dashboard)
        page_id = find_child_page(self.client, parent_page_id, PAGE_TITLE)

        if page_id is None:
            print("[Error] 讀不到父頁面的子頁清單，已中止以免另外長出一頁新儀表板")
            return None

        if not page_id:
            created = self.client.create_child_page(parent_page_id, PAGE_TITLE)
            if created is None:
                return None
            page_id = created.get("id", "")

        elif not self._clear(page_id):
            print("[Error] 清除舊儀表板內容失敗，已中止以免內容疊加")
            return None

        for batch in nb.batched(page_blocks):
            if not self.client.append_blocks(page_id, batch):
                print("[Error] 寫入儀表板內容失敗")
                return None

        return page_id
