"""
處理管線 - 協調所有模組處理每則訊息
完整流程: 訊息接收 → 前處理 → OCR(若圖片) → 分類 → 萃取 → 去重 → 儲存
"""
import re
import os
import logging
import datetime
from typing import Optional

from app.normalizer import TextNormalizer
from app.classifier import classifier
from app.extractor import extractor
from app.ocr_engine import ocr_engine
from app.deduplicator import Deduplicator

logger = logging.getLogger(__name__)


def split_multi_case(text: str) -> list[str]:
    """
    將一則包含多筆案件的訊息拆成個別案件文字。
    支援格式：
    - 甲:(買賣件...)  /  乙:(租件...)  /  丙:...
    - 1.(買賣...)  /  2.(租...)
    - 雙換行分隔 + 地址偵測

    Returns:
        拆分後的案件文字列表（每個元素是一筆獨立案件）。
        若無法拆分則回傳 [text]（單一案件）。
    """
    if not text or len(text) < 20:
        return [text]

    # ── 策略 1: 天干編號拆分（甲-癸） ──
    gan = r'[甲乙丙丁戊己庚辛壬癸]'
    pattern = rf'(?:^|\n)\s*({gan})\s*[、，,:：.．]\s*'

    matches = list(re.finditer(pattern, text))
    if len(matches) >= 2:
        # 找出共享聯絡資訊（在所有案件之後）
        shared_footer = ""
        last_end = matches[-1].end()
        footer_text = text[last_end:].strip()
        # 聯絡資訊的行：聯絡:xxx 或 LINE:xxx
        contact_lines = []
        for line in footer_text.split('\n'):
            line = line.strip()
            if re.search(r'(聯絡|聯繫|電話|手機|LINE|line)\s*[:：]', line):
                contact_lines.append(line)
        if contact_lines:
            shared_footer = '\n'.join(contact_lines)

        parts = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            case_text = text[start:end].strip()
            # 去除末尾可能殘留的聯絡資訊行（避免重複）
            if shared_footer:
                for cl in contact_lines:
                    case_text = case_text.replace(cl, "")
                case_text = case_text.strip()
                if case_text:
                    case_text += '\n' + shared_footer
            if case_text and len(case_text) >= 10:
                parts.append(case_text)

        if len(parts) >= 2:
            logger.info(f"天干編號拆分: {len(parts)} 筆案件")
            return parts

    # ── 策略 2: 數字編號拆分（1. 2. 3. 或 ① ② ③） ──
    num_pattern = r'(?:^|\n)\s*(\d+|[①②③④⑤⑥⑦⑧⑨⑩])\s*[、，,:：.．]\s*'
    matches = list(re.finditer(num_pattern, text))
    if len(matches) >= 2:
        # 過濾太短的匹配（避免把價格中的數字當作編號）
        valid_matches = []
        for m in matches:
            after = text[m.end():m.end() + 50]
            # 每個編號後面必須有房產相關關鍵字
            if re.search(r'[路街巷號段]|萬|坪|房|廳|租金', after):
                valid_matches.append(m)
        if len(valid_matches) >= 2:
            parts = []
            # 找出共享聯絡資訊
            shared_footer = ""
            last_end = valid_matches[-1].end()
            footer_text = text[last_end:].strip()
            contact_lines = [
                l.strip() for l in footer_text.split('\n')
                if re.search(r'(聯絡|聯繫|電話|手機|LINE|line)\s*[:：]', l.strip())
            ]
            if contact_lines:
                shared_footer = '\n'.join(contact_lines)

            for i, m in enumerate(valid_matches):
                start = m.end()
                end = valid_matches[i + 1].start() if i + 1 < len(valid_matches) else len(text)
                case_text = text[start:end].strip()
                if shared_footer:
                    for cl in contact_lines:
                        case_text = case_text.replace(cl, "")
                    case_text = case_text.strip()
                    if case_text:
                        case_text += '\n' + shared_footer
                if case_text and len(case_text) >= 10:
                    parts.append(case_text)

            if len(parts) >= 2:
                logger.info(f"數字編號拆分: {len(parts)} 筆案件")
                return parts

    # ── 策略 3: 雙換行拆分 + 地址偵測 ──
    blocks = re.split(r'\n\s*\n', text)
    if len(blocks) >= 2:
        address_blocks = [
            b.strip() for b in blocks
            if len(b.strip()) >= 10 and re.search(r'[\u4e00-\u9fff]{2,}[路街巷]', b)
        ]
        if len(address_blocks) >= 2:
            logger.info(f"雙換行地址拆分: {len(address_blocks)} 筆案件")
            return address_blocks

    return [text]  # 無法拆分，原樣傳回


