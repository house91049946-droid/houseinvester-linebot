"""
文字正規化引擎 - 處理特殊字體、全形字、圈號數字等異體字
這是房產群組中最關鍵的前處理步驟
"""
import re
import unicodedata

# ─── Unicode 圈號數字對應表 ───
# ① ② ③ ... ⑳
CIRCLED_DIGITS = {
    "\u2460": "1", "\u2461": "2", "\u2462": "3", "\u2463": "4", "\u2464": "5",
    "\u2465": "6", "\u2466": "7", "\u2467": "8", "\u2468": "9", "\u2469": "10",
    "\u246a": "11", "\u246b": "12", "\u246c": "13", "\u246d": "14", "\u246e": "15",
    "\u246f": "16", "\u2470": "17", "\u2471": "18", "\u2472": "19", "\u2473": "20",
}

# 括號數字 (1) (2) ...
PAREN_NUMBERS = {
    "\u2474": "1", "\u2475": "2", "\u2476": "3", "\u2477": "4", "\u2478": "5",
    "\u2479": "6", "\u247a": "7", "\u247b": "8", "\u247c": "9", "\u247d": "10",
    "\u247e": "11", "\u247f": "12", "\u2480": "13", "\u2481": "14", "\u2482": "15",
    "\u2483": "16", "\u2484": "17", "\u2485": "18", "\u2486": "19", "\u2487": "20",
}

# 負圈號數字
NEGATIVE_CIRCLED = {
    "\u24ff": "0", "\u2776": "1", "\u2777": "2", "\u2778": "3", "\u2779": "4",
    "\u277a": "5", "\u277b": "6", "\u277c": "7", "\u277d": "8", "\u277e": "9",
    "\u277f": "10", "\u24eb": "11", "\u24ec": "12", "\u24ed": "13", "\u24ee": "14",
    "\u24ef": "15", "\u24f0": "16", "\u24f1": "17", "\u24f2": "18", "\u24f3": "19",
    "\u24f4": "20",
}

# 中文數字 → 阿拉伯數字 (簡易)
CHINESE_NUMERALS = {
    "零": "0", "一": "1", "二": "2", "兩": "2", "三": "3",
    "四": "4", "五": "5", "六": "6", "七": "7", "八": "8",
    "九": "9", "十": "10",
}

# 全形 ASCII → 半形 (shift JIS 常見)
def _build_fullwidth_map() -> dict:
    mapping = {}
    # 全形數字 0-9
    for i in range(10):
        mapping[chr(0xFF10 + i)] = chr(0x30 + i)
    # 全形大寫 A-Z
    for i in range(26):
        mapping[chr(0xFF21 + i)] = chr(0x41 + i)
    # 全形小寫 a-z
    for i in range(26):
        mapping[chr(0xFF41 + i)] = chr(0x61 + i)
    # 常用全形符號
    mapping["\u3000"] = " "      # 全形空白
    mapping["\uff01"] = "!"
    mapping["\uff02"] = '"'
    mapping["\uff03"] = "#"
    mapping["\uff04"] = "$"
    mapping["\uff05"] = "%"
    mapping["\uff06"] = "&"
    mapping["\uff07"] = "'"
    mapping["\uff08"] = "("
    mapping["\uff09"] = ")"
    mapping["\uff0a"] = "*"
    mapping["\uff0b"] = "+"
    mapping["\uff0c"] = ","
    mapping["\uff0d"] = "-"
    mapping["\uff0e"] = "."
    mapping["\uff0f"] = "/"
    mapping["\uff1a"] = ":"
    mapping["\uff1b"] = ";"
    mapping["\uff1c"] = "<"
    mapping["\uff1d"] = "="
    mapping["\uff1e"] = ">"
    mapping["\uff1f"] = "?"
    mapping["\uff20"] = "@"
    mapping["\uff3b"] = "["
    mapping["\uff3c"] = "\\"
    mapping["\uff3d"] = "]"
    mapping["\uff3e"] = "^"
    mapping["\uff3f"] = "_"
    mapping["\uff40"] = "`"
    mapping["\uff5b"] = "{"
    mapping["\uff5c"] = "|"
    mapping["\uff5d"] = "}"
    mapping["\uff5e"] = "~"
    return mapping

