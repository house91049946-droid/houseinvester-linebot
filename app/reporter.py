"""
報表回報模組 - 格式化案件資訊並透過 LINE Push API 推播
支援三種模式：
  1. 即時通知：每當管線萃取到新案件，立刻推播
  2. 每日摘要：每天定時回報當日案件統計
  3. 手動查詢：透過指令主動查詢（未來可擴充）
"""
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from config import config

logger = logging.getLogger(__name__)

# ─── LINE Messaging API ───

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_MULTICAST_URL = "https://api.line.me/v2/bot/message/multicast"


class LINEPusher:
    """LINE 訊息推送器（使用同步 urllib，避免 event loop 衝突）"""

    def __init__(self, access_token: str):
        self.access_token = access_token

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _post(self, url: str, body: dict) -> bool:
        """發送 POST 請求到 LINE API"""
        try:
            data = json.dumps(body).encode("utf-8")
            req = Request(url, data=data, headers=self._auth_headers(), method="POST")
            with urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return True
                logger.warning(
                    f"LINE API 失敗: status={resp.status}"
                )
                return False
        except URLError as e:
            logger.error(f"LINE API 網路異常: {e}")
            return False
        except Exception as e:
            logger.error(f"LINE API 異常: {e}")
            return False

    def push_to_user(self, user_id: str, messages: list[dict]) -> bool:
        """推送訊息給單一使用者（Push API）"""
        body = {"to": user_id, "messages": messages}
        return self._post(LINE_PUSH_URL, body)

    def push_to_multiple(self, user_ids: list[str], messages: list[dict]) -> int:
        """推播給多位使用者（Multicast API，最多 500 人）"""
        if not user_ids:
            return 0
        body = {"to": user_ids, "messages": messages}
        if self._post(LINE_MULTICAST_URL, body):
            return len(user_ids)
        return 0


# ─── 訊息格式化 ───

TYPE_LABELS = {
    "sale": "🏠 出售",
    "rent": "🔑 出租",
    "pre_rent": "📋 預租",
}

CATEGORY_LABELS = {
    "new_listing": "新案件",
    "sold": "已成交",
    "promotion": "推文",
    "inquiry": "詢問",
}

PTYPE_LABELS = {
    "apartment": "電梯大樓",
    "condo": "公寓",
    "house": "透天/別墅",
    "studio": "套房",
    "office": "店面/商辦",
    "land": "土地",
    "parking": "車位",
    "other": "其他",
}


