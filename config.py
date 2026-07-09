"""
房產案件監控系統 - 設定檔
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # LINE Bot
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/housing.db")

    # OCR
    OCR_LANG: str = "ch"  # 中文 OCR
    OCR_USE_GPU: bool = False

    # Deduplication
    DEDUP_SIMILARITY_THRESHOLD: float = 0.75  # 相似度門檻 (0-1)
    DEDUP_TIME_WINDOW_HOURS: int = 72  # 去重時間窗口 (小時)

    # Image download
    IMAGE_DOWNLOAD_DIR: str = "data/images"

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # LINE Bot 只監控特定群組 (逗號分隔的群組 ID)
    MONITORED_GROUP_IDS: list[str] = field(default_factory=lambda: [
        gid.strip() for gid in os.getenv("MONITORED_GROUP_IDS", "").split(",") if gid.strip()
    ])

    # 忽略的 LINE 使用者 ID (如自己 Bot 的訊息)
    IGNORED_USER_IDS: list[str] = field(default_factory=lambda: [
        uid.strip() for uid in os.getenv("IGNORED_USER_IDS", "").split(",") if uid.strip()
    ])

    # ─── 報表回報設定 ───

    # 即時通知：新案件時立刻推播給這些 LINE 使用者 ID（逗號分隔）
    NOTIFY_TARGET_USER_IDS: list[str] = field(default_factory=lambda: [
        uid.strip() for uid in os.getenv("NOTIFY_TARGET_USER_IDS", "").split(",") if uid.strip()
    ])

    # 是否啟用即時通知
    ENABLE_REALTIME_NOTIFY: bool = os.getenv("ENABLE_REALTIME_NOTIFY", "true").lower() == "true"

    # 每日摘要排程 (HH:MM, 24hr)
    DAILY_SUMMARY_TIME: str = os.getenv("DAILY_SUMMARY_TIME", "21:00")

    # 每週摘要排程 (星期幾, 0=周一 ... 6=周日)
    WEEKLY_SUMMARY_DAY: int = int(os.getenv("WEEKLY_SUMMARY_DAY", "6"))  # 預設周六
    WEEKLY_SUMMARY_TIME: str = os.getenv("WEEKLY_SUMMARY_TIME", "21:00")

    # ─── GPT Vision ───
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = "gpt-4o"  # 支援 vision 的模型

    # 對外公開 URL（用於圖片轉發）
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")


config = Config()
