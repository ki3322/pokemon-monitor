# Pokemon Monitor

自動監控 Pokemon 相關網站和 Twitter 帳號，有新內容時透過 Telegram 發送通知。

## 監控目標

### 網站
- Pokemon GO Hub — https://pokemongohub.net/ (RSS)
- Serebii.net — https://www.serebii.net/ (爬蟲)
- Pokemon Information — https://pokemon-infomation.com/ (爬蟲)
- PokeBeach — https://www.pokebeach.com/ (爬蟲)
- 玩具人 寶可夢 / 寶可夢中心 — https://www.toy-people.com/ (爬蟲，兩個標籤共用去重群組)

### Twitter 帳號（透過 RSSHub）
- @PokemonGoApp
- @Zabi_pokeka
- @pokecamatomeru
- @UniteVids
- @pokerapidinfo
- @pokepoke_GW
- @pokemongoappko

## 設定步驟

### 1. 建立 Telegram Bot

1. 在 Telegram 中搜尋 @BotFather
2. 發送 `/newbot` 並依照指示建立機器人
3. 記下 Bot Token（格式：`123456789:ABC-DEF...`）
4. 與你的 Bot 開啟對話，發送任意訊息
5. 取得你的 Chat ID：
   - 訪問 `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - 找到 `"chat":{"id":123456789}` 中的數字

### 2. 設定 GitHub Secrets

在你的 GitHub repository 中：

1. 前往 **Settings** → **Secrets and variables** → **Actions**
2. 點擊 **New repository secret**
3. 新增以下 secrets：
   - `TELEGRAM_BOT_TOKEN`: 你的 Bot Token
   - `TELEGRAM_CHAT_ID`: 你的 Chat ID

（選填）在同一頁的 **Variables** 分頁可設定 `RSSHUB_INSTANCE` 來改用其他 RSSHub 實例。

### 3. 啟用 GitHub Actions

1. 前往 repository 的 **Actions** 頁面
2. 啟用 workflows（如果需要的話）
3. 可以手動點擊 **Run workflow** 測試

## 本地執行

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

python -m src.main
```

不設定 Telegram 環境變數時會以試跑模式執行：只印出結果，不發送通知也不寫入已讀記錄。

## 執行測試

```bash
pip install -r requirements-dev.txt
python -m pytest --cov
```

## Notion 撰稿流程（選填）

除了 Telegram 通知，新聞也可以同步進 Notion，讓你勾選要寫成文章的項目，寫完後一行指令回寫。

### 設定