def format_single_listing(listing_data: dict) -> list[dict]:
    """
    將單一案件格式化成 LINE Flex Message（卡片式，含互動按鈕）

    Args:
        listing_data: 包含 listing_id, listing_type, category, property_type,
            price_wan, size_ping, floor, rooms, address, community,
            has_parking, has_furniture, description, 聯絡資訊等
    """
    lt = listing_data.get("listing_type", "")
    cat = listing_data.get("category", "")
    pt = listing_data.get("property_type")
    listing_id = listing_data.get("listing_id", "")

    type_label = TYPE_LABELS.get(lt, lt)

    # ─── 建構卡片內容區 ───
    body_contents = []

    # 狀態 Badge（置頂）
    if cat == "sold":
        body_contents.append({
            "type": "box", "layout": "horizontal",
            "contents": [{
                "type": "text", "text": "🎊 已成交",
                "color": "#E53935", "weight": "bold", "size": "sm"
            }]
        })
    elif cat == "price_drop":
        body_contents.append({
            "type": "box", "layout": "horizontal",
            "contents": [{
                "type": "text", "text": "📉 降價通知",
                "color": "#FF9800", "weight": "bold", "size": "sm"
            }]
        })

    # 案件類型（大標）
    title_text = f"{type_label}"
    if cat == "sold":
        title_text += " 🎉"
    elif cat == "price_drop":
        title_text += " ⬇️"
    body_contents.append({
        "type": "text", "text": title_text,
        "weight": "bold", "size": "lg", "wrap": True
    })

    # 地址
    addr = listing_data.get("address", "")
    if addr:
        body_contents.append({
            "type": "text", "text": f"📍 {addr}",
            "size": "sm", "color": "#555555", "wrap": True
        })

    # 社區
    community = listing_data.get("community")
    if community:
        body_contents.append({
            "type": "text", "text": f"🏢 {community}",
            "size": "sm", "color": "#555555", "wrap": True
        })

    # 物件類型 + 格局
    detail_parts = []
    ptype_label = PTYPE_LABELS.get(pt, "") if pt else ""
    if ptype_label:
        detail_parts.append(ptype_label)
    rooms = listing_data.get("rooms")
    if rooms:
        detail_parts.append(rooms)
    if detail_parts:
        body_contents.append({
            "type": "text", "text": " ".join(detail_parts),
            "size": "sm", "wrap": True
        })

    # 樓層 + 坪數 同一行
    detail_line_parts = []
    floor = listing_data.get("floor")
    if floor:
        detail_line_parts.append(f"🏗 {floor}")
    size = listing_data.get("size_ping")
    if size:
        detail_line_parts.append(f"📐 {size}坪")
    if detail_line_parts:
        body_contents.append({
            "type": "text", "text": "  ".join(detail_line_parts),
            "size": "sm", "wrap": True
        })

    # 分隔線
    body_contents.append({"type": "separator", "margin": "md"})

    # 價格
    price = listing_data.get("price_wan")
    old_price = listing_data.get("old_price_wan")
    if price:
        if lt == "rent":
            price_text = f"💰 月租 {price:.1f} 萬"
        elif cat == "price_drop" and old_price:
            drop = old_price - price
            price_text = f"💰 {old_price:.0f} 萬 → {price:.0f} 萬 (降 {drop:.0f} 萬)"
        else:
            price_text = f"💰 總價 {price:.0f} 萬"
        body_contents.append({
            "type": "text", "text": price_text,
            "weight": "bold", "size": "md", "color": "#E53935", "wrap": True
        })

    # 單價
    unit_p = listing_data.get("unit_price_wan_per_ping")
    if unit_p and lt == "sale":
        body_contents.append({
            "type": "text", "text": f"💵 單價 {unit_p:.1f} 萬/坪",
            "size": "xs", "color": "#888888", "wrap": True
        })

    # 車位 / 傢俱 / 押金 / 管理費
    extras = []
    if listing_data.get("has_parking"):
        extras.append("含車位")
    if listing_data.get("has_furniture"):
        extras.append("含傢俱")
    if listing_data.get("deposit"):
        extras.append(f"押金{listing_data['deposit']}月")
    if listing_data.get("management_fee"):
        extras.append(f"管理費{listing_data['management_fee']:.0f}元")
    if extras:
        body_contents.append({
            "type": "text", "text": "📌 " + " | ".join(extras),
            "size": "xs", "color": "#888888", "wrap": True
        })

    # 分隔線
    body_contents.append({"type": "separator", "margin": "md"})

    # 文案摘要
    desc = listing_data.get("description", "")
    if desc:
        snippet = desc[:80] + ("..." if len(desc) > 80 else "")
        body_contents.append({
            "type": "text", "text": f"📝 {snippet}",
            "size": "xs", "color": "#AAAAAA", "wrap": True, "maxLines": 3
        })

    # 聯絡資訊
    contact_parts = []
    if listing_data.get("contact_name"):
        contact_parts.append(f"👤 {listing_data['contact_name']}")
    if listing_data.get("contact_phone"):
        contact_parts.append(f"📞 {listing_data['contact_phone']}")
    if listing_data.get("contact_line"):
        contact_parts.append(f"💬 {listing_data['contact_line']}")
    if listing_data.get("contact_agency"):
        contact_parts.append(f"🏢 {listing_data['contact_agency']}")
    if contact_parts:
        body_contents.append({
            "type": "text", "text": "  ".join(contact_parts),
            "size": "xs", "wrap": True
        })

    # ─── 建構按鈕區 ───
    buttons = [
        {
            "type": "button",
            "action": {
                "type": "postback",
                "label": "✅ 已完成",
                "data": f"action=completed&listing_id={listing_id}",
                "displayText": "✅ 已完成"
            },
            "style": "primary",
            "color": "#4CAF50",
            "height": "sm"
        },
        {
            "type": "button",
            "action": {
                "type": "postback",
                "label": "⭐ 有興趣",
                "data": f"action=interested&listing_id={listing_id}",
                "displayText": "⭐ 有興趣"
            },
            "style": "primary",
            "color": "#FF9800",
            "height": "sm"
        },
        {
            "type": "button",
            "action": {
                "type": "postback",
                "label": "❌ 無興趣",
                "data": f"action=not_interested&listing_id={listing_id}",
                "displayText": "❌ 無興趣"
            },
            "style": "primary",
            "color": "#9E9E9E",
            "height": "sm"
        }
    ]

    # ─── 組裝 Flex Message Bubble ───
    bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "spacing": "sm",
            "paddingAll": "16px",
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": buttons,
            "spacing": "sm",
            "paddingAll": "12px",
        },
    }

    # 計算 altText（通知列表用的純文字摘要）
    if price:
        if lt == "rent":
            price_text = f"月租{price:.1f}萬"
        elif cat == "price_drop" and old_price:
            price_text = f"{old_price:.0f}→{price:.0f}萬"
        else:
            price_text = f"總價{price:.0f}萬"
    else:
        price_text = ""

    return [{
        "type": "flex",
        "altText": f"{type_label} {addr or ''} {price_text if price else ''}",
        "contents": bubble,
    }]


