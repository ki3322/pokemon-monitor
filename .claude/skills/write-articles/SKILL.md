---
name: write-articles
description: 把 Notion 中勾選的 Pokemon 新聞寫成 PokemonHubs.com 文章，並回寫 Notion（原生排版 + 可貼上 WordPress 的 HTML）。當使用者說「寫文章」「處理勾選的新聞」「跑撰稿流程」時使用。
---

# PokemonHubs 撰稿流程

把 Notion 資料庫中勾選「寫成文章」的新聞，逐則寫成可直接上稿的文章。

## 前置檢查

確認環境變數已設定，未設定就先告訴使用者並停止：

```bash
python -m src.cli list
```

若回報 Notion 未設定，請使用者先 `export NOTION_TOKEN=...` 與 `export NOTION_DATABASE_ID=...`。

## 步驟

### 1. 抓取勾選項目與原文

```bash
python -m src.cli pending
```

這會在 `drafts/` 產生每則新聞的 `<slug>.brief.md`，內含 `page_id`、來源連結與抓回的原文內容。

若某則回報「原文抓取失敗」，用 WebFetch 讀取該則的來源連結補上內容；仍取不到就跟使用者確認是否略過該則。

### 2. 逐則撰稿

**每一則都必須先呼叫 `anthropic-skills:pokemonhubscom-writer` skill**，完全依照該 skill 的規範撰寫 —— 繁體中文台灣用語、文章結構、SEO/GEO 規則、事實查證守則。不要憑印象寫。

依該 skill 的「時效查證」要求，涉及發售日、數值、機制等會變動的事實，先用 WebSearch 確認再寫。

稿件格式要求：

- 用 Markdown，**第一行是 `# 文章標題`**（會自動同步成 Notion 頁面標題，正文不會重複出現）
- 段落標題用 `##`（H2）與 `###`（H3）
- 支援：粗體 `**`、斜體 `*`、行內程式碼、連結 `[文字](網址)`、無序與有序清單、引用 `>`、分隔線
- 文末保留該 skill 要求的「發布資訊」（Meta Title / Meta Description / 建議 URL / 主關鍵字 / 更新日期）

存成 `pending` 指令印出的路徑：`drafts/<slug>.article.md`

### 3. 回寫 Notion

```bash
python -m src.cli publish <page_id> --file drafts/<slug>.article.md --draft
```

`--draft` 把狀態設為「撰寫中」而不是「已完成」，稿子停在等人審的位置。
是使用者在互動中親自要求發布定稿時，才省略 `--draft`。

`page_id` 取自該則的 brief 檔開頭。這會：

- 清除頁面既有內容（避免重複發布疊加兩份）
- 寫入來源連結、摺疊的 WordPress HTML 區塊、以及 Notion 原生排版的文章
- 把頁面標題更新為定稿標題，狀態設為「撰寫中」（帶 `--draft` 時）

### 4. 回報

處理完所有項目後，列出每則的標題與 Notion 狀態；有略過或需人工處理的，明確說明原因。

## 注意

- 一次處理多則時，逐則完成（寫稿 → 回寫）再進行下一則，不要全部寫完才回寫 —— 中途失敗才不會全部重來。
- `publish` 預設會清除頁面既有內容。若使用者手動在 Notion 頁面加了筆記，改用 `--append`。
- 不要編造事實。原文沒提到的數值、日期、機制一律不寫，或標「官方尚未公開」。
