#!/usr/bin/env bash
#
# launchd 專用的進入點，跑一次 Notion 清理。
#
# 環境處理與 watch_once_launchd.sh 相同（launchd 的 PATH 很精簡、
# 不載入 shell profile），差別只在跑的是 notion-cleanup。
#
# 清掉兩類項目：
#   - 超過 STALE_DAYS 天還沒勾選「寫成文章」的（只限狀態仍為「待處理」）
#   - 來源在 NOTION_EXCLUDED_GROUPS 裡的
#
# 手動測試（不加 --yes 只會預覽）：
#   scripts/cleanup_once_launchd.sh --dry-run
#
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

KEYCHAIN_TOKEN_SERVICE="${KEYCHAIN_TOKEN_SERVICE:-pokemon-monitor-notion-token}"
KEYCHAIN_DB_SERVICE="${KEYCHAIN_DB_SERVICE:-pokemon-monitor-notion-database}"
PYTHON_BIN="${PYTHON_BIN:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3}"

# 沒勾選的新聞放幾天後清掉
STALE_DAYS="${STALE_DAYS:-2}"

LOG_FILE="${LOG_FILE:-$PROJECT_DIR/drafts/cleanup.log}"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG_FILE"
}

keychain_read() {
    security find-generic-password -a "$USER" -s "$1" -w 2>/dev/null
}

load_credentials() {
    NOTION_TOKEN="$(keychain_read "$KEYCHAIN_TOKEN_SERVICE")"
    NOTION_DATABASE_ID="$(keychain_read "$KEYCHAIN_DB_SERVICE")"

    if [[ -z "$NOTION_TOKEN" || -z "$NOTION_DATABASE_ID" ]]; then
        log "ERROR: Keychain 讀不到 Notion 憑證（$KEYCHAIN_TOKEN_SERVICE / $KEYCHAIN_DB_SERVICE）"
        return 1
    fi

    export NOTION_TOKEN NOTION_DATABASE_ID
}

main() {
    if [[ ! -x "$PYTHON_BIN" ]]; then
        log "ERROR: 找不到直譯器 $PYTHON_BIN"
        exit 1
    fi

    load_credentials || exit 1

    # --status "" 是刻意的：這支排程只負責「沒人要的」與「排除來源」，
    # 「略過」是人工判斷的結果，留給人自己決定何時清。
    local args=(-m src.cli notion-cleanup --status "" --stale "$STALE_DAYS" --excluded)
    if [[ "${1:-}" != "--dry-run" ]]; then
        args+=(--yes)
    fi

    log "開始清理（未勾選超過 ${STALE_DAYS} 天 + 排除來源）"
    if output="$("$PYTHON_BIN" "${args[@]}" 2>&1)"; then
        printf '%s\n' "$output" >>"$LOG_FILE"
        log "清理完成"
    else
        printf '%s\n' "$output" >>"$LOG_FILE"
        log "ERROR: 清理失敗（詳見上方輸出），下一輪會重試"
        exit 1
    fi
}

main "$@"
