"""
SQLAlchemy 資料模型 - 結構化儲存所有案件資訊
支援 SQLite（本地開發）和 PostgreSQL（Zeabur 生產環境）
"""
import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean, LargeBinary,
    ForeignKey, Enum, Index, create_engine, JSON
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import enum

Base = declarative_base()


# ----- 枚舉型態 -----

class ListingType(str, enum.Enum):
    SALE = "sale"           # 買賣
    RENT = "rent"           # 租賃
    PRE_RENT = "pre_rent"   # 預租

class PropertyType(str, enum.Enum):
    APARTMENT = "apartment"         # 電梯大樓
    CONDO = "condo"                 # 公寓
    HOUSE = "house"                 # 透天/別墅
    STUDIO = "studio"               # 套房
    OFFICE = "office"               # 辦公室/店面
    LAND = "land"                   # 土地
    PARKING = "parking"             # 車位
    OTHER = "other"

class MessageCategory(str, enum.Enum):
    NEW_LISTING = "new_listing"         # 新案件 (買賣/租賃)
    SOLD = "sold"                       # 已售出/已出租
    PROMOTION = "promotion"             # 推文/廣告 (非案件)
    INQUIRY = "inquiry"                 # 詢問/討論
    IRRELEVANT = "irrelevant"           # 不相關訊息


# ----- 主要資料表 -----

class RawMessage(Base):
    """原始訊息紀錄 (所有訊息都存)"""
    __tablename__ = "raw_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(64), unique=True, index=True)
    group_id = Column(String(64), index=True)
    user_id = Column(String(64))
    message_type = Column(String(16))          # text, image, video, file
    text_content = Column(Text, default="")    # 純文字內容
    image_url = Column(String(512))            # 若有圖片，紀錄 URL
    image_hash = Column(String(64), nullable=True, index=True)  # 圖片 MD5 去重
    ocr_text = Column(Text, default="")        # OCR 辨識後的文字
    raw_payload = Column(JSON, default={})  # LINE 原始 payload (JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 關聯到處理後的案件
    listing = relationship("HousingListing", back_populates="source_message", uselist=False)


class HousingListing(Base):
    """結構化房產案件"""
    __tablename__ = "housing_listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_message_id = Column(Integer, ForeignKey("raw_messages.id"))

    # 案件基本分類
    listing_type = Column(String(16))      # sale / rent / pre_rent
    property_type = Column(String(16))     # apartment / condo / house / ...
    category = Column(String(16))          # new_listing / sold / promotion / ...

    # 萃取出的結構化欄位
    price = Column(Float, nullable=True)          # 總價 (萬元)
    unit_price = Column(Float, nullable=True)     # 單價 (萬/坪)
    size_ping = Column(Float, nullable=True)      # 坪數
    floor = Column(String(32), nullable=True)     # 樓層 (如 "5F/12F")
    rooms = Column(String(32), nullable=True)     # 格局 (如 "3房2廳2衛")
    address = Column(String(256), nullable=True)  # 地址/區域
    community_name = Column(String(128), nullable=True)  # 社區名稱 / 案名

    # 租賃特有
    deposit = Column(Float, nullable=True)        # 押金
    management_fee = Column(Float, nullable=True) # 管理費
    has_parking = Column(Boolean, default=False)  # 含車位
    has_furniture = Column(Boolean, default=False) # 含傢俱

    # 備註與原始文案
    description = Column(Text, default="")        # 完整文案
    extracted_meta = Column(JSON, default={}) # 其他萃取到的欄位

    # 時間戳
    posted_at = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 去重標記
    dedup_hash = Column(String(64), index=True)   # 去重用 hash
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(Integer, nullable=True)

    # 處理狀態（操作者標記是否已處理）
    is_processed = Column(Boolean, default=False)

    # 萃取完整度（儀表板品質追蹤）
    has_address = Column(Boolean, default=False)   # 有地址
    has_price = Column(Boolean, default=False)      # 有價格
    has_contact = Column(Boolean, default=False)    # 有聯絡資訊

    # 關聯回原始訊息
    source_message = relationship("RawMessage", back_populates="listing")

    __table_args__ = (
        Index("idx_listing_type_category", "listing_type", "category"),
        Index("idx_address", "address"),
        Index("idx_price", "price"),
        Index("idx_posted_at", "posted_at"),
    )


class ContactInfo(Base):
    """從訊息中萃取的聯絡資訊"""
    __tablename__ = "contact_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey("housing_listings.id"))
    name = Column(String(64), nullable=True)
    phone = Column(String(32), nullable=True)
    line_id = Column(String(64), nullable=True)
    company = Column(String(128), nullable=True)


class InterestStatus(Base):
    """使用者對案件的興趣狀態（透過卡片按鈕互動）"""
    __tablename__ = "interest_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey("housing_listings.id"), nullable=False)
    user_id = Column(String(64), nullable=False)        # LINE 使用者 ID
    status = Column(String(16), nullable=False)          # completed / interested / not_interested
    set_at = Column(DateTime, default=datetime.datetime.utcnow)
    reminder_sent_at = Column(DateTime, nullable=True)   # 上次提醒時間
    remark = Column(Text, default="")                    # 備註


class ImageBlob(Base):
    """圖片持久化儲存（存於 PostgreSQL，不隨容器消失）"""
    __tablename__ = "image_blobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(64), unique=True, index=True, nullable=False)
    data = Column(LargeBinary, nullable=False)           # 圖片二進位內容
    mimetype = Column(String(32), default="image/jpeg")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ----- 資料庫連線 -----

def _migrate_db(engine):
    """自動補上 SQLAlchemy create_all 不會處理的新欄位（適用於現有 PostgreSQL）"""
    from sqlalchemy import text, inspect
    inspector = inspect(engine)

    # 檢查 housing_listings 是否有 has_address / has_price / has_contact
    if "housing_listings" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("housing_listings")}
        for col_name in ("has_address", "has_price", "has_contact"):
            if col_name not in cols:
                with engine.connect() as conn:
                    conn.execute(text(
                        f"ALTER TABLE housing_listings ADD COLUMN {col_name} BOOLEAN DEFAULT FALSE"
                    ))
                    conn.commit()

    # 檢查 raw_messages 是否有 image_hash
    if "raw_messages" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("raw_messages")}
        if "image_hash" not in cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE raw_messages ADD COLUMN image_hash VARCHAR(64)"
                ))
                conn.commit()

    # 檢查 image_blobs 表是否存在
    if "image_blobs" not in inspector.get_table_names():
        ImageBlob.__table__.create(engine, checkfirst=True)


def init_db(db_url: str):
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    _migrate_db(engine)
    Session = sessionmaker(bind=engine)
    return Session
