#!/usr/bin/env bash
#
# launchd 專用的進入點，跑一輪 watch_articles.sh。
#
# 存在的理由有兩個，都是 launchd 環境跟互動式 shell 的差異：
#   1. launchd 的 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，
#      claude（在 nvm 底下）與帶相依套件的 python 都不在裡面。
#   2. launchd 不會載入 ~/.zshrc，環境變數裡不會有 NOTION_TOKEN，
#      因此改由 Keychain 取出，plist 裡不留任何秘密。
#
# 手動測試（會用跟 launchd 完全相同的路徑與憑證）：
#   scripts/watch_once_launchd.sh
#
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

# Keychain 項目名稱。與 README 的設定指令、以及 plist 保持一致。
KEYCHAIN_TOKEN_SERVICE="${KEYCHAIN_TOKEN_SERVICE:-pokemon-monitor-notion-token}"
KEYCHAIN_DB_SERVICE="${KEYCHAIN_DB_SERVICE:-pokemon-monitor-notion-database}"

# 帶有 requests / bs4 的直譯器。換 Python 版本時改這裡。
PYTHON_BIN="${PYTHON_BIN:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3}"

LOG_FILE="${LOG_FILE:-$PROJECT_DIR/drafts/watch.log}"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG_FILE"
}

# nvm 的路徑含 node 版本號，寫死會在升級 node 後失效，因此逐一掃過。
add_node_to_path() {
    local dir
    for dir in "$HOME"/.nvm/versions/node/*/bin; do
        if [[ -x "$dir/claude" ]]; then
            PATH="$dir:$PATH"
        fi
    done
    PATH="$(dirname "$PYTHON_BIN"):/usr/local/bin:/opt/homebrew/bin:$PATH"
    export PATH
}

# 從 Keychain 取出單一項目；讀不到回傳非 0。
keychain_read() {
    security find-generic-password -a "$USER" -s "$1" -w 2>/dev/null
}

load_credentials() {
    NOTION_TOKEN="$(keychain_read "$KEYCHAIN_TOKEN_SERVICE")"
    NOTION_DATABASE_ID="$(keychain_read "$KEYCHAIN_DB_SERVICE")"

    if [[ -z "$NOTION_TOKEN" || -z "$NOTION_DATABASE_ID" ]]; then
        log "ERROR: Keychain 讀不到 Notion 憑證（$KEYCHAIN_TOKEN_SERVICE / $KEYCHAIN_DB_SERVICE）"
        log "       請依 README「勾選後自動撰稿」的 Keychain 設定加入項目後重試"
        return 1
    fi

    export NOTION_TOKEN NOTION_DATABASE_ID
}

main() {
    add_node_to_path

    if ! command -v claude >/dev/null 2>&1; then
        log "ERROR: PATH 中找不到 claude，請確認 Claude Code CLI 仍安裝在 nvm 的 node 底下"
        exit 1
    fi
    if [[ ! -x "$PYTHON_BIN" ]]; then
        log "ERROR: 找不到直譯器 $PYTHON_BIN，請改 PYTHON_BIN 指向有裝 requirements.txt 的 python"
        exit 1
    fi

    load_credentials || exit 1

    # watch_articles.sh 自己有檔案鎖與日誌，這裡只負責把環境備妥
    PYTHON="$PYTHON_BIN" exec "$PROJECT_DIR/scripts/watch_articles.sh" --once
}

main "$@"
