"""把儀表板資料渲染成單一 HTML 檔。

輸出完全自足（樣式內嵌、無外部資源），可直接用瀏覽器開啟或發布。
"""
from typing import List, Sequence

from src.article.html import escape_attribute, escape_text
from src.dashboard.css import stylesheet
from src.dashboard.stats import Dashboard, DraftStat, GroupStat, NewsStat, Stage
from src.dashboard.theme import PACK_URL
from src.notion import schema
from src.state import MAX_ITEMS_PER_SOURCE, STATE_VERSION

TITLE = "寶可夢情報監控儀表板"

# 固定的傾斜角度序列：要「散佈而非對齊」，但輸出必須可重現才能測試。
_TILTS = (-1.6, 1.1, -0.7, 1.8, -1.2, 0.9, -2.0, 1.4)

# 散佈的裝飾圖形（left, top, 邊長, 形狀, 填色）
_BLOBS = (
    ("21%", "4%", 170, "circle", "var(--accent-orange)"),
    ("85%", "9%", 130, "squish", "var(--accent-pink)"),
    ("90%", "62%", 200, "circle", "var(--accent-cream)"),
    ("-3%", "70%", 150, "squish", "var(--accent-pink)"),
    ("52%", "90%", 140, "circle", "var(--accent-orange)"),
    ("68%", "2%", 80, "circle", "transparent"),
)


def tilt(index: int) -> float:
    return _TILTS[index % len(_TILTS)]


def _blobs() -> str:
    parts = []
    for index, (left, top, size, shape, fill) in enumerate(_BLOBS):
        parts.append(
            f'<span class="blob blob--{shape}" style="left:{left};top:{top};'
            f"width:{size}px;height:{size}px;background:{fill};"
            f'--tilt:{tilt(index)}deg;animation-delay:{index * 120}ms"></span>'
        )
    return f'<div class="canvas" aria-hidden="true">{"".join(parts)}</div>'


def _pill(text: str, variant: str = "") -> str:
    classes = "pill" + (f" pill--{variant}" if variant else "")
    return f'<span class="{classes}">{escape_text(text)}</span>'


def _bar(count: int, ceiling: int = MAX_ITEMS_PER_SOURCE) -> str:
    ratio = min(count / ceiling, 1.0) if ceiling else 0.0
    modifier = "empty" if count == 0 else ("orange" if ratio >= 1.0 else "")
    fill_class = "bar__fill" + (f" bar__fill--{modifier}" if modifier else "")
    return f'<div class="bar"><div class="{fill_class}" style="width:{ratio * 100:.0f}%"></div></div>'


def render_hero(dashboard: Dashboard) -> str:
    pending = len(dashboard.pending_groups)
    pills = [_pill(f"更新於 {dashboard.generated_at}", "cream")]
    pills.append(_pill(f"{len(dashboard.groups)} 個來源群組"))

    if dashboard.notion_configured:
        pills.append(_pill("Notion 已連線", "pink"))
    else:
        pills.append(_pill("Notion 未設定", "muted"))

    if dashboard.state_version != STATE_VERSION:
        # 舊格式（含完全沒有 version 欄位的 v1）會被捨棄，下一輪只記錄現況
        found = f"v{dashboard.state_version}" if dashboard.state_version else "舊格式"
        pills.append(_pill(f"狀態 {found} → 下一輪重新初始化", "orange"))
    elif pending:
        pills.append(_pill(f"{pending} 個群組待初始化", "orange"))

    return (
        '<header class="hero">'
        f'<span class="pill pill--label">Pokemonhubs · Monitor</span>'
        f'<div class="hero__figure">{dashboard.total_tracked}<small> 則追蹤中</small></div>'
        f'<h1 class="hero__title">{escape_text(TITLE)}</h1>'
        f'<div class="hero__row">{"".join(pills)}</div>'
        "</header>"
    )


def render_funnel(stages: Sequence[Stage]) -> str:
    cards = []
    for index, stage in enumerate(stages):
        cards.append(
            f'<div class="stage" style="--tilt:{tilt(index)}deg">'
            f'<div class="stage__count">{stage.count}</div>'
            f'<div class="stage__label">{escape_text(stage.label)}</div>'
            f'<div class="stage__note">{escape_text(stage.note)}</div>'
            "</div>"
        )
    return f'<div class="funnel">{"".join(cards)}</div>'


def render_group_card(group: GroupStat, index: int) -> str:
    chips = "".join(
        f'<span class="card__chip">{escape_text(member)}</span>' for member in group.members
    )

    if not group.is_bootstrapped:
        status = _pill("待初始化", "muted")
    elif group.is_saturated:
        status = _pill("記錄已滿", "orange")
    else:
        status = _pill("運作中")

    label = group.group.replace("twitter_", "@", 1)

    return (
        f'<article class="card" style="--tilt:{tilt(index)}deg">'
        f'<h3 class="card__name">{escape_text(label)}</h3>'
        f'<div class="card__members">{chips}</div>'
        f'<div class="card__figure">{group.tracked}</div>'
        f"{_bar(group.tracked)}"
        f'<div class="card__foot">{status}'
        f'<span class="stage__note">Notion {group.notion}</span></div>'
        "</article>"
    )