FULLWIDTH_TO_HALFWIDTH = _build_fullwidth_map()


# ─── 台灣房產常見特殊寫法正規化 ───

# 金額單位標準化 (常見: 萬、W、w、K、k、億、E)
PRICE_UNIT_PATTERNS = [
    (re.compile(r"(\d+[,.]?\d*)\s*億\s*(\d+[,.]?\d*)?\s*萬?"), "yi_wan"),  # 1億2000萬
    (re.compile(r"(\d+[,.]?\d*)\s*[萬Ww]"), "wan"),   # 1000萬, 1000W
    (re.compile(r"(\d+[,.]?\d*)\s*[千Kk]"), "qian"),  # 500K (少見但在租屋市場可能)
    (re.compile(r"(\d+[,.]?\d*)\s*[億Ee]"), "yi"),    # 1億
]

# 坪數常見寫法
SIZE_PATTERNS = [
    re.compile(r"(\d+[.]?\d*)\s*坪"),
    re.compile(r"(\d+[.]?\d*)\s*[Pp]"),
    re.compile(r"建坪\s*(\d+[.]?\d*)"),
    re.compile(r"權狀\s*(\d+[.]?\d*)"),
    re.compile(r"主建物\s*(\d+[.]?\d*)"),
]

# 特殊符號清理
NOISE_PATTERNS = [
    re.compile(r"[\U0001F300-\U0001F9FF]"),  # Emoji
    re.compile(r"[\u200B-\u200D\uFEFF]"),    # Zero-width spaces
    re.compile(r"[\u2600-\u27BF]"),          # Misc symbols
    re.compile(r"[\u2702-\u27B0]"),          # Dingbats
]


class TextNormalizer:
    """文字正規化器"""

    @staticmethod
    def normalize(text: str) -> str:
        """完整正規化流程"""
        if not text:
            return ""

        t = text

        # 1. Unicode 正規化 (NFKC 會自動轉全形->半形)
        t = unicodedata.normalize("NFKC", t)

        # 2. 手動補強全形轉半形 (有些 NFKC 不會轉)
        t = TextNormalizer._fullwidth_to_halfwidth(t)

        # 3. 圈號數字 -> 阿拉伯數字
        t = TextNormalizer._circled_to_digit(t)

        # 4. 中文數字簡易轉換
        t = TextNormalizer._chinese_num_to_arabic_simple(t)

        # 5. 清理雜訊符號
        for pat in NOISE_PATTERNS:
            t = pat.sub(" ", t)

        # 6. 多餘空白合併
        t = re.sub(r"\s+", " ", t).strip()

        # 7. 特殊字元清理 (保留中英文、數字、常用標點)
        allowed = (
            r"\u4e00-\u9fff"      # CJK 基本
            r"\u3400-\u4dbf"      # CJK Ext-A
            r"a-zA-Z0-9"          # 英數字
            r".,:;!?()/%+=\-#"    # 標點
            r"\s"                  # 空白
        )
        t = re.sub(f"[^{allowed}]", "", t)

        return t

    @staticmethod
    def normalize_price_text(text: str) -> list:
        """
        從文字中提取價格資訊
        回傳 list of (原始價格字串, 正規化後的值)
        """
        results = []
        text = TextNormalizer.normalize(text)

        for pattern, unit in PRICE_UNIT_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group(0)
                if unit == "wan":
                    val = match.group(1).replace(",", "")
                    results.append((raw.strip(), f"{val}萬"))
                elif unit == "yi":
                    val = match.group(1).replace(",", "")
                    results.append((raw.strip(), f"{val}億"))
                elif unit == "yi_wan":
                    yi = match.group(1).replace(",", "")
                    wan = match.group(2).replace(",", "") if match.group(2) else "0"
                    results.append((raw.strip(), f"{yi}億{wan}萬"))
                elif unit == "qian":
                    val = match.group(1).replace(",", "")
                    results.append((raw.strip(), f"{val}千"))

        return results

    @staticmethod
    def _fullwidth_to_halfwidth(text: str) -> str:
        result = []
        for ch in text:
            result.append(FULLWIDTH_TO_HALFWIDTH.get(ch, ch))
        return "".join(result)

    @staticmethod
    def _circled_to_digit(text: str) -> str:
        """將所有圈號數字轉為阿拉伯數字"""
        all_circled = {}
        all_circled.update(CIRCLED_DIGITS)
        all_circled.update(PAREN_NUMBERS)
        all_circled.update(NEGATIVE_CIRCLED)

        result = []
        for ch in text:
            result.append(all_circled.get(ch, ch))
        return "".join(result)

    @staticmethod
    def _chinese_num_to_arabic_simple(text: str) -> str:
        """簡單的中文數字轉換（精細轉換由 extractor 處理）"""
        for cn, ar in CHINESE_NUMERALS.items():
            text = text.replace(cn, ar)
        return text


