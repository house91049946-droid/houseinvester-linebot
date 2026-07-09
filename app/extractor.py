"""
NLP 房產資訊萃取引擎 - 從正規化後的文字中提取結構化欄位
採用 Regex + 詞典 混合策略，專注台灣房產市場用語
"""
import re
import logging
from dataclasses import dataclass, field

from app.normalizer import TextNormalizer, parse_price_to_wan, parse_size_to_ping

logger = logging.getLogger(__name__)


@dataclass
class ExtractedListing:
    """萃取結果"""
    # 核心欄位
    price_wan: float | None = None           # 總價 (萬元)
    unit_price_wan_per_ping: float | None = None  # 單價 (萬/坪)
    size_ping: float | None = None           # 坪數
    floor: str | None = None                 # 樓層
    rooms: str | None = None                 # 格局
    address: str | None = None               # 地址/區域
    community: str | None = None             # 社區名稱
    listing_type: str | None = None          # sale / rent / pre_rent
    property_type: str | None = None         # 房屋類型

    # 租賃特有
    deposit: float | None = None             # 押金 (月)
    management_fee: float | None = None      # 管理費 (元/月)

    # 附加資訊
    has_parking: bool = False
    has_furniture: bool = False
    building_age: str | None = None          # 屋齡

    # 未分類欄位 (所有關鍵字匹配到的都保留)
    extra: dict = field(default_factory=dict)

    # 信心度 (0-1)
    confidence: float = 0.0


