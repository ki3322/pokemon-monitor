"""帶重試與退避的 HTTP 取得工具。

所有對外請求都經過這裡，讓單次瞬斷不會導致整個來源在該輪被略過。
"""
import time
from typing import Optional

import requests

from config import REQUEST_TIMEOUT, USER_AGENT

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2

# 只有這些狀態碼值得重試；4xx（除了 429）重試也不會變好
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_retryable(error: requests.RequestException) -> bool:
    response = getattr(error, "response", None)
    if response is None:
        # 連線失敗、逾時、DNS 問題等，重試有意義
        return True
    return response.status_code in RETRYABLE_STATUS


def fetch(
    url: str,
    max_attempts: int = MAX_ATTEMPTS,
    backoff: float = BACKOFF_SECONDS,
    sleep=time.sleep,
) -> Optional[requests.Response]:
    """取得網址內容，失敗時回傳 None 並印出原因。

    Args:
        url: 目標網址。
        max_attempts: 最多嘗試次數。
        backoff: 退避基準秒數，第 n 次失敗後等待 backoff * n 秒。
        sleep: 可注入的等待函式，方便測試。
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt >= max_attempts or not _is_retryable(error):
                break
            sleep(backoff * attempt)

    print(f"    [Error] 取得 {url} 失敗: {last_error}")
    return None
