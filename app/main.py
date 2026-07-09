"""
LINE Bot Webhook 伺服器
接收 LINE 群組訊息，觸發處理管線
"""
import os
import sys
import json
import logging
import asyncio
import datetime
import threading
from pathlib import Path

from flask import Flask, request, abort

# 確保專案根目錄在 Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import config
from app.models import init_db, RawMessage
from app.pipeline import ProcessingPipeline
from app.reporter import get_reporter

# ─── 日誌設定 ───
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── 初始化 ───
app = Flask(__name__)

# 確保目錄存在
os.makedirs(config.IMAGE_DOWNLOAD_DIR, exist_ok=True)

# 初始化資料庫
Session = init_db(config.DATABASE_URL)

# 初始化報表引擎
reporter = get_reporter(Session)

# 初始化處理管線（注入 reporter）
pipeline = ProcessingPipeline(Session, reporter=reporter)


# ─── 非同步事件迴圈輔助 ───

def run_async(coro):
    """在 Flask 同步環境中執行非同步函數"""
    try:
        # Python 3.10+ 支援 asyncio.run() 可重入呼叫
        return asyncio.run(coro)
    except RuntimeError:
        # Event loop already running, create a new one
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ─── LINE Webhook ───

@app.route("/callback", methods=["POST"])
def line_callback():
    """
    LINE Webhook 端點
    接收 LINE 平台推送的所有事件（含訊息和 postback）
    """
    body = request.get_data(as_text=True)

    try:
        events = json.loads(body).get("events", [])
    except json.JSONDecodeError:
        abort(400)

    # 非同步處理每個事件
    thread_count = 0
    for event in events:
        event_type = event.get("type", "")
        if event_type == "message":
            t = threading.Thread(
                target=_handle_event, args=(event,),
                daemon=True, name=f"line-event-{thread_count}"
            )
            t.start()
            thread_count += 1
        elif event_type == "postback":
            t = threading.Thread(
                target=_handle_postback, args=(event,),
                daemon=True, name=f"line-postback-{thread_count}"
            )
            t.start()
            thread_count += 1

    logger.info(f"收到 {len(events)} 個事件，{thread_count} 個已背景處理")
    return "OK"


def _handle_event(event: dict):
    """處理單一 LINE 事件"""
    event_type = event.get("type", "")

    # 只處理訊息事件
    if event_type != "message":
        return

    # 取得來源資訊
    source = event.get("source", {})
    source_type = source.get("type", "")
    group_id = source.get("groupId", "")
    user_id = source.get("userId", "")

    # 取得訊息內容
    message = event.get("message", {})

    # 🔍 記錄所有事件以便除錯
    logger.info(f"事件: type={event_type}, source={source_type}, "
                f"user={user_id}, group={group_id}, "
                f"msg={message.get('type', '?')}")

    # 只處理群組訊息或一對一聊天
    if source_type not in ("group", "user"):
        return

    # 監控群組過濾（僅對群組生效，一對一聊天不適用）
    if source_type == "group" and config.MONITORED_GROUP_IDS and group_id not in config.MONITORED_GROUP_IDS:
        logger.debug(f"跳過非監控群組: {group_id}")
        return

    # 檢查是否為需忽略的使用者（僅在群組中適用，一對一聊天不忽略）
    if source_type == "group" and user_id in config.IGNORED_USER_IDS:
        logger.debug(f"跳過被忽略的使用者: {user_id}")
        return

    msg_type = message.get("type", "")
    message_id = message.get("id", "")

    # 🔍 計數 log
    logger.info(f"📩 收到訊息 #{message_id}: type={msg_type}, group={group_id}")

    # 檢查訊息是否已處理過（冪等性）
    if _is_duplicate_message(message_id):
        logger.info(f"⏭️ 跳過已處理的訊息: {message_id}")
        return

    logger.info(f"收到群組訊息: type={msg_type}, group={group_id}")

    # ═════════════════════════════════════════
    # 🤫 潛伏模式：不在群組中回覆任何訊息
    #    只跑管線萃取，成功時才私下通知操作者
    # ═════════════════════════════════════════
    result = None

    if msg_type == "text":
        text = message.get("text", "")

        # 🏠 快捷指令：儀表板（僅限一對一聊天，群組不回覆）
        if text.strip() == "儀表板" and source_type == "user":
            _reply_text(user_id, f"📊 投資客案件收集器\n{config.PUBLIC_BASE_URL}/dashboard")
            return

        # 📋 快捷指令：我的案件（列出有興趣+未標記案件）
        if text.strip() == "我的案件" and source_type == "user":
            run_async(reporter.send_weekly_pending_summary())
            return

        _process_and_notify(message_id, group_id, user_id, text, event, is_image=False)

    elif msg_type == "image":
        image_url = _get_line_content_url(message_id)
        if image_url:
            _process_and_notify(message_id, group_id, user_id, "", event, is_image=True, image_url=image_url)
        else:
            logger.warning(f"無法取得圖片 URL: {message_id}")