class HousingExtractor:
    """房產資訊萃取器"""

    # ─── 台灣縣市/區域詞典 ───
    CITIES = [
        "台北市", "臺北市", "新北市", "桃園市", "台中市", "臺中市",
        "台南市", "臺南市", "高雄市", "基隆市", "新竹市", "新竹縣",
        "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣",
        "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "臺東縣", "澎湖縣",
        "金門縣", "連江縣",
    ]

    # 常見行政區 (只列部分，可持續擴充)
    DISTRICTS = [
        # 台北
        "大安區", "信義區", "中山區", "中正区", "松山區", "內湖區",
        "南港區", "文山區", "萬華區", "大同區", "士林區", "北投區",
        # 新北
        "板橋區", "永和區", "中和區", "新店區", "三重區", "蘆洲區",
        "汐止區", "新莊區", "土城區", "樹林區", "淡水區", "林口區",
        "三峽區", "鶯歌區", "五股區", "泰山區",
        # 桃園
        "桃園區", "中壢區", "平鎮區", "八德區", "楊梅區", "蘆竹區",
        "龜山區", "大園區", "龍潭區", "大溪區",
        # 台中
        "西屯區", "北屯區", "南屯區", "西區", "北區", "中區", "東區",
        "南區", "大里區", "太平區", "豐原區", "潭子區", "大雅區",
        "沙鹿區", "清水區", "龍井區", "烏日區", "大甲區",
        # 高雄
        "左營區", "鼓山區", "三民區", "苓雅區", "前鎮區", "鳳山區",
        "楠梓區", "新興區", "前金區", "鹽埕區", "小港區", "仁武區",
        # 台南
        "東區", "中西區", "北區", "南區", "安平區", "安南區", "永康區",
        # 新竹
        "東區", "北區", "香山區", "竹北市",
    ]

    # 簡稱對應表: "永和" -> "永和區", "內湖" -> "內湖區", etc.
    DISTRICT_SHORT_MAP: dict = {}  # built below

    # ─── 物件類型關鍵字 ───
    TYPE_KEYWORDS = {
        "apartment": [
            "電梯大樓", "大樓", "華廈", "社區大樓", "高樓層",
            "新成屋", "預售屋", "全新大樓", "豪宅",
        ],
        "condo": [
            "公寓", "舊公寓", "老舊公寓", "五樓公寓", "四樓公寓",
            "無電梯", "爬樓梯",
        ],
        "house": [
            "透天", "透天厝", "別墅", "獨棟", "雙拼", "連棟透天",
            "整棟", "住辦",
        ],
        "studio": [
            "套房", "獨立套房", "小套房", "分租套房", "雅房",
            "小坪數", "微型宅",
        ],
        "office": [
            "店面", "辦公室", "商辦", "廠辦", "黃金店面", "攤位",
            "事務所", "出租店面",
        ],
        "land": [
            "土地", "建地", "農地", "工業地", "素地", "空地",
        ],
        "parking": [
            "車位出售", "車位出租", "出售車位", "出租車位",
            "車位單獨出售", "純車位",
        ],
    }

    @classmethod
    def _build_district_short_map(cls):
        """建立行政區簡稱映射表"""
        if cls.DISTRICT_SHORT_MAP:
            return
        for d in cls.DISTRICTS:
            # "永和區" -> {"永和", "永和區"}
            base = d.rstrip("區")
            cls.DISTRICT_SHORT_MAP[base] = d
            cls.DISTRICT_SHORT_MAP[d] = d
        # 特殊簡稱
        cls.DISTRICT_SHORT_MAP["台北"] = "台北市"
        cls.DISTRICT_SHORT_MAP["臺北"] = "臺北市"
        cls.DISTRICT_SHORT_MAP["台中"] = "台中市"
        cls.DISTRICT_SHORT_MAP["臺中"] = "臺中市"
        cls.DISTRICT_SHORT_MAP["高雄"] = "高雄市"
        cls.DISTRICT_SHORT_MAP["台南"] = "台南市"
        cls.DISTRICT_SHORT_MAP["臺南"] = "臺南市"
        cls.DISTRICT_SHORT_MAP["新竹"] = "新竹市"
        cls.DISTRICT_SHORT_MAP["桃園"] = "桃園市"
        cls.DISTRICT_SHORT_MAP["基隆"] = "基隆市"
        cls.DISTRICT_SHORT_MAP["七期"] = "台中市西屯區"

    # ─── 買賣 vs 租賃關鍵字 ───
    SALE_KEYWORDS = [
        "出售", "售", "賣", "買賣", "銷售", "代售", "急售", "割愛",
        "出售中", "出售物件", "總價", "開價", "售價",
    ]
    RENT_KEYWORDS = [
        "出租", "租", "承租", "租金", "月租", "年租",
        "分租", "合租", "求租", "租房", "租屋",
        "押金", "仲介費", "可租補",
    ]
    PRE_RENT_KEYWORDS = [
        "預租", "預出租", "即將釋出", "預約看房",
    ]

    # ─── 售出/成交關鍵字 ───
    SOLD_KEYWORDS = [
        "已售出", "已成交", "售出", "恭喜成交", "賀成交",
        "已出租", "租掉了", "已租", "已售", "賣掉了",
        "成交價", "實登", "成交行情",
    ]

    # ─── 推文/廣告關鍵字 ───
    PROMOTION_KEYWORDS = [
        "委託", "歡迎委託", "專任委託", "一般委託",
        "需要委託請找我", "幫您賣好價", "代尋", "徵求",
        "免費估價", "行情諮詢", "歡迎來電", "預約賞屋",
    ]

    # ─── 車位/傢俱/裝潢關鍵字 ───
    PARKING_KEYWORDS = [
        "含車位", "附車位", "平面車位", "機械車位", "坡道平面",
        "坡平", "坡道機械", "升降平面", "車位", "停車位",
    ]
    FURNITURE_KEYWORDS = [
        "含傢俱", "附傢俱", "含家具", "附家具",
        "傢俱全", "家具全", "含家電", "附家電",
        "拎包入住", "一卡皮箱", "免整理",
    ]
    DECORATION_KEYWORDS = [
        "全新裝潢", "百萬裝潢", "精裝修", "豪華裝修",
        "重新整理", "裝潢", "整修",
    ]

    def extract(self, text: str) -> ExtractedListing:
        """主萃取方法"""
        text = TextNormalizer.normalize(text)
        result = ExtractedListing()
        confidence_points = 0

        # 1. 判斷案件類型 (買賣/租賃)
        result.listing_type = self._detect_listing_type(text)
        if result.listing_type:
            confidence_points += 1

        # 2. 判斷物件類型 (大樓/公寓/透天...)
        result.property_type = self._detect_property_type(text)
        if result.property_type:
            confidence_points += 1

        # 3. 萃取價格
        result.price_wan = self._extract_price(text)
        if result.price_wan:
            confidence_points += 2  # 價格是最重要的欄位

        # 4. 萃取單價
        result.unit_price_wan_per_ping = self._extract_unit_price(text)

        # 5. 萃取坪數
        result.size_ping = parse_size_to_ping(text)
        if result.size_ping:
            confidence_points += 1

        # 6. 萃取地址/區域
        result.address = self._extract_address(text)
        if result.address:
            confidence_points += 2

        # 7. 萃取樓層
        result.floor = self._extract_floor(text)
        if result.floor:
            confidence_points += 1

        # 8. 萃取格局
        result.rooms = self._extract_rooms(text)

        # 9. 萃取社區名稱
        result.community = self._extract_community(text)

        # 10. 車位
        result.has_parking = self._check_keywords(text, self.PARKING_KEYWORDS)

        # 11. 傢俱
        result.has_furniture = self._check_keywords(text, self.FURNITURE_KEYWORDS)

        # 12. 押金 (租賃)
        if result.listing_type == "rent":
            result.deposit = self._extract_deposit(text)

        # 13. 管理費
        result.management_fee = self._extract_management_fee(text)

        # 14. 屋齡
        result.building_age = self._extract_building_age(text)

        # 15. 計算信心度 (最高約 10 分)
        result.confidence = min(confidence_points / 10.0, 1.0)

        return result

    # ─── 內部偵測方法 ───

    def _detect_listing_type(self, text: str) -> str | None:
        """判斷是買賣還是租賃"""
        sale_score = sum(1 for kw in self.SALE_KEYWORDS if kw in text)
        rent_score = sum(1 for kw in self.RENT_KEYWORDS if kw in text)
        pre_rent_score = sum(1 for kw in self.PRE_RENT_KEYWORDS if kw in text)

        if pre_rent_score > 0:
            return "pre_rent"
        if rent_score > sale_score:
            return "rent"
        if sale_score > 0:
            return "sale"

        # 如果沒明確關鍵字，根據價格數值推斷
        # 租金通常 < 50 萬，售價通常 > 100 萬
        price = parse_price_to_wan(text)
        if price is not None:
            if price <= 10:
                return "rent"
            elif price >= 100:
                return "sale"

        return None

    def _detect_property_type(self, text: str) -> str | None:
        """偵測物件類型"""
        scores = {}
        for ptype, keywords in self.TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[ptype] = score

        if scores:
            return max(scores, key=scores.get)
        return None

    def _extract_price(self, text: str) -> float | None:
        """萃取總價（萬元）"""
        return parse_price_to_wan(text)

    def _extract_unit_price(self, text: str) -> float | None:
        """萃取單價（萬/坪）"""
        patterns = [
            re.compile(r"(\d+[.]?\d*)\s*萬\s*/\s*坪"),
            re.compile(r"(\d+[.]?\d*)\s*[萬Ww]\s*[/／]\s*[坪Pp]"),
            re.compile(r"單價\s*[:：]?\s*(\d+[.]?\d*)\s*[萬Ww]"),
            re.compile(r"(\d+[.]?\d*)\s*[萬Ww]\s*一坪"),
            re.compile(r"每坪\s*(\d+[.]?\d*)\s*[萬Ww]"),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                return float(m.group(1))
        return None

    def _extract_address(self, text: str) -> str | None:
        """萃取地址或區域資訊"""
        # 完整地址格式（精準匹配，依序嘗試）
        address_patterns = [
            # 縣市+行政區+路/街(+段)+號碼(含之如336之43)+號/弄/巷/樓
            re.compile(r"([\u4e00-\u9fff]{2,4}[縣市]\s*[\u4e00-\u9fff]{2,4}[區鄉鎮市]\s*[\u4e00-\u9fff\d]+[路街](\d+段)?\s*[\d\-\s之]+[號弄巷樓])"),
            # 路/街(+段)+號碼(含之)+號 (不含行政區)
            re.compile(r"([\u4e00-\u9fff\d]{2,}[路街](\d+段)?\s*[\d\-\s之]+[號弄巷])"),
            # 直接找 路/街+號碼(含之) (不含 號)
            re.compile(r"([\u4e00-\u9fff\d]{2,}[路街](\d+段)?\s*[\d\-\s之]+)"),
        ]

        for pat in address_patterns:
            m = pat.search(text)
            if m:
                addr = re.sub(r"\s+", "", m.group(1))  # 移除內部多餘空格
                # 確保至少有數字（避免匹配到純路名）
                if re.search(r"\d", addr):
                    return addr

        # 回退：找 路名+號碼 (最寬鬆，允許路名含數字)
        road_pat = re.compile(r"([\u4e00-\u9fff\d]{2,}[路街])\s*(\d[\d\-\s]*\d?)")
        m = road_pat.search(text)
        if m:
            addr = m.group(1) + m.group(2)
            addr = re.sub(r"\s+", "", addr)
            return addr

        # 回退：找 縣市+行政區
        for city in self.CITIES:
            if city in text:
                idx = text.index(city)
                remainder = text[idx + len(city):idx + len(city) + 10]
                for district in self.DISTRICTS:
                    if district in remainder:
                        return f"{city}{district}"
                return city

        # 建立簡稱表 (lazy init)
        self._build_district_short_map()

        # 找獨立的行政區名稱（如 "大安區", "永和區", "永和", "內湖"）
        for short_name, full_name in sorted(
            self.DISTRICT_SHORT_MAP.items(),
            key=lambda x: -len(x[0])  # 長度優先
        ):
            if short_name in text:
                # 避免部分匹配 (如 "內湖" 匹配到 "內湖區" 已經用更長的匹配了)
                if short_name.endswith("區"):
                    return full_name
                # 確認是獨立的詞 (前後不是其他中文字)
                idx = text.index(short_name)
                # 檢查前一個字
                if idx > 0 and re.match(r"[\u4e00-\u9fff]", text[idx - 1]):
                    continue
                return full_name

        return None

    def _extract_floor(self, text: str) -> str | None:
        """萃取樓層資訊"""
        patterns = [
            re.compile(r"(\d+)\s*[FfＦｆ]\s*/\s*(\d+)\s*[FfＦｆ]"),
            re.compile(r"(\d+)\s*[/／]\s*(\d+)\s*[FfＦｆ樓]"),
            re.compile(r"(\d+)\s*[FfＦｆ]\s*[（(]\s*總?\s*(\d+)\s*[FfＦｆ樓]?\s*[)）]"),
            re.compile(r"第?\s*(\d+)\s*層"),
            re.compile(r"(\d+)\s*[FfＦｆ]"),
            re.compile(r"^B?(\d+)[層樓]", re.MULTILINE),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    return f"{m.group(1)}F/{m.group(2)}F"
                return f"{m.group(1)}F"
        return None

    def _extract_rooms(self, text: str) -> str | None:
        """萃取格局"""
        patterns = [
            re.compile(r"(\d+)\s*房\s*(\d+)\s*廳\s*(\d+)\s*衛"),
            re.compile(r"(\d+)\s*房\s*(\d+)\s*廳\s*(\d+)\s*浴"),
            re.compile(r"(\d+)\s*房\s*(\d+)\s*廳"),
            re.compile(r"(\d+)[/／](\d+)[/／](\d+)"),
            re.compile(r"(\d+)[房Rr]\s*(\d+)[廳Ll]\s*(\d+)[衛浴Bb]"),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                groups = m.groups()
                if len(groups) == 3:
                    return f"{groups[0]}房{groups[1]}廳{groups[2]}衛"
                elif len(groups) == 2:
                    return f"{groups[0]}房{groups[1]}廳"
        return None

    def _extract_community(self, text: str) -> str | None:
        """萃取社區名稱"""
        patterns = [
            re.compile(r"[\u4e00-\u9fff]{2,6}(新城|花園|城堡|帝寶|一號院|大院|天地|廣場|特區|莊園|世家|天下)"),
            re.compile(r"「([\u4e00-\u9fffA-Za-z0-9]{2,12})」"),
            re.compile(r"社區\s*[:：]?\s*([\u4e00-\u9fff]{2,10})"),
            re.compile(r"案名\s*[:：]?\s*([\u4e00-\u9fffA-Za-z0-9]{2,10})"),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                return m.group(1) if m.lastindex else m.group(0)
        return None

    def _extract_deposit(self, text: str) -> float | None:
        """萃取押金（以月為單位）"""
        patterns = [
            re.compile(r"押金\s*[:：]?\s*(\d+[.]?\d*)\s*[月個]"),
            re.compile(r"(\d+[.]?\d*)\s*[月個]押金"),
            re.compile(r"押\s*(\d+[.]?\d*)\s*[月個]"),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                return float(m.group(1))
        return None

    def _extract_management_fee(self, text: str) -> float | None:
        """萃取管理費（元/月）"""
        patterns = [
            re.compile(r"管理費\s*[:：]?\s*(\d+[,]?\d*)\s*[元塊]"),
            re.compile(r"(\d+[,]?\d*)\s*[元塊]?\s*[/／]\s*月.*管理"),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                val = m.group(1).replace(",", "")
                return float(val)
        return None

    def _extract_building_age(self, text: str) -> str | None:
        """萃取屋齡"""
        patterns = [
            re.compile(r"屋齡\s*[:：]?\s*(\d+[.]?\d*)\s*年"),
            re.compile(r"(\d+[.]?\d*)\s*年屋齡"),
            re.compile(r"(\d+)\s*年老?\s*(大樓|公寓|透天|華廈)"),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                return f"{m.group(1)}年"
        return None

    def is_sold_message(self, text: str) -> bool:
        """判斷是否為售出/成交訊息"""
        return any(kw in text for kw in self.SOLD_KEYWORDS)

    def is_promotion_message(self, text: str) -> bool:
        """判斷是否為推文/廣告訊息（非實際案件）"""
        score = sum(1 for kw in self.PROMOTION_KEYWORDS if kw in text)
        # 推文關鍵字 >= 2 個才算
        return score >= 2

    def _check_keywords(self, text: str, keywords: list[str]) -> bool:
        """檢查文字是否包含任一關鍵字"""
        return any(kw in text for kw in keywords)


# 全域萃取器實例
extractor = HousingExtractor()