class ProcessingPipeline:
    """訊息處理管線"""

    def __init__(self, session_factory, reporter=None):
        self.Session = session_factory
        self.deduplicator = Deduplicator(session_factory)
        self.normalizer = TextNormalizer()
        self.reporter = reporter  # 報表回報引擎 (可選)

    @staticmethod
    def split_multi_case(text: str) -> list[str]:
        """將一則包含多筆案件的訊息拆成個別案件（代理到模組層級函數）"""
        return split_multi_case(text)

    async def process_text_message(
        self,
        message_id: str,
        group_id: str,
        user_id: str,
        text: str,
        raw_payload: dict,
    ) -> Optional[dict]:
        """
        處理純文字訊息

        Returns:
            如果成功萃取案件，回傳 dict；否則回傳 None
        """
        # Step 0: 儲存原始訊息
        raw_msg = self._save_raw_message(
            message_id=message_id,
            group_id=group_id,
            user_id=user_id,
            message_type="text",
            text_content=text,
            raw_payload=raw_payload,
        )

        # Step 1: 文字正規化
        normalized = self.normalizer.normalize(text)
        logger.debug(f"正規化後: {normalized[:100]}...")

        # Step 2: 分類
        category = classifier.classify(normalized)
        logger.info(f"訊息分類: {category}")

        # 只處理案件和售出訊息
        if category not in ("new_listing", "sold"):
            return None

        # Step 3: NLP 萃取
        extracted = extractor.extract(normalized)

        # 信心度太低就跳過
        if extracted.confidence < 0.3:
            logger.info(f"萃取信心度太低 ({extracted.confidence:.2f})，跳過")
            return None

        # Step 4: 去重檢查
        is_dup, dup_of_id = self.deduplicator.check_duplicate(
            text=normalized,
            group_id=group_id,
            source_message_id=message_id,
            address=getattr(extracted, 'address', None),
        )
        if is_dup:
            logger.info(f"偵測到重複案件，來源 ID: {dup_of_id}")
            # 仍然儲存，但標記為重複
            listing = self._save_listing(
                raw_message=raw_msg,
                extracted=extracted,
                category=category,
                normalized_text=normalized,
                is_duplicate=True,
                duplicate_of_id=dup_of_id,
            )
            return None  # 不回傳重複案件

        # Step 5: 儲存結構化案件
        listing = self._save_listing(
            raw_message=raw_msg,
            extracted=extracted,
            category=category,
            normalized_text=normalized,
            is_duplicate=False,
        )

        logger.info(
            f"新案件: {extracted.listing_type} | "
            f"{extracted.address or '未知區域'} | "
            f"{extracted.price_wan}萬 | "
            f"{extracted.size_ping}坪 | "
            f"信心度: {extracted.confidence:.2f}"
        )

        result = {
            "listing_id": listing.id,
            "category": category,
            "listing_type": extracted.listing_type,
            "property_type": extracted.property_type,
            "price_wan": extracted.price_wan,
            "size_ping": extracted.size_ping,
            "address": extracted.address,
            "confidence": extracted.confidence,
        }

        return result

    async def process_image_message(
        self,
        message_id: str,
        group_id: str,
        user_id: str,
        image_url: str,
        raw_payload: dict,
    ) -> Optional[dict]:
        """
        處理圖片訊息：下載 → GPT Vision → tesseract OCR fallback

        Returns:
            如果萃取到案件，回傳 dict；否則回傳 None
        """
        # Step 0: 儲存原始訊息
        raw_msg = self._save_raw_message(
            message_id=message_id,
            group_id=group_id,
            user_id=user_id,
            message_type="image",
            image_url=image_url,
            raw_payload=raw_payload,
        )

        # Step 1: 下載 + GPT Vision / OCR
        image_path, ocr_text, gpt_result = await ocr_engine.process_line_image(
            message_id=message_id,
            image_url=image_url,
        )

        # 更新原始訊息中的 OCR 文字
        if ocr_text:
            self._update_raw_message_ocr(raw_msg.id, ocr_text, image_path)

        # ─── GPT Vision 成功 → 直接用結構化資料 ───
        if gpt_result and gpt_result.get("is_property") is True:
            return self._handle_gpt_result(
                gpt_result, raw_msg, message_id, group_id,
                image_path=image_path, normalized_text=None
            )

        # ─── GPT 判定不是房產 → 跳過 ───
        if gpt_result and gpt_result.get("is_property") is False:
            logger.info(f"GPT 判定不是房產圖片，跳過: {message_id}")
            return None

        # ─── Fallback: tesseract OCR → 傳統 pipeline ───
        if not ocr_text or len(ocr_text) < 10:
            logger.info(f"OCR 辨識失敗或文字不足 (<10字)，跳過: {message_id}")
            return None

        logger.info(f"OCR 辨識文字: {ocr_text[:200]}...")

        normalized = self.normalizer.normalize(ocr_text)
        category = classifier.classify(normalized)

        if category not in ("new_listing", "sold"):
            logger.info(f"分類非案件 ({category})，跳過: {message_id}")
            return None

        extracted = extractor.extract(normalized)
        if extracted.confidence < 0.3:
            logger.info(f"萃取信心度太低 ({extracted.confidence:.2f})，跳過: {message_id}")
            return None

        is_dup, dup_of_id = self.deduplicator.check_duplicate(
            text=normalized,
            group_id=group_id,
            source_message_id=message_id,
            address=getattr(extracted, 'address', None),
        )

        listing = self._save_listing(
            raw_message=raw_msg,
            extracted=extracted,
            category=category,
            normalized_text=normalized,
            is_duplicate=is_dup,
            duplicate_of_id=dup_of_id if is_dup else None,
        )

        if is_dup:
            return None

        return {
            "listing_id": listing.id,
            "category": category,
            "listing_type": extracted.listing_type,
            "property_type": extracted.property_type,
            "price_wan": extracted.price_wan,
            "size_ping": extracted.size_ping,
            "address": extracted.address,
            "confidence": extracted.confidence,
            "contact_name": None,
            "contact_phone": None,
            "contact_line": None,
            "contact_agency": None,
            "image_path": image_path if image_path else None,
        }

    def _handle_gpt_result(
        self,
        gpt: dict,
        raw_msg,
        message_id: str,
        group_id: str,
        image_path: str = "",
        normalized_text: str | None = None,
    ) -> Optional[dict]:
        """
        將 GPT Vision 回傳的結構化資料轉為 listing 儲存

        GPT 回傳的 schema:
        {
          listing_type, property_type, price_wan, size_ping,
          floor, rooms, address, community, has_parking,
          has_furniture, management_fee, building_age, description, confidence
        }
        """
        from app.extractor import ExtractedListing

        # 建立 ExtractedListing 物件（與 extractor 相容）
        extracted = ExtractedListing(
            price_wan=gpt.get("price_wan"),
            unit_price_wan_per_ping=gpt.get("unit_price_wan_per_ping"),
            size_ping=gpt.get("size_ping"),
            floor=gpt.get("floor"),
            rooms=gpt.get("rooms"),
            address=gpt.get("address"),
            community=gpt.get("community"),
            listing_type=gpt.get("listing_type"),
            property_type=gpt.get("property_type"),
            has_parking=bool(gpt.get("has_parking")),
            has_furniture=bool(gpt.get("has_furniture")),
            management_fee=gpt.get("management_fee"),
            building_age=gpt.get("building_age"),
            confidence=gpt.get("confidence", 0.8),
        )

        # 去重檢查（用描述文字或地址做 hash）
        dedup_text = gpt.get("description", "") or gpt.get("address", "") or ""
        is_dup, dup_of_id = self.deduplicator.check_duplicate(
            text=dedup_text,
            group_id=group_id,
            source_message_id=message_id,
            address=gpt.get("address"),
        )

        listing = self._save_listing(
            raw_message=raw_msg,
            extracted=extracted,
            category=gpt.get("category") or "new_listing",
            normalized_text=normalized_text or gpt.get("description", ""),
            is_duplicate=is_dup,
            duplicate_of_id=dup_of_id if is_dup else None,
        )

        # 儲存 GPT 萃取的聯絡資訊
        self._save_contact(listing, gpt)

        if is_dup:
            return None

        return {
            "listing_id": listing.id,
            "category": gpt.get("category") or "new_listing",
            "listing_type": extracted.listing_type,
            "property_type": extracted.property_type,
            "price_wan": extracted.price_wan,
            "size_ping": extracted.size_ping,
            "address": extracted.address,
            "confidence": extracted.confidence,
            "contact_name": gpt.get("contact_name"),
            "contact_phone": gpt.get("contact_phone"),
            "contact_line": gpt.get("contact_line"),
            "contact_agency": gpt.get("contact_agency"),
            "image_path": image_path,
            "description": gpt.get("description", ""),
        }

    # ─── 內部方法 ───

    def _save_raw_message(self, **kwargs) -> "RawMessage":
        """儲存原始訊息到資料庫（自動跳過重複）"""
        from app.models import RawMessage

        session = self.Session()
        try:
            # 先檢查是否已存在
            existing = (
                session.query(RawMessage)
                .filter(RawMessage.message_id == kwargs["message_id"])
                .first()
            )
            if existing:
                logger.debug(f"訊息已存在，跳過: {kwargs['message_id']}")
                return existing

            msg = RawMessage(
                message_id=kwargs["message_id"],
                group_id=kwargs["group_id"],
                user_id=kwargs["user_id"],
                message_type=kwargs["message_type"],
                text_content=kwargs.get("text_content", ""),
                image_url=kwargs.get("image_url", ""),
                raw_payload=kwargs.get("raw_payload", {}),
            )
            session.add(msg)
            session.commit()
            session.refresh(msg)
            return msg
        except Exception as e:
            session.rollback()
            logger.error(f"儲存原始訊息失敗: {e}")
            raise
        finally:
            session.close()

    def _update_raw_message_ocr(
        self, raw_msg_id: int, ocr_text: str, image_path: str
    ):
        """更新原始訊息的 OCR 文字"""
        from app.models import RawMessage

        session = self.Session()
        try:
            msg = session.query(RawMessage).filter(
                RawMessage.id == raw_msg_id
            ).first()
            if msg:
                msg.ocr_text = ocr_text
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"更新 OCR 文字失敗: {e}")
        finally:
            session.close()

    def _save_listing(
        self,
        raw_message: "RawMessage",
        extracted,
        category: str,
        normalized_text: str,
        is_duplicate: bool = False,
        duplicate_of_id: int | None = None,
    ) -> "HousingListing":
        """儲存結構化案件"""
        from app.models import HousingListing

        session = self.Session()
        try:
            dedup_hash = self.deduplicator.compute_dedup_hash(normalized_text)

            listing = HousingListing(
                source_message_id=raw_message.id,
                listing_type=extracted.listing_type,
                property_type=extracted.property_type,
                category=category,
                price=extracted.price_wan,
                unit_price=extracted.unit_price_wan_per_ping,
                size_ping=extracted.size_ping,
                floor=extracted.floor,
                rooms=extracted.rooms,
                address=re.sub(r"\s+", "", extracted.address or ""),
                community_name=extracted.community,
                description=normalized_text,
                has_parking=extracted.has_parking,
                has_furniture=extracted.has_furniture,
                deposit=extracted.deposit,
                management_fee=extracted.management_fee,
                extracted_meta=extracted.extra,
                dedup_hash=dedup_hash,
                is_duplicate=is_duplicate,
                duplicate_of_id=duplicate_of_id,
                posted_at=datetime.datetime.utcnow(),
            )
            session.add(listing)
            session.commit()
            session.refresh(listing)
            return listing
        except Exception as e:
            session.rollback()
            logger.error(f"儲存案件失敗: {e}")
            raise
        finally:
            session.close()

    def _save_contact(self, listing, gpt: dict):
        """儲存 GPT 萃取的聯絡資訊到 ContactInfo 表"""
        contact_data = {
            "name": gpt.get("contact_name"),
            "phone": gpt.get("contact_phone"),
            "line_id": gpt.get("contact_line"),
            "company": gpt.get("contact_agency"),
        }
        if not any(contact_data.values()):
            return

        from app.models import ContactInfo
        session = self.Session()
        try:
            existing = (
                session.query(ContactInfo)
                .filter(ContactInfo.listing_id == listing.id)
                .first()
            )
            if existing:
                return
            contact = ContactInfo(listing_id=listing.id, **contact_data)
            session.add(contact)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"儲存聯絡資訊失敗: {e}")
        finally:
            session.close()
