FROM python:3.11-slim

# 安裝 tesseract OCR + 正體中文語言包（fallback 用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Zeabur 會自動設定 PORT 環境變數
CMD gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