def _process_and_notify(message_id, group_id, user_id, text, event,
                        is_image=False, image_url=None):
    """在同一個 async context 中處理管線 + 通知"""

    async def _run():
        if is_image:
            result = await pipeline.process_image_message(
                message_id=message_id, group_id=group_id,
                user_id=user_id, image_url=image_url, raw_payload=event,
            )
            results = [result] if result else []
        else:
            # 一則訊息可能含多筆案件 → 先拆分
            cases = pipeline.split_multi_case(text)
            logger.info(f"訊息拆分: {len(cases)} 筆案件片段")
            results = []
            for idx, case_text in enumerate(cases):
                # 為每筆案件生成唯一 message_id（原始ID + 序號）
                case_msg_id = f"{message_id}#{idx}" if idx > 0 else message_id
                result = await pipeline.process_text_message(
                    message_id=case_msg_id, group_id=group_id,
                    user_id=user_id, text=case_text, raw_payload=event,
                )
                if result:
                    results.append(result)

        # 發送通知
        for result in results:
            logger.info(f"案件萃取成功: {json.dumps(result, ensure_ascii=False)}")
            if reporter and result.get("category") in ("new_listing", "sold", "price_drop"):
                await reporter.notify_new_listing(result)
        return results

    return run_async(_run())


def _handle_postback(event: dict):
    """處理使用者點擊卡片按鈕（postback）"""
    data_str = event.get("postback", {}).get("data", "")
    source = event.get("source", {})
    user_id = source.get("userId", "")

    if not data_str or not user_id:
        return

    # 解析 postback data: "action=interested&listing_id=123"
    params = {}
    for pair in data_str.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[k] = v

    action = params.get("action", "")
    listing_id = params.get("listing_id", "")
    if not action or not listing_id:
        return

    logger.info(f"Postback: user={user_id}, action={action}, listing={listing_id}")

    # 儲存興趣狀態
    session = Session()
    try:
        from app.models import InterestStatus
        existing = (
            session.query(InterestStatus)
            .filter(
                InterestStatus.listing_id == int(listing_id),
                InterestStatus.user_id == user_id,
            )
            .first()
        )
        if existing:
            existing.status = action
            existing.set_at = datetime.datetime.utcnow()
        else:
            new_entry = InterestStatus(
                listing_id=int(listing_id),
                user_id=user_id,
                status=action,
            )
            session.add(new_entry)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"儲存興趣狀態失敗: {e}")
    finally:
        session.close()


def _reply_text(user_id: str, text: str):
    """回覆純文字給指定使用者（僅限一對一聊天）"""
    from urllib.request import Request, urlopen
    body = json.dumps({
        "to": user_id,
        "messages": [{"type": "text", "text": text}]
    }).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        req = Request("https://api.line.me/v2/bot/message/push", data=body, headers=headers, method="POST")
        urlopen(req, timeout=10)
    except Exception as e:
        logger.error(f"回覆失敗: {e}")


def _get_line_content_url(message_id: str) -> str:
    """取得 LINE 訊息內容的下載 URL"""
    return f"https://api-data.line.me/v2/bot/message/{message_id}/content"


def _is_duplicate_message(message_id: str) -> bool:
    """檢查訊息 ID 是否已處理過"""
    session = Session()
    try:
        existing = (
            session.query(RawMessage)
            .filter(RawMessage.message_id == message_id)
            .first()
        )
        return existing is not None
    except Exception:
        return False
    finally:
        session.close()


