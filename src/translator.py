"""標題翻譯。

直接呼叫 translate.googleapis.com 的 gtx 端點，不經 deep-translator：
2026-11 觀察到 deep-translator 用的 translate.google.com/m 對每個請求都回 429，
連單次請求都會被擋，GitHub Actions 與本機皆然，所以並不是頻率問題。
"""
from typing import Callable

import requests

from config import REQUEST_TIMEOUT, USER_AGENT

TARGET_LANGUAGE = "zh-TW"
ENDPOINT = "https://translate.googleapis.com/translate_a/single"

# Google 會在中文譯文裡夾零寬字元，肉眼看不到但會讓搜尋與比對失準
_ZERO_WIDTH = str.maketrans("", "", "​‌‍﻿")


def _parse(payload: object) -> str:
    """從回應取出譯文。長標題會被拆成多句，每句是 [譯文, 原文, ...]。"""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return ""
    pieces = (
        segment[0]
        for segment in payload[0]
        if isinstance(segment, list) and segment and isinstance(segment[0], str)
    )
    return "".join(pieces).translate(_ZERO_WIDTH).strip()


def translate_title(text: str, get: Callable[..., requests.Response] = requests.get) -> str:
    """將標題翻譯成繁體中文，失敗時回傳原文。

    翻譯服務不穩定是可預期的，因此失敗只降級成原文而不中斷整輪監控；
    已經是繁體中文的來源請在設定中加上 `"translate": False` 略過。

    Args:
        text: 原文標題。
        get: 可注入的 HTTP GET，方便測試。
    """
    if not text:
        return text

    try:
        response = get(
            ENDPOINT,
            params={"client": "gtx", "sl": "auto", "tl": TARGET_LANGUAGE, "dt": "t", "q": text},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = _parse(response.json())
    except (requests.RequestException, ValueError) as error:
        print(f"    [Warning] 翻譯失敗，改用原文: {error}")
        return text

    return result or text
