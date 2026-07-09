"""
訊息分類器 - 判斷每則訊息屬於哪種類型
買賣案件 / 租賃案件 / 售出訊息 / 推文廣告 / 無關訊息 / 降價更新
"""
import re
import logging
from app.extractor import extractor
from app.normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class MessageClassifier:
    """訊息分類器"""

    # 分類權重設定
    MIN_LENGTH_FOR_LISTING = 20       # 至少要有 20 個字才可能是案件
    MIN_LISTING_KEYWORDS = 2          # 最少需要幾個房產關鍵字

    # 強烈房產訊號關鍵字 (任一出現就高度可能是案件)
    STRONG_SIGNALS = [
        "坪", "萬", "房", "廳", "衛", "建坪",
        "總價", "售價", "租金", "月租",
    ]

    # 排除關鍵字 (極高機率不是案件)
    EXCLUDE_KEYWORDS = [
        "早安", "晚安", "吃飯", "聚餐", "生日快樂",
        "恭喜發財", "新年快樂", "政治", "天氣",
        "投票", "股票", "台積電", "長輩圖", "早安圖",
        "簽到", "報到",
    ]

    # 這些關鍵字需要前後文檢查
    EXCLUDE_PATTERNS = [
        # +1 只在非樓層語境時排除 (不是 "B1+1F")
        (re.compile(r"(?<![B\d])\+1(?![FfＦｆ樓])"), True),
        # 純 "+1" 開頭或在空白後
        (re.compile(r"(?:^|\s)\+1(?:\s|$)"), True),
    ]

    # 買方需求關鍵字（非賣方案件，歸類為 inquiry）
    BUYER_REQUEST_KEYWORDS = [
        "買需", "客需", "求購", "徵求", "代尋",
        "想買", "誠買", "買方", "急尋",
    ]

    # 新聞摘要模式（每日新聞摘要有大量偽價格地址）
    NEWS_SUMMARY_PATTERNS = [
        re.compile(r"【\d{2}月\d{2}日】.*新聞"),
        re.compile(r"新聞摘要"),
        re.compile(r"☑️.*新聞"),
        re.compile(r"中部各大報.*房產新聞"),
        re.compile(r"等[\.．]{2,}\d+則新聞"),
    ]

    # 降價關鍵字
    PRICE_DROP_KEYWORDS = [
        "降價", "調降", "下修", "下殺",
        "降售", "急售", "賠售", "砍價",
    ]

    def classify(self, text: str) -> str:
        """
        分類訊息類型
        回傳: new_listing / sold / price_drop / promotion / inquiry / irrelevant
        """
        text = TextNormalizer.normalize(text)

        if not text or len(text) < 5:
            return "irrelevant"

        # 0. 排除明顯無關訊息
        if self._is_excluded(text):
            return "irrelevant"

        # 0.5 排除買方需求（非賣方/出租方案件）
        if self._is_buyer_request(text):
            logger.info(f"歸類為買方需求: {text[:60]}...")
            return "inquiry"

        # 0.6 排除新聞摘要
        if self._is_news_summary(text):
            logger.info(f"歸類為新聞摘要，跳過")
            return "promotion"

        # 0.7 降價檢查（要在售出之前，避免「降價出售」被誤判為售出）
        if any(kw in text for kw in self.PRICE_DROP_KEYWORDS):
            listing_type = extractor._detect_listing_type(text)
            if listing_type:
                logger.info(f"歸類為降價訊息: {text[:60]}...")
                return "price_drop"

        # 1. 售出/成交訊息
        if extractor.is_sold_message(text):
            return "sold"

        # 2. 推文/廣告訊息 (非案件)
        if extractor.is_promotion_message(text):
            return "promotion"

        # 3. 檢查是否有足夠長度和房產關鍵字來判斷是否為案件
        has_listing_signals = self._count_listing_signals(text) >= self.MIN_LISTING_KEYWORDS
        is_long_enough = len(text) >= self.MIN_LENGTH_FOR_LISTING
        has_strong_signal = any(sig in text for sig in self.STRONG_SIGNALS)

        if (has_listing_signals and is_long_enough) or has_strong_signal:
            # 用 extractor 確認是買賣還是租賃
            listing_type = extractor._detect_listing_type(text)
            if listing_type:
                return "new_listing"
            # 即使無法判斷買賣/租賃，有足夠訊號也算案件
            if has_strong_signal or has_listing_signals >= 3:
                return "new_listing"

        # 4. 如果有一些房產關鍵字但不足以判斷為案件 → 可能是討論/詢問
        if has_listing_signals and not is_long_enough:
            return "inquiry"

        # 5. 其他
        return "irrelevant"

    def _is_buyer_request(self, text: str) -> bool:
        """檢查是否為買方需求訊息（非賣方案件）"""
        if not text:
            return False
        # 買方關鍵字出現 + 訊息不長 → 高機率是買方需求
        buyer_hits = sum(1 for kw in self.BUYER_REQUEST_KEYWORDS if kw in text)
        if buyer_hits >= 1 and len(text) < 200:
            return True
        return False

    def _is_news_summary(self, text: str) -> bool:
        """檢查是否為每日新聞摘要"""
        if not text:
            return False
        for pat in self.NEWS_SUMMARY_PATTERNS:
            if pat.search(text):
                return True
        return False

    def _count_listing_signals(self, text: str) -> int:
        """計算文字中出現的房產相關訊號數"""
        count = 0

        # 價格訊號
        price_patterns = [
            r"\d+[萬Ww]", r"\d+[億Ee]", r"\d+[千Kk]",
            r"總價", r"售價", r"租金", r"月租",
        ]
        for pat in price_patterns:
            if re.search(pat, text):
                count += 1
                break

        # 坪數訊號
        if any(kw in text for kw in ["坪", "建坪", "權狀", "主建物", "使用坪數"]):
            count += 1

        # 格局訊號
        if any(kw in text for kw in ["房", "廳", "衛", "格局"]):
            count += 1

        # 地址訊號
        if any(kw in text for kw in ["路", "街", "巷", "號", "段"]):
            count += 1

        # 樓層訊號
        if re.search(r"\d+[FfＦｆ樓]", text):
            count += 1

        # 物件類型訊號
        type_kw = ["大樓", "公寓", "透天", "套房", "華廈", "別墅", "店面"]
        if any(kw in text for kw in type_kw):
            count += 1

        return count

    def _is_excluded(self, text: str) -> bool:
        """檢查是否為明顯無關訊息"""
        for kw in self.EXCLUDE_KEYWORDS:
            if kw in text:
                return True
        for pat, _ in self.EXCLUDE_PATTERNS:
            if pat.search(text):
                return True
        return False


# 全域分類器實例
classifier = MessageClassifier()