1. 到 [My integrations](https://www.notion.so/my-integrations) 建立 integration，取得 token
2. 在 Notion 開一個頁面當容器，點右上 **...** → **Connections** → 加入該 integration
3. 建立資料庫：

```bash
export NOTION_TOKEN=secret_...
python scripts/setup_notion.py <該頁面的網址>
```

腳本會印出 `NOTION_DATABASE_ID`，把它連同 `NOTION_TOKEN` 加進 GitHub Secrets（監控用）與本機環境變數（撰稿用）。

未設定 Notion 時，監控會自動略過同步，不影響 Telegram 通知。

### 使用

1. 監控排程把新聞推進 Notion，狀態為「待處理」
2. 在 Notion 勾選 **寫成文章** 欄位
3. 在本機用 Claude Code 執行 `/write-articles`，它會：
   - `python -m src.cli pending` 抓出勾選項目與原文，產生 `drafts/*.brief.md`
   - 依 `pokemonhubscom-writer` 規範撰稿
   - `python -m src.cli publish <page_id> --file <稿件>` 回寫 Notion
4. 打開該 Notion 頁面，展開 **📋 WordPress HTML**，點複製鈕
5. 貼進 WordPress 的「程式碼編輯器」

也可以手動跑各步驟：

```bash
python -m src.cli list                                    # 列出勾選項目
python -m src.cli pending                                 # 抓原文、產生摘要檔
python -m src.cli publish <page_id> --file drafts/x.md    # 回寫 Notion
```

### 資料庫欄位

| 欄位 | 型別 | 說明 |
|---|---|---|
| 標題 | title | 新聞標題；發布後會換成定稿標題 |
| 原始標題 | rich_text | 監控抓到的原文標題，發布時不會被覆寫 |
| 連結 | url | 來源原文網址 |
| 來源 | rich_text | Serebii.net / PokeBeach / @PokemonGoApp… |
| 類型 | select | 文章 / 推文 |
| 發現時間 | date | 監控抓到的時間 |
| 新鮮度 | formula | 由發現時間換算：🔥 今天 / 🟡 3 天內 / ⚪ 一週內 / 🕓 較舊 |
| **寫成文章** | checkbox | **← 你勾這個** |
| 狀態 | select | 待處理 / 撰寫中 / 已完成 / 略過 |
| 上稿 | formula | WordPress 欄位有值就是 ✅ 已上稿，否則 ⬜ 未上稿 |
| 項目ID | rich_text | 對應監控的去重 ID |
| WordPress | url | 上稿後回填 |

「狀態＝已完成」只代表稿子寫完；有沒有真的貼上 WordPress 看「上稿」欄，它由 WordPress 網址自動推導，不必再手動維護第二個狀態。

### 刪除不會用的新聞

把不會寫的新聞狀態改成「略過」，再執行：

```bash
python -m src.cli notion-cleanup --dry-run   # 先看會刪哪些
python -m src.cli notion-cleanup
```

這是**可還原的軟刪除**：頁面進 Notion 垃圾桶，30 天內都能救回。
Notion API 沒有永久刪除的端點，要真的清空只能在 Notion 介面上操作。

刪掉不會讓監控把同一則再抓回來——去重靠 `state.json` 的投遞記錄，
與資料庫裡有沒有那一頁無關。

#### 在 Notion 加一鍵刪除按鈕（手動，30 秒）

Notion 的按鈕屬性**無法由 API 建立**，要自己在介面上加：

1. 資料庫右側 `+` → 新增屬性 → 型別選 **按鈕（Button）**
2. 名稱填「刪除」
3. 動作選 **刪除頁面（Delete page）**，或選 **編輯屬性 → 狀態 → 略過**
   （後者搭配上面的指令批次清除，誤刪時還有一次反悔機會）
4. 完成

### 補回初始化跳過的既有文章

新啟用 Notion 時，第一輪只會把現況標記為已投遞而不建立頁面（避免一次湧入整頁）。
那些既有文章不會自動進資料庫，要補的話執行：

```bash
python -m src.cli notion-backfill --dry-run   # 先看會建立哪些
python -m src.cli notion-backfill
```

只補 Notion，不碰 Telegram，也不改投遞記錄，所以重跑監控不會重複通知。
以「項目ID」去重，可以重複執行。

### 升級既有資料庫

欄位定義變更後，用這個指令把既有資料庫補齊（**只補不改**，可重複執行）：

```bash
python -m src.cli notion-upgrade --backfill
```

`--backfill` 會把既有項目空白的「原始標題」用目前的標題補上。注意已經發布過的項目，
標題早就被換成定稿標題了，補進去的會是定稿標題而不是真正的原文標題——這是無法還原的。

> **為什麼不用 Notion 的「Export → HTML」？** Notion API 沒有匯出端點，那是純 UI 功能；而且它匯出的 HTML 夾帶大量 Notion 自己的 class 與 `<div>` 包裝，貼進 WordPress 還要再清一次。這裡改由程式直接產生乾淨的語意化 HTML（只有 `<h2>` / `<p>` / `<ul>` / `<a>`，沒有 class、沒有 inline style），樣式完全交給你的佈景主題。

## 狀態儀表板

把目前的監控狀態渲染成一頁自足的 HTML（無外部資源，直接用瀏覽器開）：

```bash
python -m src.cli dashboard
```

預設輸出到 `drafts/dashboard.html`，可用 `--output` 換路徑。內容包含：

- **流程漏斗**：監控來源 → Telegram → Notion → 撰寫中 → 已成稿
- **待撰稿佇列**：Notion 中已勾選「寫成文章」且未完成的項目
- **最近新聞**：Notion 資料庫最近 30 則（新鮮度、來源、狀態、可點連結），附各狀態統計
- **各來源群組**：記錄筆數、是否已初始化、是否已達 100 筆上限
- **撰稿進度**：`drafts/` 目錄裡每份稿件的狀態

佇列與最近新聞需要 `NOTION_TOKEN` 與 `NOTION_DATABASE_ID`（產生時即時查詢 Notion）。
未設定時這兩區會顯示設定指引；查詢失敗則明確標示失敗（儀表板其餘部分照常產生），
兩種情況的訊息不同，看訊息就知道要修什麼。網頁版的新鮮度按日曆日計算，
所以「🔥 今天」不含昨天（Notion 的公式欄位是以 24 小時計）。

狀態檔還是舊格式時（`STATE_VERSION` 不符），儀表板會直接標示「下一輪重新初始化」，
而不是顯示一組其實不會被採用的數字。

### 寫進 Notion

```bash
python -m src.cli dashboard --notion <父頁面網址或 ID>
```

會在該頁底下建立（或更新）一個名為 **📊 監控儀表板** 的子頁。重複執行是更新同一頁，
不會一直長出新頁；清除舊內容失敗時會直接中止，避免疊出兩份。

需要 `NOTION_TOKEN`，而且那個父頁面要先分享給 integration
（該頁右上「⋯」→ Connections）。

Notion 沒有自訂 CSS，能遷移的只有色塊、標題階層與分欄：黃底標註為主、橘／粉作強調、
數字用 `heading_1` 撐大、進度用 `████░░░░░░` 字元量表。膠囊形狀、傾斜與浮動圖形無法遷移，
也刻意不用圖片假造。

視覺套用 [Antoniouve 設計系統](https://opendesign.cc/packs/antoniouve/)（OpenDesign design-pack/v1）。
所有 token 集中在 `src/dashboard/theme.py`，只搬設計語言，未使用該站的品牌資產或文案。

## 專案結構

```
pokemon-monitor/
├── .github/workflows/monitor.yml  # GitHub Actions 設定
├── src/
│   ├── main.py                    # 主程式與監控流程
│   ├── models.py                  # 共用資料模型與項目 ID
│   ├── state.py                   # 投遞記錄（多目的地、原子寫入）
│   ├── sinks.py                   # 投遞目的地（Telegram / Notion）
│   ├── notifier.py                # Telegram 通知
│   ├── translator.py              # 標題翻譯
│   ├── http_client.py             # 帶重試的 HTTP 取得
│   ├── cli.py                     # 撰稿流程指令列
│   ├── monitors/
│   │   ├── rss_monitor.py         # RSS 與 Twitter 監控
│   │   └── web_scraper.py         # 網頁爬蟲
│   ├── article/
│   │   ├── markdown.py            # Markdown → 中介結構
│   │   ├── html.py                # 中介結構 → WordPress HTML
│   │   ├── extractor.py           # 來源原文抽取
│   │   └── brief.py               # 撰稿摘要檔
│   ├── dashboard/
│   │   ├── theme.py               # Antoniouve 設計 token
│   │   ├── css.py                 # 由 token 產生的樣式表
│   │   ├── stats.py               # 統計計算（純函式）
│   │   ├── collect.py             # 讀狀態檔與草稿目錄
│   │   └── render.py              # 儀表板 HTML
│   └── notion/
│       ├── client.py              # Notion API 用戶端
│       ├── ids.py                 # 頁面 ID / 網址解析
│       ├── schema.py              # 資料庫欄位定義
│       ├── blocks.py              # 中介結構 → Notion 區塊
│       ├── sync.py                # 監控 → Notion
│       ├── reader.py              # 讀取勾選項目
│       ├── upgrade.py             # 既有資料庫的欄位升級
│       ├── dashboard.py           # 儀表板 → Notion 頁面
│       └── writer.py              # 文章 → Notion 頁面
├── scripts/setup_notion.py        # 一次性建立 Notion 資料庫
├── .claude/skills/write-articles/ # Claude Code 撰稿流程
├── tests/                         # 測試與 HTML fixtures
├── config.py                      # 設定檔
├── state.json                     # 已讀記錄
└── requirements.txt               # Python 依賴
```

## 自訂監控目標

編輯 `config.py`：

- `RSS_SOURCES`: RSS feed 來源
- `SCRAPE_SOURCES`: 需要爬蟲的網站
- `TWITTER_ACCOUNTS`: Twitter 帳號列表

每個來源支援的欄位：

| 欄位 | 必填 | 說明 |
|---|---|---|
| `name` | 是 | 顯示在通知中的名稱 |
| `url` | 是 | 來源網址 |
| `group` | 否 | 共用已讀記錄的群組，用於避免同一篇文章在多個標籤頁重複通知（預設為 `name`） |
| `translate` | 否 | 是否翻譯標題（預設 `True`；已是繁體中文的來源請設為 `False`） |

新增爬蟲來源時，必須同時在 `src/monitors/web_scraper.py` 的 `SCRAPERS` 中註冊對應的網域與函式，否則程式會在啟動時直接報錯。

## 運作方式

- **去重**：每則內容的 ID 由「連結（或 RSS guid）」雜湊而成，**不包含標題**。因為 Serebii 的當日彙整標題會整天累加、Pokemon Information 的標題含最後更新日期，把標題納入雜湊會讓同一篇文章被反覆通知。
- **初次初始化**：新來源（或狀態檔重置後）的第一輪只記錄現況、不發送通知，避免一次湧出整頁內容。
- **失敗重試**：只有成功送出的通知才會標記為已讀，發送失敗的項目會在下一輪重試。
- **監控失效告警**：超過半數的 Twitter 帳號或網頁來源抓取失敗時會發出警告，並有 12 小時冷卻避免重複轟炸。

## 注意事項

- Twitter 監控透過 RSSHub 實例，可能偶爾不穩定
- 網頁爬蟲可能因網站改版而需要調整；大量來源同時失敗時會收到 Telegram 警告
- GitHub Actions 免費帳號每月有 2000 分鐘執行限制
- `state.json` 的格式版本變更時（`src/state.py` 的 `STATE_VERSION`）會捨棄舊記錄並重新初始化一次