# ─── 查詢 API ───

@app.route("/api/listings", methods=["GET"])
def get_listings():
    """查詢已萃取的案件列表"""
    from app.models import HousingListing, ContactInfo

    session = Session()
    try:
        # 基本查詢參數
        listing_type = request.args.get("type")          # sale / rent
        property_type = request.args.get("property")     # apartment / condo / ...
        category = request.args.get("category")          # new_listing / sold
        min_price = request.args.get("min_price", type=float)
        max_price = request.args.get("max_price", type=float)
        address_kw = request.args.get("address")         # 地址關鍵字
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        include_duplicates = request.args.get("include_duplicates", "false") == "true"
        processed = request.args.get("processed")          # "true"/"false"/None(全部)

        query = session.query(HousingListing)

        if not include_duplicates:
            query = query.filter(HousingListing.is_duplicate == False)

        if listing_type:
            query = query.filter(HousingListing.listing_type == listing_type)
        if property_type:
            query = query.filter(HousingListing.property_type == property_type)
        if category:
            query = query.filter(HousingListing.category == category)
        if processed is not None:
            query = query.filter(HousingListing.is_processed == (processed == "true"))
        if min_price is not None:
            query = query.filter(HousingListing.price >= min_price)
        if max_price is not None:
            query = query.filter(HousingListing.price <= max_price)
        if address_kw:
            query = query.filter(HousingListing.address.contains(address_kw))

        query = query.order_by(HousingListing.posted_at.desc())
        total = query.count()
        listings = query.offset(offset).limit(limit).all()

        # 批量查詢聯絡資訊
        listing_ids = [l.id for l in listings]
        contacts_map = {}
        if listing_ids:
            contacts = (
                session.query(ContactInfo)
                .filter(ContactInfo.listing_id.in_(listing_ids))
                .all()
            )
            for c in contacts:
                contacts_map[c.listing_id] = c

        results = []
        for l in listings:
            contact = contacts_map.get(l.id)
            # 建構圖片網址（從 RawMessage 關聯查詢）
            image_url = None
            if l.source_message:
                src_msg = l.source_message
                if src_msg.image_url:
                    # 優先用我們下載的本地圖片
                    image_url = (
                        f"{config.PUBLIC_BASE_URL}/images/{src_msg.message_id}.jpg"
                        if config.PUBLIC_BASE_URL else src_msg.image_url
                    )

            results.append({
                "id": l.id,
                "listing_type": l.listing_type,
                "property_type": l.property_type,
                "category": l.category,
                "price_wan": l.price,
                "unit_price_wan_per_ping": l.unit_price,
                "size_ping": l.size_ping,
                "floor": l.floor,
                "rooms": l.rooms,
                "address": l.address,
                "community": l.community_name,
                "has_parking": l.has_parking,
                "has_furniture": l.has_furniture,
                "is_duplicate": l.is_duplicate,
                "is_processed": l.is_processed,
                "posted_at": l.posted_at.isoformat() if l.posted_at else None,
                "description": l.description[:200] if l.description else "",
                "image_url": image_url,
                "contact_name": contact.name if contact else None,
                "contact_phone": contact.phone if contact else None,
                "contact_line": contact.line_id if contact else None,
                "contact_agency": contact.company if contact else None,
            })

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results,
        }

    except Exception as e:
        logger.error(f"查詢案件失敗: {e}")
        return {"error": str(e)}, 500
    finally:
        session.close()


