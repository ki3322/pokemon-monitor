"""儀表板樣式表。

完全由 theme.py 的 token 驅動，只有兩處刻意的衍生值（都在下方註明理由）：
  1. --type-ui：原始字階從 body 26px 直接跳到 small 9px，中間沒有可用於
     密集數據的尺寸，因此在兩者之間補一級。
  2. --accent-*：原始 spec 的 accent 為 null，取自禁用清單描述的橘／粉點綴。

樣式依頁面區段拆成常數，stylesheet() 依序串接。
"""
from src.dashboard.theme import css_variables

_BASE = """
* { box-sizing: border-box; }

body {
  margin: 0;
  /* 禁用清單第一條：不使用白色或深色背景 */
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font);
  font-size: var(--type-ui);
  line-height: 1.45;
  overflow-x: hidden;
}
"""

_DECORATIONS = """
/* 裝飾圖形：散佈、絕對定位、彼此重疊——版面骨架就是這樣定義的 */
.canvas {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}
.blob {
  position: absolute;
  border: var(--border);
  animation: drift var(--duration-medium) var(--easing) both;
}
.blob--circle { border-radius: var(--radius-pill); }
.blob--squish { border-radius: var(--radius-md); }

@keyframes drift {
  from { opacity: 0; transform: translateY(24px) scale(0.9); }
  to   { opacity: 1; transform: none; }
}
@keyframes float {
  from { transform: translateY(0) rotate(var(--tilt, 0deg)); }
  to   { transform: translateY(-14px) rotate(var(--tilt, 0deg)); }
}
.blob {
  animation: drift var(--duration-medium) var(--easing) both,
             float 6s var(--easing) infinite alternate;
}

.page {
  position: relative;
  z-index: 1;
  max-width: var(--container);
  margin: 0 auto;
  padding: var(--space-48) var(--space-32) var(--space-96);
}
"""

_PILLS = """
/* ------------------------------------------------------------------ 藥丸 */
.pill {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-8) var(--space-24);
  border: var(--border);
  border-radius: var(--radius-pill);
  background: transparent;
  font-size: var(--type-ui);
  white-space: nowrap;
  transition: transform var(--duration-small) var(--easing);
}
.pill:hover { transform: translateY(-3px); }
.pill--label {
  font-size: var(--type-label);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: var(--space-4) var(--space-16);
}
.pill--orange { background: var(--accent-orange); }
.pill--pink   { background: var(--accent-pink); }
.pill--cream  { background: var(--accent-cream); }
.pill--muted  { color: var(--muted); border-color: var(--muted); }
"""

_HERO = """
/* ------------------------------------------------------------------ 首屏 */
.hero { margin-bottom: var(--space-64); }
.hero__figure {
  font-size: clamp(72px, 14vw, var(--type-display));
  line-height: var(--lh-display);
  font-weight: var(--weight-display);
  letter-spacing: var(--ls-display);
  margin: var(--space-24) 0 var(--space-8);
}
.hero__figure small {
  font-size: clamp(20px, 3vw, 34px);
  letter-spacing: 0;
}
.hero__title {
  font-size: var(--type-h1);
  line-height: var(--lh-h1);
  font-weight: var(--weight-h1);
  margin: 0 0 var(--space-16);
  max-width: var(--paragraph, 1280px);
}
.hero__row { display: flex; flex-wrap: wrap; gap: var(--space-8); }
"""

_SECTIONS = """
/* ------------------------------------------------------------------ 區塊 */
.section { margin-top: var(--space-64); }
.section__head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--space-16);
  margin-bottom: var(--space-24);
}
.section__title {
  font-size: var(--type-h1);
  line-height: var(--lh-h1);
  font-weight: var(--weight-h1);
  margin: 0;
}
.section__note { color: var(--muted); font-size: var(--type-ui); }

/* 刻意不用固定欄數的網格：禁用清單禁止僵化對齊 */
.scatter {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gutter);
  align-items: flex-start;
}
"""