def render_groups(groups: Sequence[GroupStat], empty_text: str) -> str:
    if not groups:
        return f'<div class="empty">{escape_text(empty_text)}</div>'
    cards = [render_group_card(group, index) for index, group in enumerate(groups)]
    return f'<div class="scatter">{"".join(cards)}</div>'


def render_drafts(drafts: Sequence[DraftStat]) -> str:
    if not drafts:
        return '<div class="empty">還沒有稿件。在 Notion 勾選「寫成文章」後執行 pending。</div>'

    rows = []
    for draft in drafts:
        variant = "pink" if draft.has_article else "cream"
        rows.append(
            '<div class="row">'
            f'<span class="row__name">{escape_text(draft.slug)}</span>'
            f"{_pill(draft.status, variant)}"
            "</div>"
        )
    return f'<div class="rows">{"".join(rows)}</div>'


# 狀態 → pill 樣式
_STATUS_VARIANTS = {
    schema.STATUS_PENDING: "cream",
    schema.STATUS_WRITING: "orange",
    schema.STATUS_DONE: "pink",
    schema.STATUS_SKIPPED: "muted",
}


def render_news_row(item: NewsStat) -> str:
    title = escape_text(item.title or "（無標題）")
    if item.link:
        title = f'<a href="{escape_attribute(item.link)}">{title}</a>'

    source = f'<span class="card__chip">{escape_text(item.source)}</span>' if item.source else ""
    status = _pill(item.status or "—", _STATUS_VARIANTS.get(item.status, ""))

    return (
        '<div class="row">'
        f'<span class="row__name">{escape_text(item.freshness)}　{title}</span>'
        f'<span class="row__meta">{source}{status}</span>'
        "</div>"
    )


def render_news_rows(news: Sequence[NewsStat], empty_text: str) -> str:
    if not news:
        return f'<div class="empty">{escape_text(empty_text)}</div>'
    return f'<div class="rows">{"".join(render_news_row(item) for item in news)}</div>'


def render_news_sections(dashboard: Dashboard) -> List[str]:
    """Notion 新聞的兩個區塊：待撰稿佇列與最近新聞。

    沒抓到資料時（未設定或查詢失敗）改為單一區塊說明原因——
    兩種情況的訊息必須不同，使用者才知道要修什麼。
    """
    if dashboard.news is None:
        reason = (
            "Notion 查詢失敗，本次無法顯示新聞列表，請稍後重新產生。"
            if dashboard.notion_configured
            else "Notion 未設定。設定 NOTION_TOKEN 與 NOTION_DATABASE_ID 後，這裡會顯示資料庫的新聞。"
        )
        return [_section("Notion 新聞", "Pokemon 新聞待撰稿", f'<div class="empty">{escape_text(reason)}</div>')]

    counts = " · ".join(f"{status} {count}" for status, count in dashboard.news_status_counts)
    recent_note = f"最近 {len(dashboard.news)} 則" + (f"｜{counts}" if counts else "")

    return [
        _section(
            "待撰稿佇列",
            "已勾選「寫成文章」且未完成",
            render_news_rows(dashboard.queue, "沒有勾選待寫的項目。到 Notion 勾選「寫成文章」。"),
        ),
        _section(
            "最近新聞",
            recent_note,
            render_news_rows(dashboard.news, "資料庫還沒有新聞，等下一輪監控寫入。"),
        ),
    ]


def _section(title: str, note: str, body: str) -> str:
    return (
        '<section class="section">'
        '<div class="section__head">'
        f'<h2 class="section__title">{escape_text(title)}</h2>'
        f'<span class="section__note">{escape_text(note)}</span>'
        "</div>"
        f"{body}"
        "</section>"
    )


def render_body(dashboard: Dashboard) -> str:
    sections: List[str] = [
        _section("流程漏斗", "從抓取到可貼上 WordPress", render_funnel(dashboard.stages)),
        *render_news_sections(dashboard),
        _section(
            "網站來源",
            f"每個群組最多保留 {MAX_ITEMS_PER_SOURCE} 筆記錄",
            render_groups(dashboard.website_groups, "設定檔裡沒有網站來源。"),
        ),
        _section(
            "Twitter 帳號",
            "透過 RSSHub 取得",
            render_groups(dashboard.twitter_groups, "設定檔裡沒有 Twitter 帳號。"),
        ),
        _section("撰稿進度", "drafts/ 目錄", render_drafts(dashboard.drafts)),
    ]

    foot = (
        '<footer class="foot">'
        "<span>資料來源：config.py · state.json · drafts/ · Notion</span>"
        f'<span>設計語言：Antoniouve — <a href="{escape_attribute(PACK_URL)}">OpenDesign</a></span>'
        "</footer>"
    )

    return f'{_blobs()}<main class="page">{render_hero(dashboard)}{"".join(sections)}{foot}</main>'


def render_page(dashboard: Dashboard) -> str:
    """輸出完整的獨立 HTML 檔。"""
    return (
        "<!doctype html>\n"
        '<html lang="zh-Hant">\n<head>\n'
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"<title>{escape_text(TITLE)}</title>\n"
        f"<style>\n{stylesheet()}</style>\n"
        "</head>\n<body>\n"
        f"{render_body(dashboard)}\n"
        "</body>\n</html>\n"
    )