@app.route("/api/debug/pipeline-stats", methods=["GET"])
def debug_pipeline_stats():
    """除錯：管線統計 — 多少訊息進來 vs 多少變成案件"""
    from sqlalchemy import func
    from app.models import HousingListing

    session = Session()
    try:
        total_messages = session.query(func.count(RawMessage.id)).scalar()
        total_listings = session.query(func.count(HousingListing.id)).scalar()
        dup_count = session.query(func.count(HousingListing.id)).filter(
            HousingListing.is_duplicate == True
        ).scalar()
        sold_count = session.query(func.count(HousingListing.id)).filter(
            HousingListing.category == "sold"
        ).scalar()

        recent_messages = (
            session.query(RawMessage)
            .order_by(RawMessage.created_at.desc())
            .limit(30)
            .all()
        )
        recent_data = []
        for r in recent_messages:
            l = session.query(HousingListing).filter(
                HousingListing.source_message_id == r.id
            ).first()
            recent_data.append({
                "raw_id": r.id,
                "msg_id": r.message_id,
                "type": r.message_type,
                "text_preview": (r.text_content or r.ocr_text or "")[:100],
                "has_listing": l is not None,
                "listing_cat": l.category if l else None,
                "listing_addr": l.address if l else None,
                "is_dup": l.is_duplicate if l else None,
            })

        return {
            "total_raw_messages": total_messages,
            "total_listings": total_listings,
            "duplicate_listings": dup_count,
            "sold_listings": sold_count,
            "recent_messages": recent_data,
        }
    finally:
        session.close()


