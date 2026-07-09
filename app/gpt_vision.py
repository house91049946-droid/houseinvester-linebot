"""
GPT Vision 圖片辨識模組
用 GPT-4o 直接看懂房產圖片，輸出結構化 JSON
"""
import base64
import logging
import json
import re
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)

# Prompt 模板 - 告訴 GPT 我們要什麼
SYSTEM_PROMPT = """你是一個台灣房地產資料萃取助手。我會給你一張房地產物件的圖片。

請從圖片中萃取出以下資訊，以 JSON 格式回傳（只回傳 JSON，不要其他文字）：

{
  "is_property": true/false,
  "category": "new_listing"/"sold"/null,
  "listing_type": "sale"/"rent"/null,
  "property_type": "apartment"/"condo"/"house"/"studio"/"office"/"land"/"parking"/null,
  "price_wan": 數字(萬元),
  "unit_price_wan_per_ping": 數字(單價萬/坪) 或 null,
  "size_ping": 數字(坪),
  "floor": "樓層描述",
  "rooms": "格局",
  "address": "完整地址",
  "community": "社區名稱",
  "has_parking": true/false,
  "has_furniture": true/false,
  "management_fee": 數字(元/月) 或 null,
  "building_age": "屋齡",
  "description": "原始文案摘要(限100字)",
  "confidence": 0.0-1.0,
  "contact_name": "聯絡人姓名" 或 null,
  "contact_phone": "電話號碼" 或 null,
  "contact_line": "LINE ID" 或 null,
  "contact_agency": "仲介公司名稱" 或 null
}

規則：
- 若圖片不是房產案件，is_property = false，其他欄位 null

- ⚠️ 售出判定（非常重要）：
  圖片上若有紅字大章蓋印「售出」「已成交」「賀成交」「成交」「SOLD」「已售」、
  或紅色圓形/方形印章覆蓋在物件資訊上、或手寫紅字標註已售出，
  則 category = "sold"。
  沒有這些售出標記的，category = "new_listing"。

- 價格單位一律轉為「萬元」。「1188萬」→ 1188，「1.2億」→ 12000，「月租15000元」→ 1.5
- 坪數只取數字（「建坪52.183坪」→ 52.183）
- 地址盡可能完整，含縣市區路段門牌。**土地案件必須用地號格式**，如「台中市北屯區仁美段1234地號」。
- ⚠️ 地號處理規則（非常重要）：
  - 土地案件（property_type = "land"）的地址一定是「段+地號」格式，例如「東勢區東勢段石角小段3377地號」
  - 地號永遠放在 address 欄位，不要放到 community 或 description
  - 不要用地號當作 title/標題/community，它本身就是地址
  - 常見地號格式：X段、XX小段、XXXX地號、XXXX-XX地號
- 格局格式如「3房2廳2衛」
- 車位/傢俱/管理費有提到就設 true/數字
- 聯絡資訊：仲介姓名、電話(09xx開頭)、LINE ID、公司名稱。電話去掉括號和空格（「0933-985-008」→「0933985008」）
- 資訊不完整不需猜測，填 null
- confidence 依圖片清晰度和資訊完整度給 0-1 分數
- ⚠️ address 欄位不要只填縣市區（如「永和區」「台中市西區」），必須包含路名/段名/門牌號碼或完整地號。找不到完整地址就填 null，不要填不完整的區域名稱。
"""


def _encode_image(image_path: str) -> str:
    """將圖片轉為 base64 data URL"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _parse_gpt_response(text: str) -> dict | None:
    """從 GPT 回傳中提取 JSON"""
    # 嘗試直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 嘗試從 markdown code block 中提取
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 嘗試找到第一個 { ... }
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning(f"無法解析 GPT 回傳 JSON: {text[:200]}")
    return None


def recognize_with_gpt(image_path: str) -> dict | None:
    """
    用 GPT-4o Vision 辨識房產圖片

    Returns:
        dict with housing data, or None if failed
    """
    if not config.OPENAI_API_KEY:
        logger.warning("未設定 OPENAI_API_KEY，跳過 GPT Vision")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai 套件未安裝，請執行: pip install openai")
        return None

    try:
        b64 = _encode_image(image_path)
        data_url = f"data:image/jpeg;base64,{b64}"

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "請從這張台灣房產圖片中萃取資訊，回傳 JSON。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
                        },
                    ],
                },
            ],
            max_tokens=800,
            temperature=0,
        )

        content = response.choices[0].message.content
        logger.info(f"GPT Vision 回傳: {content[:200]}...")

        result = _parse_gpt_response(content)
        if result and result.get("is_property") is True:
            logger.info(
                f"GPT 萃取: {result.get('listing_type')}/{result.get('property_type')} "
                f"{result.get('price_wan')}萬 {result.get('size_ping')}坪 "
                f"({result.get('confidence', '?')})"
            )
            return result
        elif result:
            logger.info(f"GPT 判定非房產: is_property={result.get('is_property')}")
            return result

        return None

    except Exception as e:
        logger.error(f"GPT Vision 失敗: {e}")
        return None
