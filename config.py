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

    # Database（支援 Zeabur PostgreSQL 多種注入方式）
    @staticmethod
    def _build_db_url() -> str:
        # 1) 明確 DATABASE_URL
        explicit = os.getenv("DATABASE_URL", "")
        if explicit and "postgres" in explicit:
            return explicit

        # 2) Zeabur 注入的完整 connection string（service linking 後會解析）
        pg_conn_str = os.getenv("POSTGRES_CONNECTION_STRING", "")
        if pg_conn_str and "postgresql://" in pg_conn_str:
            return pg_conn_str

        # 3) 獨立環境變數
        pg_host = os.getenv("POSTGRES_HOST", "")
        if pg_host:
            pg_user = os.getenv("POSTGRES_USERNAME", "postgres")
            pg_pass = os.getenv("POSTGRES_PASSWORD", "")
            pg_port = os.getenv("POSTGRES_PORT", "5432")
            pg_db   = os.getenv("POSTGRES_DATABASE", "postgres")
            return f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

        # 4) 容器環境但沒 PostgreSQL → 暫時 fallback SQLite 並記錄（讓 deploy 不 crash）
        if os.getenv("PORT") or os.getenv("ZEABUR"):
            print("[WARN] 容器環境偵測不到 PostgreSQL，暫時 fallback SQLite")
            print(f"  DATABASE_URL={explicit[:60] if explicit else '未設定'}")
            print(f"  POSTGRES_CONNECTION_STRING={pg_conn_str[:60] if pg_conn_str else '未設定'}")

        # 5) 本機開發或 fallback：SQLite
        return explicit or "sqlite:///data/housing.db"

    DATABASE_URL: str = field(default_factory=_build_db_url)

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

    # ─── DeepSeek（文字萃取） ───
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"  # 高性能 + 便宜

    # 對外公開 URL（用於圖片轉發）
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")


config = Config()