@app.route("/api/debug/messages", methods=["GET"])
def debug_messages():
    """除錯：查看最近收到的原始訊息狀態"""
    raw = request.args.get("raw", "false") == "true"
    limit = request.args.get("limit", 20, type=int)
    session = Session()
    try:
        rows = (
            session.query(RawMessage)
            .order_by(RawMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        from app.models import HousingListing
        results = []
        for r in rows:
            listing = session.query(HousingListing).filter(
                HousingListing.source_message_id == r.id
            ).first()
            entry = {
                "message_id": r.message_id,
                "type": r.message_type,
                "user_id": r.user_id,
                "group_id": r.group_id,
                "text_preview": (r.text_content or r.ocr_text or "")[:80 if not raw else -1],
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "has_listing": listing is not None,
                "listing_category": listing.category if listing else None,
                "listing_address": listing.address if listing else None,
                "is_duplicate": listing.is_duplicate if listing else None,
            }
            if raw:
                entry["text_full"] = r.text_content or ""
                entry["ocr_text"] = r.ocr_text or ""
            results.append(entry)
        return {"count": len(results), "messages": results}
    finally:
        session.close()


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """取得統計資訊"""
    from app.models import HousingListing, RawMessage
    from sqlalchemy import func

    session = Session()
    try:
        # 總案件數
        total_listings = (
            session.query(func.count(HousingListing.id))
            .filter(HousingListing.is_duplicate == False)
            .scalar()
        )
        total_messages = session.query(func.count(RawMessage.id)).scalar()

        # 依類型統計
        type_stats = {}
        for lt in ["sale", "rent"]:
            count = (
                session.query(func.count(HousingListing.id))
                .filter(
                    HousingListing.listing_type == lt,
                    HousingListing.is_duplicate == False,
                )
                .scalar()
            )
            type_stats[lt] = count

        # 依分類統計
        cat_stats = {}
        for cat in ["new_listing", "sold"]:
            count = (
                session.query(func.count(HousingListing.id))
                .filter(
                    HousingListing.category == cat,
                    HousingListing.is_duplicate == False,
                )
                .scalar()
            )
            cat_stats[cat] = count

        return {
            "total_messages": total_messages,
            "total_listings": total_listings,
            "by_type": type_stats,
            "by_category": cat_stats,
        }

    except Exception as e:
        logger.error(f"查詢統計失敗: {e}")
        return {"error": str(e)}, 500
    finally:
        session.close()


@app.route("/api/listings/<int:listing_id>/toggle-processed", methods=["POST"])
def toggle_processed(listing_id):
    """切換案件的已處理/未處理狀態"""
    from app.models import HousingListing

    session = Session()
    try:
        listing = session.query(HousingListing).filter(
            HousingListing.id == listing_id
        ).first()
        if not listing:
            return {"error": "案件不存在"}, 404
        listing.is_processed = not listing.is_processed
        session.commit()
        return {"id": listing_id, "is_processed": listing.is_processed}
    except Exception as e:
        session.rollback()
        logger.error(f"切換處理狀態失敗: {e}")
        return {"error": str(e)}, 500
    finally:
        session.close()


@app.route("/health", methods=["GET"])
def health():
    """健康檢查端點"""
    return {"status": "ok"}


@app.route("/api/debug/db", methods=["GET"])
def debug_db():
    """檢查資料庫連線狀態和實際連線資訊"""
    import os
    pg_conn = os.getenv("POSTGRES_CONNECTION_STRING", "")
    info = {
        "DATABASE_URL": config.DATABASE_URL[:80] + "..." if len(config.DATABASE_URL) > 80 else config.DATABASE_URL,
        "db_type": "PostgreSQL" if "postgres" in config.DATABASE_URL else "SQLite",
        "env_POSTGRES_CONNECTION_STRING": pg_conn[:80] if pg_conn else "未設定",
        "env_POSTGRES_HOST": os.getenv("POSTGRES_HOST", "未設定"),
        "app_connected": True,
    }
    session = Session()
    try:
        from sqlalchemy import text
        result = session.execute(text("SELECT COUNT(*) FROM raw_messages"))
        info["raw_message_count"] = result.scalar()
        result2 = session.execute(text("SELECT COUNT(*) FROM housing_listings"))
        info["listing_count"] = result2.scalar()
    except Exception as e:
        info["app_connected"] = False
        info["error"] = str(e)
    finally:
        session.close()
    return info


@app.route("/api/debug/recent-users", methods=["GET"])
def debug_recent_users():
    """列出最近訊息的發送者 ID"""
    session = Session()
    try:
        from sqlalchemy import text
        result = session.execute(text(
            "SELECT DISTINCT user_id, MIN(created_at) as first_seen, MAX(created_at) as last_seen "
            "FROM raw_messages WHERE user_id IS NOT NULL "
            "GROUP BY user_id ORDER BY last_seen DESC LIMIT 20"
        ))
        users = []
        for row in result:
            users.append({
                "user_id": row[0],
                "first_seen": row[1].isoformat() if row[1] else None,
                "last_seen": row[2].isoformat() if row[2] else None,
            })
        return {"count": len(users), "users": users}
    finally:
        session.close()


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """數據看板"""
    from app.dashboard import DASHBOARD_HTML
    return DASHBOARD_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/images/<message_id>.jpg", methods=["GET"])
def serve_image(message_id):
    """提供已下載圖片供 LINE 訊息使用（防止目錄遍歷攻擊）"""
    from flask import send_file
    safe_id = message_id.replace("/", "").replace("\\", "").replace("..", "")
    # 使用絕對路徑
    img_dir = os.path.join(app.root_path, "..", config.IMAGE_DOWNLOAD_DIR)
    path = os.path.abspath(os.path.join(img_dir, f"{safe_id}.jpg"))
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/jpeg")


# ─── 報表摘要 API ───

@app.route("/api/report/daily", methods=["POST"])
def trigger_daily_summary():
    """手動觸發每日摘要（可用 crontab 定時呼叫）"""
    if not reporter:
        return {"error": "報表引擎未初始化"}, 500

    target = request.args.get("date")  # YYYY-MM-DD, 預設今天
    count = run_async(reporter.send_daily_summary(target))
    return {"status": "sent", "listing_count": count}


@app.route("/api/report/weekly", methods=["POST"])
def trigger_weekly_summary():
    """手動觸發每週摘要"""
    if not reporter:
        return {"error": "報表引擎未初始化"}, 500

    count = run_async(reporter.send_weekly_summary())
    return {"status": "sent", "listing_count": count}


@app.route("/api/remind/interested", methods=["POST"])
def trigger_interest_reminder():
    """
    自動提醒：對「有興趣」超過 7 天未處理的案件發送提醒
    可用 crontab 每天定時呼叫
    """
    if not reporter:
        return {"error": "報表引擎未初始化"}, 500

    count = run_async(reporter.send_interest_reminders())
    return {"status": "sent", "reminded_count": count}


@app.route("/api/report/weekly-pending", methods=["POST"])
def trigger_weekly_pending():
    """
    每週一待辦摘要：列出「有興趣」+「未標記」的案件
    設定 crontab: 0 9 * * 1（每週一上午 9 點）
    """
    if not reporter:
        return {"error": "報表引擎未初始化"}, 500

    count = run_async(reporter.send_weekly_pending_summary())
    return {"status": "sent", "total_pending": count}


# ─── 啟動 ───

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"

    logger.info(f"啟動 LINE Bot Webhook 伺服器 (port={port}, debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)