def format_multi_listing_summary(
    listings: list[dict],
    title: str = "📊 案件摘要",
    period: str = "",
) -> list[dict]:
    """
    多筆案件摘要（用於每日/每週報表）

    格式：
    📊 每日案件摘要 (2026-07-08)
    ─────────────────
    今日共 12 筆新案件
    🏠 出售 8 筆 | 🔑 出租 4 筆
    🎉 成交 3 筆
    ─────────────────
    🏠 內湖區 2680萬 25.8坪 3房2廳2衛
    🔑 大安區 月租15萬 45坪 店面
    ...
    """
    messages = []

    # 統計
    sale_count = sum(1 for l in listings if l.get("listing_type") == "sale" and l.get("category") == "new_listing")
    rent_count = sum(1 for l in listings if l.get("listing_type") == "rent")
    sold_count = sum(1 for l in listings if l.get("category") == "sold")

    header_lines = [title]
    if period:
        header_lines.append(f"📅 {period}")
    header_lines.append("─" * 20)
    header_lines.append(f"🏠 出售 {sale_count} 筆 | 🔑 出租 {rent_count} 筆")
    if sold_count:
        header_lines.append(f"🎉 成交 {sold_count} 筆")
    header_lines.append("─" * 20)

    messages.append({"type": "text", "text": "\n".join(header_lines)})

    # 逐筆列出（每 5 筆合併一條訊息避免太長）
    batch = []
    for i, l in enumerate(listings):
        lt = l.get("listing_type", "")
        cat = l.get("category", "")
        type_icon = "🏠" if lt == "sale" else "🔑" if lt == "rent" else "📋"
        cat_suffix = " 🎉已成交" if cat == "sold" else ""

        parts = [type_icon]

        addr = l.get("address", "")
        if addr:
            parts.append(addr)

        size = l.get("size_ping")
        if size:
            parts.append(f"{size}坪")

        price = l.get("price_wan")
        if price:
            if lt == "rent":
                parts.append(f"月租{price:.1f}萬")
            else:
                parts.append(f"{price:.0f}萬")

        rooms = l.get("rooms")
        if rooms:
            parts.append(rooms)

        ptype = l.get("property_type")
        if ptype:
            parts.append(PTYPE_LABELS.get(ptype, ""))

        parts.append(cat_suffix)

        batch.append(" ".join(parts))

        if len(batch) >= 5:
            messages.append({"type": "text", "text": "\n".join(batch)})
            batch = []

    if batch:
        messages.append({"type": "text", "text": "\n".join(batch)})

    return messages


