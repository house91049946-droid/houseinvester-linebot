"""
去重複化引擎 - 偵測高度重複的房產案件訊息
使用多重策略：SimHash + 關鍵欄位比對 + 時間窗口
"""
import hashlib
import re
import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher

# rapidfuzz 是更快的選項，但如果沒裝就用 difflib
try:
    from rapidfuzz import fuzz as _fuzz_lib
    def _similarity(a, b):
        return _fuzz_lib.token_sort_ratio(a, b)
except ImportError:
    def _similarity(a, b):
        return SequenceMatcher(None, a, b).ratio() * 100

from config import config

logger = logging.getLogger(__name__)


def _strip_contact_info(text: str) -> str:
    """
    清除文字中的聯絡資訊，避免共享聯絡人造成 fuzzy 去重誤判。
    移除行：
    - 聯絡/聯繫/電話/手機/LINE/line 開頭的行
    - 純電話號碼行 (09xx-xxx-xxx)
    - 類別標籤行: (買賣件...) (租件...)
    """
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # 聯絡資訊行
        if re.search(r'(聯絡|聯繫|電話|手機|LINE|line)\s*[:：]', stripped):
            continue
        # 純電話號碼 (09xx 開頭)
        if re.match(r'^09\d{2}[-\s]?\d{3}[-\s]?\d{3}$', stripped):
            continue
        # 類別標籤行 (買賣件/租件/售出 開頭)
        if re.match(r'^[\(（]\s*(買賣件|租件|售出)', stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _address_suffix(address: str) -> str:
    """
    從完整地址中提取路名後綴（只取「路/街」之後的地址部分作為比對關鍵）
    兩種地址會比對為相同：
      「台中市北屯區崇德路三段220號」 vs 「北屯區崇德路三段220號」
      「永和區中正路588號7樓」 vs 「新北市永和區中正路588號」
    關鍵：只比路名+門牌，忽略縣市區前綴和樓層資訊
    """
    # 策略：取最後一個「路」或「街」，往前取路名（避開行政區後綴）
    for ch in ("路", "街", "段"):
        idx = address.rfind(ch)
        if idx == -1:
            continue
        # 往前取 3 個字作為路名起點，但跳過行政區後綴
        road_start = max(0, idx - 3)
        district_endings = "區市縣鄉鎮村里"
        while road_start < idx and address[road_start] in district_endings:
            road_start += 1
        suffix = address[road_start:][:30]
        break

    if not suffix:
        return ""

    # 去掉括號和空白
    suffix = re.sub(r"[（）()「」【】\s]", "", suffix)

    # ── 正規化：只保留路名＋段＋號（去掉樓層等無關資訊） ──
    # 格式: XX路 X段 XXX號  → 其他都去掉
    # 格式: XX段 XXX地號    → 去掉「地號」統一格式
    # 格式: XX街 XXX號      → 保留

    # 先嘗試取到最後一個「號」為止（含號及其後的「之X」）
    m = re.match(r"^(.+?\d+號(?:之\d+)?)", suffix)
    if m:
        return m.group(1)

    # 地號格式: XX地號 → 去掉「地號」後綴
    m = re.match(r"^(.+?)地號", suffix)
    if m:
        return m.group(1)

    return suffix


class Deduplicator:
    """案件去重複化引擎"""

    def __init__(self, session_factory):
        """
        Args:
            session_factory: SQLAlchemy session factory
        """
        self.Session = session_factory

    def compute_dedup_hash(self, text: str) -> str:
        """
        計算去重標籤
        基於關鍵欄位的標準化雜湊，而非完整文字
        （因為房仲常會微調文案，但關鍵數字不會變）
        """
        # 萃取核心數字特徵（價格、坪數、樓層）
        features = []

        # 價格
        price_matches = re.findall(r"(\d+[.]?\d*)\s*[萬Ww]", text)
        if price_matches:
            features.append(f"p:{price_matches[0]}")

        # 坪數
        size_match = re.search(r"(\d+[.]?\d*)\s*坪", text)
        if size_match:
            features.append(f"s:{size_match.group(1)}")

        # 樓層
        floor_match = re.search(r"(\d+)\s*[FfＦｆ]", text)
        if floor_match:
            features.append(f"f:{floor_match.group(1)}")

        # 地址關鍵詞 (取前兩個中文字)
        address_kw = re.findall(r"([\u4e00-\u9fff]{2,4}[路街段])", text)
        for addr in address_kw[:2]:
            features.append(f"a:{addr}")

        # 格局
        room_match = re.search(r"(\d+)\s*房\s*(\d+)\s*廳", text)
        if room_match:
            features.append(f"r:{room_match.group(1)}_{room_match.group(2)}")

        # 如果特徵太少，退化成完整文字的 hash
        if len(features) < 2:
            cleaned = re.sub(r"\s+", "", text)
            return hashlib.md5(cleaned.encode()).hexdigest()[:16]

        feature_str = "|".join(sorted(features))
        return hashlib.md5(feature_str.encode()).hexdigest()[:16]

    def check_duplicate(
        self, text: str, group_id: str, source_message_id: str | None = None,
        address: str | None = None
    ) -> tuple[bool, int | None]:
        """
        檢查訊息是否為重複案件
        回傳 (是否重複, 重複來源的案件 ID)

        策略：
        0. 地址完全匹配（不限時間窗口，跨時間）
        1. 計算 dedup_hash
        2. 在時間窗口內尋找相同 hash 的案件
        3. 如果 hash 沒命中，用 fuzzy 比對做二次確認
        """
        dedup_hash = self.compute_dedup_hash(text)

        session = self.Session()
        try:
            from app.models import HousingListing

            time_window = datetime.utcnow() - timedelta(
                hours=config.DEDUP_TIME_WINDOW_HOURS
            )

            # 策略 0: 地址後綴匹配（路名+門牌，不限時間窗口）
            if address and len(address) > 4:
                addr_norm = re.sub(r"\s+", "", address)
                # 只取路名後綴：從第一個「路/街」開始到結尾
                suffix = _address_suffix(addr_norm)
                if suffix and len(suffix) >= 4:
                    # 用 LIKE 模糊比對所有已存案件的地址後綴
                    existing_addr = (
                        session.query(HousingListing)
                        .filter(HousingListing.address.contains(suffix))
                        .first()
                    )
                    if existing_addr:
                        logger.info(f"地址後綴重複: {suffix}")
                        return True, existing_addr.id

            # 策略 1: Hash 完全匹配
            existing = (
                session.query(HousingListing)
                .filter(
                    HousingListing.dedup_hash == dedup_hash,
                    HousingListing.created_at >= time_window,
                )
                .first()
            )
            if existing:
                # 排除自己跟自己比對
                if existing.source_message_id:
                    from app.models import RawMessage
                    raw = session.query(RawMessage).filter(
                        RawMessage.id == existing.source_message_id
                    ).first()
                    if raw and raw.message_id == source_message_id:
                        return False, None

                logger.info(f"Hash 匹配重複: {dedup_hash}")
                return True, existing.id

            # 策略 2: Fuzzy 文字相似度比對（對 hash 未命中但文字高度相似）
            candidates = (
                session.query(HousingListing)
                .filter(
                    HousingListing.created_at >= time_window,
                    HousingListing.category == "new_listing",
                )
                .all()
            )

            # 比對前先清除聯絡資訊，避免共享聯絡人造成誤判
            clean_text = _strip_contact_info(text)
            for candidate in candidates:
                if candidate.description and len(candidate.description) > 20:
                    clean_candidate = _strip_contact_info(candidate.description)
                    # 兩邊都去掉聯絡資訊後再比對
                    if not clean_text or not clean_candidate:
                        continue
                    similarity = _similarity(
                        clean_text[:200], clean_candidate[:200]
                    )
                    if similarity > config.DEDUP_SIMILARITY_THRESHOLD * 100:
                        logger.info(
                            f"Fuzzy 匹配重複 (相似度: {similarity}%)"
                        )
                        return True, candidate.id

            return False, None

        except Exception as e:
            logger.error(f"去重檢查失敗: {e}")
            return False, None
        finally:
            session.close()

    def check_duplicate_with_price(
        self,
        text: str,
        group_id: str,
        source_message_id: str,
        address: str | None = None
    ) -> tuple[bool, int | None, float | None]:
        """
        同 check_duplicate，但額外回傳舊案件的價格（用於降價判斷）。
        回傳 (是否重複, 重複來源的案件 ID, 舊價格)

        當 address 匹配到現有案件時，一併回傳舊價格供 pipeline 比對。
        """
        dedup_hash = self.compute_dedup_hash(text)

        session = self.Session()
        try:
            from app.models import HousingListing

            time_window = datetime.utcnow() - timedelta(
                hours=config.DEDUP_TIME_WINDOW_HOURS
            )

            # 策略 0: 地址後綴匹配 + 回傳舊價格
            if address and len(address) > 4:
                addr_norm = re.sub(r"\s+", "", address)
                suffix = _address_suffix(addr_norm)
                if suffix and len(suffix) >= 4:
                    existing = (
                        session.query(HousingListing)
                        .filter(HousingListing.address.contains(suffix))
                        .order_by(HousingListing.posted_at.desc())
                        .first()
                    )
                    if existing:
                        logger.info(f"地址後綴重複(with price): {suffix}")
                        return True, existing.id, existing.price

            # 策略 1-2 不返回舊價格（非降價場景）
            is_dup, dup_id = self.check_duplicate(
                text, group_id, source_message_id, address
            )
            if is_dup:
                return True, dup_id, None

            return False, None, None

        except Exception as e:
            logger.error(f"去重+價格檢查失敗: {e}")
            return False, None, None
        finally:
            session.close()

    def mark_duplicate(self, listing_id: int, duplicate_of_id: int):
        """標記案件為重複"""
        session = self.Session()
        try:
            from app.models import HousingListing
            listing = session.query(HousingListing).filter(
                HousingListing.id == listing_id
            ).first()
            if listing:
                listing.is_duplicate = True
                listing.duplicate_of_id = duplicate_of_id
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"標記重複失敗: {e}")
        finally:
            session.close()


# ─── 輔助：建立全域實例的工廠函數 ───

_deduplicator_instance = None


def get_deduplicator(session_factory=None):
    global _deduplicator_instance
    if _deduplicator_instance is None and session_factory is not None:
        _deduplicator_instance = Deduplicator(session_factory)
    return _deduplicator_instance
