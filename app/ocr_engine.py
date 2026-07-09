"""
圖片辨識引擎
策略: GPT-4o Vision (主力) > tesseract OCR (fallback)
（已移除非雲端依賴：PaddleOCR、OpenCV）
"""
import os
import subprocess
import logging
from urllib.request import Request, urlopen

from config import config

logger = logging.getLogger(__name__)


class OCREngine:

    def __init__(self):
        self._tesseract_available = self._check_tesseract()
        self._gpt_available = bool(config.OPENAI_API_KEY)

    def _check_tesseract(self) -> bool:
        try:
            subprocess.run(["tesseract", "--version"],
                           capture_output=True, timeout=5, check=True)
            logger.info("OCR: tesseract (fallback ready)")
            return True
        except Exception:
            logger.warning("tesseract 未安裝（僅依賴 GPT Vision）")
            return False

    async def download_image(self, image_url: str, save_path: str) -> bool:
        """從 LINE 下載圖片 (urllib)"""
        try:
            req = Request(image_url)
            req.add_header("Authorization", f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}")
            with urlopen(req, timeout=30) as resp:
                data = resp.read()
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(data)
            return True
        except Exception as e:
            logger.error(f"圖片下載失敗 {image_url}: {e}")
            return False

    def _tesseract_ocr(self, image_path: str) -> str:
        """用 tesseract CLI 做 OCR (chi_tra + psm=3)"""
        try:
            result = subprocess.run(
                ["tesseract", image_path, "stdout",
                 "-l", "chi_tra", "--psm", "3"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"tesseract 失敗: {e}")
        return ""

    def _try_gpt_vision(self, image_path: str) -> dict | None:
        """嘗試用 GPT-4o Vision 辨識圖片"""
        if not self._gpt_available:
            return None
        try:
            from app.gpt_vision import recognize_with_gpt
            return recognize_with_gpt(image_path)
        except Exception as e:
            logger.warning(f"GPT Vision 調用失敗: {e}")
            return None

    async def process_line_image(
        self, message_id: str, image_url: str
    ) -> tuple[str, str, dict | None]:
        """
        處理 LINE 圖片：下載 → GPT Vision → tesseract fallback

        Returns:
            (save_path, ocr_text, gpt_result)
        """
        save_path = os.path.join(
            config.IMAGE_DOWNLOAD_DIR, f"{message_id}.jpg"
        )
        success = await self.download_image(image_url, save_path)
        if not success:
            return "", "", None

        # 1. GPT Vision (主力)
        gpt_result = self._try_gpt_vision(save_path)
        if gpt_result and gpt_result.get("is_property"):
            logger.info(f"GPT 萃取: {gpt_result.get('price_wan')}萬 @ {gpt_result.get('address')}")
            ocr_text = self._tesseract_ocr(save_path) if self._tesseract_available else ""
            return save_path, ocr_text, gpt_result

        # 2. GPT 判定非房產
        if gpt_result and gpt_result.get("is_property") is False:
            logger.info("GPT 判定非房產，跳過")
            return save_path, "", gpt_result

        # 3. Fallback: tesseract OCR
        ocr_text = self._tesseract_ocr(save_path) if self._tesseract_available else ""
        return save_path, ocr_text, None


ocr_engine = OCREngine()