_CARDS = """
/* ------------------------------------------------------------------ 卡片 */
.card {
  /* 上限避免最後一列只剩一張卡時被拉成整條橫幅 */
  flex: 1 1 280px;
  max-width: 420px;
  border: var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-24);
  /* 實心底色（仍是同一片黃）：讓散佈圖形留在留白處，不會透到數據後面 */
  background: var(--bg);
  transform: rotate(var(--tilt, 0deg));
  transition: transform var(--duration-small) var(--easing),
              background-color var(--duration-small) var(--easing);
}
.card:hover { transform: rotate(0deg) translateY(-6px); background: var(--accent-cream); }
.card__name {
  font-size: var(--type-body);
  line-height: 1.15;
  font-weight: var(--weight-body);
  margin: 0 0 var(--space-8);
  word-break: break-word;
}
.card__members { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-bottom: var(--space-16); }
.card__chip {
  border: 1px solid var(--muted);
  border-radius: var(--radius-pill);
  padding: 2px var(--space-8);
  font-size: var(--type-label);
  color: var(--muted);
}
.card__figure {
  font-size: 48px;
  line-height: 1;
  font-weight: var(--weight-display);
  letter-spacing: var(--ls-display);
}
.card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  margin-top: var(--space-16);
}

/* 進度條：用邊框與實心填色表現，不用陰影 */
.bar {
  height: 12px;
  border: var(--border);
  border-radius: var(--radius-pill);
  overflow: hidden;
  margin-top: var(--space-16);
}
.bar__fill {
  height: 100%;
  background: var(--ink);
  transition: width var(--duration-medium) var(--easing);
}
.bar__fill--orange { background: var(--accent-orange); }
.bar__fill--empty  { background: transparent; }
"""

_FUNNEL = """
/* ------------------------------------------------------------------ 漏斗 */
.funnel { display: flex; flex-wrap: wrap; gap: var(--space-16); align-items: stretch; }
.stage {
  flex: 1 1 180px;
  border: var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-24);
  background: var(--bg);
  transform: rotate(var(--tilt, 0deg));
  transition: transform var(--duration-small) var(--easing);
}
.stage:hover { transform: rotate(0deg) scale(1.03); }
.stage__count {
  font-size: 64px;
  line-height: 1;
  font-weight: var(--weight-display);
  letter-spacing: var(--ls-display);
}
.stage__label { font-size: var(--type-ui); margin-top: var(--space-8); }
.stage__note { font-size: var(--type-label); color: var(--muted); }
"""

_LISTS = """
/* ------------------------------------------------------------------ 清單 */
.rows { display: flex; flex-direction: column; gap: var(--space-8); }
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-16);
  border: var(--border);
  border-radius: var(--radius-pill);
  padding: var(--space-8) var(--space-24);
  background: var(--bg);
  transition: transform var(--duration-small) var(--easing);
}
.row:hover { transform: translateX(6px); }
.row__name { font-family: var(--font); word-break: break-all; }
.row__name a { color: var(--ink); }
.row__meta { display: flex; align-items: center; gap: var(--space-8); white-space: nowrap; }

.empty {
  border: 1px dashed var(--muted);
  border-radius: var(--radius-md);
  padding: var(--space-32);
  color: var(--muted);
  text-align: center;
}

.foot {
  margin-top: var(--space-96);
  padding-top: var(--space-24);
  border-top: var(--border);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-16);
  justify-content: space-between;
  font-size: var(--type-label);
  color: var(--muted);
}
.foot a { color: var(--ink); }
"""

_RESPONSIVE = """
@media (max-width: 768px) {
  .page { padding: var(--space-32) var(--space-16) var(--space-64); }
  .card, .stage { transform: none; }
  .card__figure { font-size: 40px; }
  .stage__count { font-size: 48px; }
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


def _root() -> str:
    return f""":root {{
{css_variables()}
  /* 字階補級：26px 與 9px 之間沒有適合密集數據的尺寸 */
  --type-ui: 15px;
  --type-label: 11px;
}}
"""


def stylesheet() -> str:
    return "".join(
        (
            _root(),
            _BASE,
            _DECORATIONS,
            _PILLS,
            _HERO,
            _SECTIONS,
            _CARDS,
            _FUNNEL,
            _LISTS,
            _RESPONSIVE,
        )
    )