# ─── 報表引擎 ───

class Reporter:
    """報表回報引擎：整合格式化 + LINE 推送"""

    def __init__(self, session_factory):
        self.Session = session_factory
        self.pusher = LINEPusher(config.LINE_CHANNEL_ACCESS_TOKEN)

    # ─── 案件萃取通知 ───

    async def notify_new_listing(self, listing_data: dict):
        """
        即時通知：當萃取到新案件時推播給所有目標使用者
        同時附上原始圖片和聯絡資訊
        """
        if not config.NOTIFY_TARGET_USER_IDS:
            return
        if not config.ENABLE_REALTIME_NOTIFY:
            return

        messages = format_single_listing(listing_data)

        # 如果有圖片，附加圖片訊息
        image_path = listing_data.get("image_path", "")
        if image_path and config.PUBLIC_BASE_URL:
            # 從本地路徑取出 message_id: "data/images/{message_id}.jpg"
            basename = os.path.basename(image_path)
            message_id = basename.replace(".jpg", "")
            image_url = f"{config.PUBLIC_BASE_URL}/images/{message_id}.jpg"
            messages.append({
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            })

        count = self.pusher.push_to_multiple(
            config.NOTIFY_TARGET_USER_IDS, messages
        )
        if count:
            logger.info(f"案件通知已發送 ({count} 位收件者)")

    async def send_daily_summary(self, target_date: str | None = None):
        """
        發送每日摘要

        Args:
            target_date: "YYYY-MM-DD"，None 表示今天
        """
        if not config.NOTIFY_TARGET_USER_IDS:
            return

        if target_date is None:
            target_date = datetime.utcnow().strftime("%Y-%m-%d")

        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        start = date_obj.replace(hour=0, minute=0, second=0)
        end = date_obj.replace(hour=23, minute=59, second=59)

        listings = self._query_listings(start, end)

        messages = format_multi_listing_summary(
            listings,
            title="📊 每日案件摘要",
            period=target_date,
        )

        if not listings:
            messages = [{
                "type": "text",
                "text": f"📊 每日案件摘要\n📅 {target_date}\n─" * 20 + "\n本日尚無新案件"
            }]

        self.pusher.push_to_multiple(
            config.NOTIFY_TARGET_USER_IDS, messages
        )

        return len(listings)

    async def send_weekly_summary(self):
        """發送每週摘要（過去 7 天）"""
        if not config.NOTIFY_TARGET_USER_IDS:
            return

        end = datetime.utcnow()
        start = end - timedelta(days=7)

        listings = self._query_listings(start, end)

        period = f"{start.strftime('%m/%d')} - {end.strftime('%m/%d')}"
        messages = format_multi_listing_summary(
            listings,
            title="📊 本週案件摘要",
            period=period,
        )

        if not listings:
            messages = [{
                "type": "text",
                "text": f"📊 本週案件摘要\n📅 {period}\n─" * 20 + "\n本週尚無新案件"
            }]

        sale_count = sum(
            1 for l in listings
            if l.get("listing_type") == "sale" and l.get("category") == "new_listing"
        )
        rent_count = sum(1 for l in listings if l.get("listing_type") == "rent")
        sold_count = sum(1 for l in listings if l.get("category") == "sold")

        total_price = sum(
            l.get("price_wan", 0) or 0
            for l in listings
            if l.get("listing_type") == "sale"
        )

        stat_lines = [
            f"📊 本週統計",
            f"📅 {period}",
            "─" * 20,
            f"總案件: {len(listings)} 筆",
            f"出售: {sale_count} 筆 (總價約 {total_price:.0f} 萬)",
            f"出租: {rent_count} 筆",
            f"成交: {sold_count} 筆",
        ]
        messages.insert(0, {"type": "text", "text": "\n".join(stat_lines)})

        self.pusher.push_to_multiple(
            config.NOTIFY_TARGET_USER_IDS, messages
        )

        return len(listings)

    def _query_listings(self, start: datetime, end: datetime) -> list[dict]:
        """查詢時段內的案件"""
        from app.models import HousingListing

        session = self.Session()
        try:
            rows = (
                session.query(HousingListing)
                .filter(
                    HousingListing.posted_at >= start,
                    HousingListing.posted_at <= end,
                    HousingListing.is_duplicate == False,
                )
                .order_by(HousingListing.posted_at.desc())
                .all()
            )

            results = []
            for r in rows:
                results.append({
                    "id": r.id,
                    "listing_type": r.listing_type,
                    "property_type": r.property_type,
                    "category": r.category,
                    "price_wan": r.price,
                    "unit_price_wan_per_ping": r.unit_price,
                    "size_ping": r.size_ping,
                    "floor": r.floor,
                    "rooms": r.rooms,
                    "address": r.address,
                    "community": r.community_name,
                    "has_parking": r.has_parking,
                    "has_furniture": r.has_furniture,
                    "deposit": r.deposit,
                    "management_fee": r.management_fee,
                    "description": r.description,
                    "posted_at": r.posted_at.strftime("%m/%d %H:%M") if r.posted_at else "",
                    "confidence": 1.0,  # 已儲存表示通過信心門檻
                })
            return results
        finally:
            session.close()

    async def send_interest_reminders(self) -> int:
        """
        提醒機制：掃描所有「有興趣」且超過 7 天未提醒的案件，
        發送提醒通知給目標使用者。
        """
        if not config.NOTIFY_TARGET_USER_IDS:
            return 0

        session = self.Session()
        try:
            from app.models import InterestStatus, HousingListing

            cutoff = datetime.utcnow() - timedelta(days=7)
            # 找「有興趣」但超過 7 天未提醒的
            rows = (
                session.query(InterestStatus)
                .filter(
                    InterestStatus.status == "interested",
                    (
                        InterestStatus.reminder_sent_at.is_(None)
                        | (InterestStatus.reminder_sent_at <= cutoff)
                    ),
                    InterestStatus.set_at <= cutoff,
                )
                .all()
            )

            reminded = 0
            for row in rows:
                listing = session.query(HousingListing).filter(
                    HousingListing.id == row.listing_id
                ).first()
                if not listing:
                    continue

                # 發送提醒卡片（附加提醒文字）
                reminder_text = (
                    "⏰ 提醒：您之前對以下案件表示有興趣，"
                    "但超過 7 天尚未處理，請注意！"
                )
                msg = {"type": "text", "text": reminder_text}

                listing_data = {
                    "listing_id": listing.id,
                    "listing_type": listing.listing_type,
                    "property_type": listing.property_type,
                    "category": listing.category,
                    "price_wan": listing.price,
                    "size_ping": listing.size_ping,
                    "floor": listing.floor,
                    "rooms": listing.rooms,
                    "address": listing.address,
                    "community": listing.community_name,
                    "has_parking": listing.has_parking,
                    "has_furniture": listing.has_furniture,
                    "deposit": listing.deposit,
                    "management_fee": listing.management_fee,
                    "description": listing.description or "",
                    "contact_name": None,
                    "contact_phone": None,
                    "contact_line": None,
                    "contact_agency": None,
                }
                card = format_single_listing(listing_data)

                self.pusher.push_to_multiple(
                    config.NOTIFY_TARGET_USER_IDS,
                    [msg] + card
                )

                # 更新提醒時間
                row.reminder_sent_at = datetime.utcnow()
                reminded += 1

            session.commit()
            logger.info(f"興趣提醒已發送: {reminded} 筆")
            return reminded
        except Exception as e:
            session.rollback()
            logger.error(f"興趣提醒發送失敗: {e}")
            return 0
        finally:
            session.close()

    async def close(self):
        pass  # urllib 不需要關閉


# 全域實例工廠
_reporter_instance: Optional[Reporter] = None


def get_reporter(session_factory=None) -> Optional[Reporter]:
    global _reporter_instance
    if _reporter_instance is None and session_factory is not None:
        _reporter_instance = Reporter(session_factory)
    return _reporter_instance
