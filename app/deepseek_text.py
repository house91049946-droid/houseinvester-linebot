"""
DeepSeek 文字訊息萃取模組
用 DeepSeek API 直接理解台灣房產文字，輸出結構化 JSON
取代原本 regex 萃取器，大幅提升準確度（尤其在聯絡資訊上）
"""
import logging
import json
import re

from config import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一個台灣房地產資料萃取助手。我會給你一段來自投資客 LINE 群組的訊息文字。

請從文字中萃取出以下資訊，以 JSON 格式回傳（只回傳 JSON，不要其他文字）：

{
  "is_property": true/false,
  "category": "new_listing"/"sold"/"price_drop"/null,
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
  "deposit": 押金月數 或 null,
  "building_age": "屋齡",
  "description": "原始文案摘要(限100字)",
  "confidence": 0.0-1.0,
  "contact_name": "聯絡人姓名" 或 null,
  "contact_phone": "電話號碼" 或 null,
  "contact_line": "LINE ID" 或 null,
  "contact_agency": "仲介公司名稱" 或 null
}

規則：
- 若文字不是房產案件（閒聊、新聞、廣告推文、買方需求、政治、問候），is_property = false
- 廣告推文（只說「歡迎委託」「幫您賣好價」沒有具體案件）→ is_property = false
- 買方需求（「買需」「客需」「求購」）→ is_property = false
- 新聞摘要（「新聞」「☑️」開頭）→ is_property = false

- ⚠️ 售出判定：文字中有「已售出」「已成交」「賀成交」「賣掉了」→ category = "sold"
- ⚠️ 降價判定：文字中有「降價」「調降」「急售」「賠售」「下殺」→ category = "price_drop"
- 其他正常案件 → category = "new_listing"

- 價格單位一律轉為「萬元」。「1188萬」→ 1188，「1.2億」→ 12000，「月租15000元」→ 1.5
- 坪數只取數字（「建坪37.59坪」→ 37.59，「11坪」→ 11）
- 地址盡可能完整，含縣市區路段門牌。找不到完整地址填 null
- ⚠️ 土地案件地址一定是「段+地號」格式
- 格局格式如「3房2廳2衛」，不確定填 null
- 車位/傢俱/管理費有提到就設 true/數字
- ⚠️ 聯絡資訊非常重要！仔細掃描文字中的：
  - 聯絡人姓名（通常跟電話連在一起，如「蔣秉詳0985-094168」）
  - 電話號碼（09xx開頭，去掉「-」「 」等分隔符）
  - LINE ID（「LINE:xxx」「賴:xxx」「LINE ID:xxx」）
  - 仲介公司（「永慶」「信義」「住商」「台灣房屋」「有巢氏」等）
- 資訊不完整不需猜測，填 null
- confidence 依資訊完整度給 0-1 分數
"""


def _parse_json(text: str) -> dict | None:
    """從 LLM 回傳中提取 JSON"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning(f"無法解析 DeepSeek 回傳: {text[:200]}")
    return None


def extract_with_deepseek(text: str) -> dict | None:
    """
    用 DeepSeek API 萃取房產資訊

    Returns:
        dict with housing data, or None
    """
    if not config.DEEPSEEK_API_KEY:
        logger.warning("未設定 DEEPSEEK_API_KEY，跳過 DeepSeek 萃取")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai 套件未安裝")
        return None

    try:
        client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )

        response = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=800,
            temperature=0,
        )

        content = response.choices[0].message.content
        logger.info(f"DeepSeek 回傳: {content[:200]}...")

        result = _parse_json(content)
        if result:
            logger.info(
                f"DeepSeek 萃取: is_property={result.get('is_property')}, "
                f"{result.get('listing_type')}/{result.get('property_type')} "
                f"{result.get('price_wan')}萬 "
                f"聯絡:{result.get('contact_name') or '無'} {result.get('contact_phone') or '無'}"
            )
            return result

        return None

    except Exception as e:
        logger.error(f"DeepSeek API 失敗: {e}")
        return None
