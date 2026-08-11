#!/usr/bin/env bash
#
# 輪詢 Notion，勾選「寫成文章」的項目一出現就自動撰稿。
#
# 用你現有的 Claude 訂閱（claude -p），不需要 ANTHROPIC_API_KEY。
# 寫好的稿子狀態停在「撰寫中」等你審閱，不會自動標成已完成。
#
# 用法：
#   scripts/watch_articles.sh              # 每 10 分鐘檢查一次
#   INTERVAL=300 scripts/watch_articles.sh # 改成每 5 分鐘
#   scripts/watch_articles.sh --once       # 只跑一次就結束（給 cron 用）
#
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

INTERVAL="${INTERVAL:-600}"
PYTHON="${PYTHON:-python3}"
LOG_FILE="${LOG_FILE:-$PROJECT_DIR/drafts/watch.log}"
# 同時只允許一個實例：撰稿途中若被第二個實例插隊，會對同一頁重複寫入
LOCK_FILE="${LOCK_FILE:-$PROJECT_DIR/drafts/.watch.lock}"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$LOG_FILE"
}

check_environment() {
    if [[ -z "${NOTION_TOKEN:-}" || -z "${NOTION_DATABASE_ID:-}" ]]; then
        log "ERROR: 缺少 NOTION_TOKEN 或 NOTION_DATABASE_ID，請先 export 再執行"
        exit 1
    fi
    if ! command -v claude >/dev/null 2>&1; then
        log "ERROR: 找不到 claude 指令，請確認 Claude Code CLI 已安裝"
        exit 1
    fi
    if ! "$PYTHON" -c "import bs4" >/dev/null 2>&1; then
        log "ERROR: $PYTHON 缺少相依套件，請用有安裝 requirements.txt 的直譯器"
        log "       例如：PYTHON=/usr/local/bin/python3 scripts/watch_articles.sh"
        exit 1
    fi
}

# 有沒有待寫的項目。有 → 0，沒有 → 1，查詢失敗 → 2
has_pending() {
    local output
    output="$("$PYTHON" -m src.cli list 2>&1)"

    if grep -q "查詢失敗\|\[Error\]" <<<"$output"; then
        log "WARN: Notion 查詢失敗，本輪跳過"
        log "$output"
        return 2
    fi
    if grep -q "目前沒有勾選待寫的項目" <<<"$output"; then
        return 1
    fi

    log "發現待寫項目："
    grep -E '^\s+\[' <<<"$output" | tee -a "$LOG_FILE"
    return 0
}

run_claude() {
    log "開始撰稿..."
    # acceptEdits 讓它能寫檔；撰稿流程需要的工具明確列出，
    # 不用 bypassPermissions，避免無人看管時什麼都能執行
    if claude -p "/write-articles" \
        --permission-mode acceptEdits \
        --allowedTools "Bash Read Write Edit WebFetch WebSearch Skill" \
        >>"$LOG_FILE" 2>&1; then
        log "撰稿完成，稿件狀態為「撰寫中」，請到 Notion 審閱後改成「已完成」"
    else
        log "ERROR: claude 執行失敗（詳見 $LOG_FILE），下一輪會重試"
    fi
}

# $1 = "verbose" 時連「沒事做」也記錄。排程單次執行必須留下痕跡，
# 否則完全靜默的一輪跟「根本沒被執行」分不出來。
tick() {
    has_pending
    case $? in
        0) run_claude ;;
        1) [[ "${1:-}" == "verbose" ]] && log "沒有待寫項目" ;;
        *) : ;;  # 查詢失敗，has_pending 已記錄
    esac
    return 0
}

main() {
    check_environment

    if [[ "${1:-}" == "--once" ]]; then
        tick verbose
        return
    fi

    log "開始監看，每 ${INTERVAL} 秒檢查一次（Ctrl-C 結束）"
    while true; do
        tick
        sleep "$INTERVAL"
    done
}

# 用 flock 擋住重複執行；沒有 flock 的系統（macOS 預設）退回檢查 PID
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        echo "已有另一個 watch_articles 在執行中，結束。"
        exit 0
    fi
else
    if [[ -f "$LOCK_FILE" ]] && kill -0 "$(cat "$LOCK_FILE" 2>/dev/null)" 2>/dev/null; then
        echo "已有另一個 watch_articles 在執行中（PID $(cat "$LOCK_FILE")），結束。"
        exit 0
    fi
    echo $$ >"$LOCK_FILE"
    trap 'rm -f "$LOCK_FILE"' EXIT
fi

main "$@"