# ─── 價格解析工具 ───

def parse_price_to_wan(price_text: str) -> float | None:
    """
    將各種價格文字轉換為統一的「萬元」數值
    
    範例:
        "1680萬" -> 1680.0
        "1.2億" -> 12000.0
        "1億2000萬" -> 12000.0
        "500K" -> 50.0
        "3.5W" -> 3.5
    """
    price_text = TextNormalizer.normalize(price_text).strip()

    # 移除千分位逗號
    price_text = price_text.replace(",", "").replace("，", "")

    # 修復 OCR 造成的數字分割: "1 188 萬" -> "1188 萬"
    price_text = re.sub(r"(\d+)\s+(\d{3,4})\s*[萬Ww]", r"\1\2萬", price_text)

    # 億+萬 組合: "1億2000萬"
    m = re.search(r"(\d+\.?\d*)億(\d+\.?\d*)?萬?", price_text)
    if m:
        yi = float(m.group(1))
        wan = float(m.group(2)) if m.group(2) else 0
        return yi * 10000 + wan

    # 億
    m = re.search(r"(\d+\.?\d*)億", price_text)
    if m:
        return float(m.group(1)) * 10000

    # 萬 / W / w（允許空格，如 "5600 萬"、"1188 萬"）
    m = re.search(r"(\d+\.?\d*)\s*[萬Ww]", price_text)
    if m:
        return float(m.group(1))

    # 千 / K / k (較少見，轉萬)
    m = re.search(r"(\d+\.?\d*)[千Kk]", price_text)
    if m:
        return float(m.group(1)) * 0.1

    # 純數字 (假設單位是萬)
    m = re.match(r"^(\d+\.?\d*)$", price_text)
    if m:
        val = float(m.group(1))
        # 判斷是否為合理房價（> 100 萬的可能性高，但避免將租金誤判）
        if val > 100:
            return val
        return None

    return None


def parse_size_to_ping(text: str) -> float | None:
    """從文字中提取坪數"""
    text = TextNormalizer.normalize(text)
    for pat in SIZE_PATTERNS:
        m = pat.search(text)
        if m:
            return float(m.group(1))
    return None


# ─── 測試 ───
if __name__ == "__main__":
    test_texts = [
        "\u2468 永和頂溪捷運站 3分鐘 1480萬 25.8坪 3房2廳2衛",
        "\u3224 大安區精華店面 1.2億 建坪45坪",
        "\u2469 已售出 恭喜成交 內湖3房 2680萬",
        "投資客 出售 598萬 15坪套房",
        "RC造 12F/5F 權狀32.5坪 1680W",
    ]

    normalizer = TextNormalizer()
    for t in test_texts:
        normalized = normalizer.normalize(t)
        prices = normalizer.normalize_price_text(t)
        wan = parse_price_to_wan(normalized)
        ping = parse_size_to_ping(normalized)
        print(f"原始: {t}")
        print(f"  -> 正規化: {normalized}")
        print(f"  -> 價格: {prices}")
        print(f"  -> 轉萬元: {wan}")
        print(f"  -> 坪數: {ping}")
        print()
