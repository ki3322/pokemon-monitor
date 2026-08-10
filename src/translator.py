"""標題翻譯。"""
from deep_translator import GoogleTranslator

TARGET_LANGUAGE = "zh-TW"


def translate_title(text: str) -> str:
    """將標題翻譯成繁體中文，失敗時回傳原文。

    翻譯服務不穩定是可預期的，因此失敗只降級成原文而不中斷整輪監控；
    已經是繁體中文的來源請在設定中加上 `"translate": False` 略過。
    """
    if not text:
        return text

    try:
        result = GoogleTranslator(source="auto", target=TARGET_LANGUAGE).translate(text)
        return result or text
    except Exception as error:  # 翻譯服務的例外型別不穩定，一律降級
        print(f"    [Warning] 翻譯失敗，改用原文: {error}")
        return text
