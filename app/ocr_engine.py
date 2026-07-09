"""
圖片辨識引擎
策略: GPT-4o Vision (主力) > tesseract OCR (fallback)
"""
import os
import subprocess
import logging
import cv2
import numpy as np
from urllib.request import Request, urlopen

from config import config
from app.normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class OCREngine:

    def __init__(self):
        self._ocr = None
        self._mode = None  # "paddle" | "tesseract" | None
        self._gpt_available = config.OPENAI_API_KEY != ""

    def _detect_engine(self):
        """自動偵測可用的 OCR 引擎"""
        if self._mode is not None:
            return self._mode

        # 1. 試 PaddleOCR
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                lang=config.OCR_LANG, use_angle_cls=True,
                use_gpu=config.OCR_USE_GPU, show_log=False,
            )
            self._mode = "paddle"
            logger.info("OCR: PaddleOCR")
            return "paddle"
        except Exception:
            pass

        # 2. 試 tesseract
        try:
            subprocess.run(["tesseract", "--version"],
                           capture_output=True, timeout=5, check=True)
            self._mode = "tesseract"
            logger.info("OCR: tesseract (fallback)")
            return "tesseract"
        except Exception:
            pass

        self._mode = None
        logger.warning("無可用 OCR 引擎")
        return None

    async def download_image(self, image_url: str, save_path: str) -> bool:
        """從 LINE 下載圖片 (使用 urllib，避免 httpx event loop 衝突)"""
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

    def enhance_image(self, image_path: str) -> str | None:
        """圖片前處理增強"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            height, width = img.shape[:2]
            if width < 800 or height < 800:
                scale = max(1200 / width, 1200 / height)
                img = cv2.resize(img, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            denoised = cv2.fastNlMeansDenoising(enhanced, h=10)
            binary = cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2)
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
            sharpened = cv2.filter2D(binary, -1, kernel)
            enhanced_path = image_path.replace(".", "_enhanced.")
            cv2.imwrite(enhanced_path, sharpened)
            return enhanced_path
        except Exception as e:
            logger.error(f"圖片增強失敗: {e}")
            return None

    def _tesseract_ocr(self, image_path: str) -> str:
        """用 tesseract CLI 做 OCR (chi_tra + psm=3 最佳)"""
        try:
            result = subprocess.run(
                ["tesseract", image_path, "stdout",
                 "-l", "chi_tra",
                 "--psm", "3"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"tesseract 失敗: {e}")
        return ""

    def _paddle_ocr(self, image_path: str) -> str:
        """用 PaddleOCR 做辨識"""
        try:
            result = self._ocr.ocr(image_path, cls=True)
            if not result or not result[0]:
                return ""
            lines = []
            for line_info in result[0]:
                if line_info and len(line_info) >= 2:
                    text = line_info[1][0]
                    confidence = line_info[1][1]
                    if confidence > 0.5:
                        lines.append(text)
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"PaddleOCR 失敗: {e}")
            return ""

    def recognize(self, image_path: str) -> str:
        """OCR 辨識主入口"""
        mode = self._detect_engine()

        if mode is None:
            return ""

        try:
            if mode == "paddle":
                enhanced_path = self.enhance_image(image_path)
                target = enhanced_path if enhanced_path else image_path
                raw = self._paddle_ocr(target)
            elif mode == "tesseract":
                # tesseract 自己會做前處理，不增強
                raw = self._tesseract_ocr(image_path)
            else:
                return ""

            normalized = TextNormalizer.normalize(raw)
            logger.info(f"OCR ({mode}): {len(raw)} chars")
            return normalized
        except Exception as e:
            logger.error(f"OCR 失敗 {image_path}: {e}")
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
            - ocr_text: tesseract 文字（GPT 失敗時使用）
            - gpt_result: GPT 回傳的結構化 dict，或 None
        """
        save_path = os.path.join(
            config.IMAGE_DOWNLOAD_DIR, f"{message_id}.jpg"
        )
        success = await self.download_image(image_url, save_path)
        if not success:
            return "", "", None

        # 1. 先試 GPT Vision (主力)
        gpt_result = self._try_gpt_vision(save_path)
        if gpt_result and gpt_result.get("is_property"):
            logger.info(f"GPT 成功萃取: {gpt_result.get('price_wan')}萬 @ {gpt_result.get('address')}")
            # 仍跑 tesseract OCR 取得原始文字（供記錄用）
            ocr_text = self.recognize(save_path)
            return save_path, ocr_text, gpt_result

        # 2. GPT 失敗/非房產 → fallback to tesseract OCR
        if gpt_result and gpt_result.get("is_property") is False:
            logger.info("GPT 判定不是房產圖片，跳過")
            return save_path, "", gpt_result

        # GPT 沒裝或沒 key → 只用 tesseract
        ocr_text = self.recognize(save_path)
        return save_path, ocr_text, None


ocr_engine = OCREngine()
