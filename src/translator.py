"""標題翻譯。

依序嘗試 MyMemory 與 Google，全部失敗才退回原文：
  - Google（translate.googleapis.com）在 GitHub Actions 的機器上每個請求都回 429，
    同樣的請求在本機正常——被擋的是 Actions 的共用 IP，重試也沒用。
  - MyMemory 免金鑰，匿名每日 5,000 字；設定 MYMEMORY_EMAIL 可提高到 50,000 字。
    它不會可靠地自動偵測來源語言，所以用文字的書寫系統判斷。
"""
import html
import os
import re
from typing import Callable, List, Optional, Tuple

import requests

from config import REQUEST_TIMEOUT, USER_AGENT

TARGET_LANGUAGE = "zh-TW"

MYMEMORY_ENDPOINT = "https://api.mymemory.translated.net/get"
MYMEMORY_MAX_CHARS = 500  # 單次查詢上限，超過會回「QUERY LENGTH LIMIT EXCEEDED」
MYMEMORY_EMAIL_ENV = "MYMEMORY_EMAIL"

GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"

# 警告訊息裡每個錯誤保留的長度：requests 的錯誤會帶上含標題的整串網址
ERROR_PREVIEW_CHARS = 120

# Google 會在中文譯文裡夾零寬字元，肉眼看不到但會讓搜尋與比對失準
_ZERO_WIDTH = str.maketrans("", "", "​‌‍﻿")

_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]")
_HAN = re.compile(r"[一-鿿]")
_SENTENCE_END = re.compile(r"(?<=[。！？!?.\n])")

HttpGet = Callable[..., requests.Response]


class TranslationError(Exception):
    """翻譯服務回應了，但內容不能當譯文用。"""


def detect_language(text: str) -> str:
    """用書寫系統判斷來源語言。日文常混用漢字，所以假名要先於漢字判斷。"""
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _HAN.search(text):
        return "zh-CN"
    return "en"


def _hard_split(piece: str, limit: int) -> List[str]:
    return [piece[i : i + limit] for i in range(0, len(piece), limit)]


def split_for_limit(text: str, limit: int) -> List[str]:
    """在句子邊界切成每段不超過 limit 字的片段，接回去與原文完全相同。"""
    pieces = [
        part
        for sentence in _SENTENCE_END.split(text)
        if sentence
        for part in _hard_split(sentence, limit)
    ]

    chunks: List[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + len(piece) <= limit:
            chunks = [*chunks[:-1], chunks[-1] + piece]
        else:
            chunks = [*chunks, piece]
    return chunks


def _clean(text: str) -> str:
    return text.translate(_ZERO_WIDTH).strip()


def _mymemory_chunk(chunk: str, source: str, get: HttpGet) -> str:
    params = {"q": chunk, "langpair": f"{source}|{TARGET_LANGUAGE}"}
    email = os.environ.get(MYMEMORY_EMAIL_ENV, "").strip()
    if email:
        params = {**params, "de": email}

    response = get(
        MYMEMORY_ENDPOINT,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    # 錯誤常以 HTTP 200 回來，錯誤訊息放在譯文欄位，絕不能當成譯文
    if not isinstance(payload, dict) or not isinstance(payload.get("responseData"), dict):
        raise TranslationError("回應格式不符")
    translated = str(payload["responseData"].get("translatedText") or "")
    if str(payload.get("responseStatus")) != "200":
        raise TranslationError(payload.get("responseDetails") or translated or "未知錯誤")
    if payload.get("quotaFinished") or translated.upper().startswith("MYMEMORY WARNING"):
        raise TranslationError("今日免費額度已用完")
    return html.unescape(translated)


def _mymemory(text: str, get: HttpGet) -> str:
    source = detect_language(text)
    return _clean(
        "".join(_mymemory_chunk(chunk, source, get) for chunk in split_for_limit(text, MYMEMORY_MAX_CHARS))
    )


def _google(text: str, get: HttpGet) -> str:
    """長標題會被拆成多句回傳，每句是 [譯文, 原文, ...]，必須全部接回來。"""
    response = get(
        GOOGLE_ENDPOINT,
        params={"client": "gtx", "sl": "auto", "tl": TARGET_LANGUAGE, "dt": "t", "q": text},
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return ""
    pieces = (
        segment[0]
        for segment in payload[0]
        if isinstance(segment, list) and segment and isinstance(segment[0], str)
    )
    return _clean("".join(pieces))


PROVIDERS: Tuple[Tuple[str, Callable[[str, HttpGet], str]], ...] = (
    ("MyMemory", _mymemory),
    ("Google", _google),
)


def translate(text: str, get: HttpGet = requests.get) -> Optional[str]:
    """將標題翻譯成繁體中文；所有服務都失敗時回傳 None。

    回傳 None 而不是原文，呼叫端才分得出「翻譯成功」與「失敗退回原文」，
    進而發現服務整個掛掉。空字串不需要翻譯，原樣回傳、不算失敗。

    Args:
        text: 原文標題。
        get: 可注入的 HTTP GET，方便測試。
    """
    if not text:
        return text

    errors: List[str] = []
    for name, provider in PROVIDERS:
        try:
            result = provider(text, get)
        except (requests.RequestException, ValueError, TranslationError) as error:
            errors.append(f"{name}: {str(error)[:ERROR_PREVIEW_CHARS]}")
            continue
        if result:
            return result
        errors.append(f"{name}: 譯文是空的")

    print(f"    [Warning] 翻譯失敗，改用原文: {'；'.join(errors)}")
    return None


def translate_title(text: str, get: HttpGet = requests.get) -> str:
    """將標題翻譯成繁體中文，所有服務都失敗時回傳原文。

    翻譯服務不穩定是可預期的，因此失敗只降級成原文而不中斷整輪監控；
    已經是繁體中文的來源請在設定中加上 `"translate": False` 略過。
    """
    result = translate(text, get)
    return text if result is None else result
