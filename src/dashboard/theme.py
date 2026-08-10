"""Antoniouve 設計系統的 token（OpenDesign design-pack/v1）。

來源：https://opendesign.cc/packs/antoniouve/spec.json

這裡只搬設計語言，不搬品牌資產與文案。所有數值原樣保留，
需要為儀表板衍生的值一律標註推導依據，避免日後被誤認為原始 token。
"""
from typing import Dict, Tuple

PACK_SLUG = "antoniouve"
PACK_URL = "https://opendesign.cc/packs/antoniouve/"

# --------------------------------------------------------------- 1. 色彩
COLORS: Dict[str, str] = {
    "bg": "#FFC900",
    "ink": "#000000",
    "muted": "#7A7A7A",
    "line": "rgba(0,0,0,1.0)",
}

# spec 的 accent 為 null，但禁用清單明確指出畫面上有「飽和的黃、橘、粉」點綴，
# 且禁止柔和粉彩。資料視覺化需要能區分類別的色相，因此在該描述範圍內補三個點綴色。
ACCENTS: Dict[str, str] = {
    "orange": "#FF6B2C",
    "pink": "#FF4FA3",
    "cream": "#FFF0B3",
}

# --------------------------------------------------------------- 2. 字型
# spec 只給了「geometric-sans」這個類別，沒有指定字檔。
# 這裡用系統內建的幾何無襯線字體堆疊，避免載入外部字型（也符合 CSP 限制）。
FONT_STACK = (
    '"Avenir Next", Avenir, "Century Gothic", "Futura", '
    '"Poppins", "Nunito Sans", "PingFang TC", "Noto Sans TC", sans-serif'
)

TYPE_SCALE: Dict[str, Dict] = {
    "display": {"size": 123, "lh": 1.0, "weight": 500, "ls": "-1px"},
    "h1": {"size": 34, "lh": 1.4, "weight": 400, "ls": "0px"},
    "body": {"size": 26, "lh": 1.0, "weight": 400, "ls": "0px"},
    "small": {"size": 9, "lh": 1.0, "weight": 400, "ls": "0px"},
}

# --------------------------------------------------------------- 3. 間距
SPACING_BASE = 4
SPACING_SCALE: Tuple[int, ...] = (4, 8, 16, 24, 32, 48, 64, 96)

# --------------------------------------------------------------- 4. 表面
RADIUS: Dict[str, int] = {"sm": 17, "md": 17, "lg": 429, "pill": 429}
BORDER = "1px solid black"
# spec 的 shadows 是空陣列：這套系統完全不用陰影，深度靠邊框與重疊表現。
SHADOWS: Tuple[str, ...] = ()

# --------------------------------------------------------------- 5. 版面
CONTAINER_MAX = 1440
PARAGRAPH_MAX = 1280
GUTTER = 24
BREAKPOINTS: Tuple[int, ...] = (768, 1024)

# --------------------------------------------------------------- 6. 動效
DURATIONS: Dict[str, int] = {"micro": 450, "small": 450, "medium": 600}
EASING = "cubic-bezier(0.19, 1, 0.22, 1)"


def css_variables() -> str:
    """輸出 :root 內的 CSS 變數宣告（不含選擇器本身）。"""
    lines = [f"--{name}: {value};" for name, value in COLORS.items()]
    lines += [f"--accent-{name}: {value};" for name, value in ACCENTS.items()]
    lines.append(f"--font: {FONT_STACK};")

    for token, spec in TYPE_SCALE.items():
        lines.append(f"--type-{token}: {spec['size']}px;")
        lines.append(f"--lh-{token}: {spec['lh']};")
        lines.append(f"--weight-{token}: {spec['weight']};")
        lines.append(f"--ls-{token}: {spec['ls']};")

    for step in SPACING_SCALE:
        lines.append(f"--space-{step}: {step}px;")

    for name, value in RADIUS.items():
        lines.append(f"--radius-{name}: {value}px;")

    lines.append(f"--border: {BORDER};")
    lines.append(f"--container: {CONTAINER_MAX}px;")
    lines.append(f"--paragraph: {PARAGRAPH_MAX}px;")
    lines.append(f"--gutter: {GUTTER}px;")

    for name, value in DURATIONS.items():
        lines.append(f"--duration-{name}: {value}ms;")
    lines.append(f"--easing: {EASING};")

    return "\n".join(f"  {line}" for line in lines)
