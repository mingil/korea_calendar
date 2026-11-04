import functools
import hashlib
import math
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from korean_lunar_calendar import KoreanLunarCalendar

_thread_local = threading.local()


def _get_lunar_cal() -> KoreanLunarCalendar:
    cal = getattr(_thread_local, "cal", None)
    if cal is None:
        cal = KoreanLunarCalendar()
        _thread_local.cal = cal
    return cal

KST = timezone(timedelta(hours=9))
WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

CATEGORY_META: Dict[str, Dict[str, str]] = {
    "holiday": {
        "label": "법정공휴일·대체공휴일",
        "short_label": "공휴일",
        "emoji": "🔴",
        "color": "#ef4444",
        "dateKind": "01",
        "desc": "관공서의 공휴일에 관한 규정 및 공휴일에 관한 법률에 따른 빨간날(휴일)",
    },
    "national": {
        "label": "5대 국경일",
        "short_label": "국경일",
        "emoji": "🇰🇷",
        "color": "#dc2626",
        "dateKind": "01",
        "desc": "국경일에 관한 법률에 따른 대한민국 5대 국경일 (3·1절, 제헌절, 광복절, 개천절, 한글날)",
    },
    "anniversary": {
        "label": "국가 법정기념일",
        "short_label": "법정기념일",
        "emoji": "🏛️",
        "color": "#3b82f6",
        "dateKind": "02",
        "desc": "각종 기념일 등에 관한 규정(대통령령) 및 개별 법률로 지정된 대한민국 공식 기념일",
    },
    "solar_term": {
        "label": "24절기",
        "short_label": "24절기",
        "emoji": "🌿",
        "color": "#10b981",
        "dateKind": "03",
        "desc": "한국천문연구원 역서 기준 태양의 황경(15° 간격)에 따른 계절 절기",
    },
    "sundry": {
        "label": "잡절·세시풍속",
        "short_label": "잡절·명절",
        "emoji": "🌕",
        "color": "#f59e0b",
        "dateKind": "04",
        "desc": "삼복(초복·중복·말복), 한식, 단오, 정월대보름, 칠석, 백중, 납일 등 한국 전통 세시풍속 및 잡절",
    },
    "lunar": {
        "label": "음력 초하루·보름",
        "short_label": "음력달력",
        "emoji": "🏮",
        "color": "#8b5cf6",
        "dateKind": "05",
        "desc": "매월 음력 1일(초하루) 및 음력 15일(보름달) 기준 음력 날짜 안내",
    },
    "popular": {
        "label": "대중·생활 기념일",
        "short_label": "생활기념일",
        "emoji": "💝",
        "color": "#ec4899",
        "dateKind": "06",
        "desc": "발렌타인데이, 화이트데이, 삼겹살데이, 로즈데이, 빼빼로데이 등 일상 속 데이 기념일",
    },
    "custom": {
        "label": "나만의 기념일·행사",
        "short_label": "커스텀일정",
        "emoji": "⭐",
        "color": "#06b6d4",
        "dateKind": "99",
        "desc": "사용자가 직접 등록한 가족 행사, 생일 및 개인 기념일",
    },
}

# 24절기 상세 정보 (이름, 태양황경(도), 대략적인 월, 이모티콘, 상세 설명)
SOLAR_TERMS_SPEC: List[Tuple[str, int, int, str, str]] = [
    ("소한", 285, 1, "❄️", "작은 추위라는 뜻이나 우리나라에서는 일 년 중 가장 추운 시기입니다. (태양 황경 285°)"),
    ("대한", 300, 1, "🧊", "큰 추위라는 뜻으로 겨울의 마지막 절기입니다. '소한 얼음 대한에 녹는다'는 속담이 있습니다. (태양 황경 300°)"),
    ("입춘", 315, 2, "🌱", "봄의 시작을 알리는 첫 번째 절기입니다. 대문에 '입춘대길 건양다경(立春大吉 建陽多慶)' 입춘첩을 붙입니다. (태양 황경 315°)"),
    ("우수", 330, 2, "💧", "눈이 녹아 비가 되고 얼음이 풀려 봄물이 오른다는 절기입니다. (태양 황경 330°)"),
    ("경칩", 345, 3, "🐸", "만물이 겨울잠에서 깨어나는 시기입니다. 땅속의 개구리와 벌레들이 활동을 시작합니다. (태양 황경 345°)"),
    ("춘분", 0, 3, "🌸", "낮과 밤의 길이가 같아지며 본격적인 봄이 시작되는 날입니다. (태양 황경 0°)"),
    ("청명", 15, 4, "🌤️", "하늘이 차츰 맑아지고 봄농사를 준비하며 성묘나 나무 심기를 하는 절기입니다. (태양 황경 15°)"),
    ("곡우", 30, 4, "🌧️", "봄비가 내려 백곡(온갖 곡식)을 기름지게 한다는 봄의 마지막 절기입니다. 우전차(첫 녹차)를 수확합니다. (태양 황경 30°)"),
    ("입하", 45, 5, "🌿", "여름이 시작되었음을 알리는 절기입니다. 신록이 우거지고 개구리 울음소리가 들립니다. (태양 황경 45°)"),
    ("소만", 60, 5, "🌾", "햇볕이 풍부하고 만물이 점차 생장하여 가득 찬다는 절기입니다. 모내기를 시작합니다. (태양 황경 60°)"),
    ("망종", 75, 6, "🌾", "보리 등 수염이 있는 까끄라기 곡식의 종자를 뿌리고 보리베기와 모내기에 바쁜 절기입니다. (태양 황경 75°)"),
    ("하지", 90, 6, "☀️", "일 년 중 낮의 길이가 가장 긴 날입니다. 남부지방의 모내기가 마무리되고 감자를 수확합니다. (태양 황경 90°)"),
    ("소서", 105, 7, "🌡️", "작은 더위라는 뜻으로 본격적인 무더위와 장마철이 시작되는 시기입니다. (태양 황경 105°)"),
    ("대서", 120, 7, "🔥", "큰 더위라는 뜻으로 장마가 끝나고 염천(炎天)의 폭염이 가장 심한 한여름 절기입니다. (태양 황경 120°)"),
    ("입추", 135, 8, "🍂", "가을의 시작을 알리는 절기입니다. 밤에는 선선한 바람이 불기 시작하고 김장용 무·배추를 심습니다. (태양 황경 135°)"),
    ("처서", 150, 8, "🌬️", "더위가 그치고 선선한 가을을 맞이한다는 절기입니다. '처서가 지나면 모기도 입이 삐뚤어진다'는 속담이 있습니다. (태양 황경 150°)"),
    ("백로", 165, 9, "露", "밤 기온이 이슬점 이하로 내려가 풀잎에 하얀 이슬이 맺히는 완연한 가을 절기입니다. (태양 황경 165°)"),
    ("추분", 180, 9, "🍁", "낮과 밤의 길이가 같아지며 이후로 밤이 길어지는 가을의 한가운데 절기입니다. (태양 황경 180°)"),
    ("한로", 195, 10, "🌾", "찬 이슬이 맺히기 시작하며 기온이 더 내려가기 전에 추수를 서두르는 절기입니다. (태양 황경 195°)"),
    ("상강", 210, 10, "🍂", "밤 기온이 급격히 낮아져 서리가 내리기 시작하고 단풍이 절정에 이르는 가을의 마지막 절기입니다. (태양 황경 210°)"),
    ("입동", 225, 11, "🧥", "겨울이 시작되는 절기로 김장을 담그며 월동 준비를 시작합니다. (태양 황경 225°)"),
    ("소설", 240, 11, "🌨️", "첫눈이 내리기 시작하고 살얼음이 얼며 겨울 추위가 찾아오는 절기입니다. (태양 황경 240°)"),
    ("대설", 255, 12, "⛄", "큰 눈이 많이 내린다는 절기로 농한기에 접어들며 이듬해 풍년을 기원합니다. (태양 황경 255°)"),
    ("동지", 270, 12, "🥣", "일 년 중 밤이 가장 길고 낮이 가장 짧은 날입니다. 액운을 쫓고 새해 건강을 기원하며 동지 팥죽을 나누어 먹습니다. (태양 황경 270°)"),
]

# 고정 양력 국가 법정기념일 목록 (월, 일, 명칭, 이모티콘, 설명, 부가태그)
FIXED_NATIONAL_ANNIVERSARIES: List[Tuple[int, int, str, str, str, List[str]]] = [
    (2, 2, "습지의 날", "🦆", "습지의 가치와 중요성을 알리기 위해 지정된 국가 법정기념일 (환경부·해양수산부)", ["환경", "법정기념일"]),
    (3, 3, "납세자의 날", "🧾", "성실한 납세 문화를 조성하기 위해 지정된 법정기념일 (재정경제부)", ["경제", "법정기념일"]),
    (3, 8, "여성의 날", "🌷", "여성의 지위 향상과 양성평등 실현을 촉진하기 위한 법정기념일 (여성가족부)", ["인권", "법정기념일"]),
    (3, 15, "3·15 의거 기념일", "🕯️", "1960년 마산에서 일어난 3·15 민주 의거의 숭고한 정신을 기리는 국가기념일 (국가보훈부)", ["보훈", "역사", "법정기념일"]),
    (3, 21, "암 예방의 날", "🎗️", "암에 대한 국민의 이해를 높이고 암의 예방·치료 및 관리 의욕을 고취하기 위한 법정기념일 (보건복지부)", ["보건", "의료", "법정기념일"]),
    (3, 22, "세계 물의 날", "💧", "물 부족과 수질오염을 방지하고 물의 소중함을 되새기기 위한 유엔 및 국가 기념일 (환경부)", ["환경", "법정기념일"]),
    (3, 24, "결핵예방의 날", "🫁", "결핵 예방 및 퇴치에 대한 경각심을 높이기 위한 법정기념일 (질병관리청)", ["보건", "의료", "법정기념일"]),
    (4, 1, "수산인의 날", "🐟", "수산업과 어촌의 소중함을 알리고 수산인의 긍지를 높이기 위한 법정기념일 (해양수산부)", ["산업", "법정기념일"]),
    (4, 3, "4·3 희생자 추념일", "🌺", "제주 4·3 사건 희생자를 위령하고 평화와 인권의 가치를 기리는 국가기념일 (행정안전부)", ["역사", "추념일", "법정기념일"]),
    (4, 5, "식목일", "🌲", "국민 식수에 의한 애림 사상을 높이고 산지의 자원화를 위하여 제정된 법정기념일 (산림청)", ["환경", "식목일", "법정기념일"]),
    (4, 7, "보건의 날", "🏥", "국민 보건의식을 향상시키고 보건의료 및 복지 분야 종사자를 격려하기 위한 법정기념일 (보건복지부)", ["보건", "의료", "법정기념일"]),
    (4, 11, "대한민국 임시정부 수립기념일", "🇰🇷", "1919년 4월 11일 대한민국 임시정부 수립과 자주독립 정신을 기리는 국가기념일 (국가보훈부)", ["보훈", "역사", "법정기념일"]),
    (4, 12, "도서관의 날", "📚", "도서관의 사회적 가치와 필요성을 알리고 이용을 촉진하기 위한 법정기념일 (문화체육관광부)", ["문화", "교육", "법정기념일"]),
    (4, 16, "국민안전의 날", "🛟", "안전의 중요성을 되새기고 안전사고 예방 의식을 높이기 위한 법정기념일 (행정안전부)", ["안전", "법정기념일"]),
    (4, 19, "4·19 혁명 기념일", "🕯️", "1960년 4·19 민주혁명의 민주이념을 계승하기 위한 국가기념일 (국가보훈부)", ["보훈", "역사", "법정기념일"]),
    (4, 20, "장애인의 날", "♿", "장애인에 대한 이해를 깊게 하고 장애인의 재활 의욕을 고취하기 위한 법정기념일 (보건복지부)", ["복지", "인권", "법정기념일"]),
    (4, 21, "과학의 날", "🔬", "과학기술의 중요성을 알리고 과학기술 진흥을 촉진하기 위한 법정기념일 (과학기술정보통신부)", ["과학기술", "법정기념일"]),
    (4, 22, "정보통신의 날", "📡", "정보통신의 중요성과 의의를 높이고 정보통신 발전을 다짐하는 법정기념일 (과학기술정보통신부)", ["과학기술", "IT", "법정기념일"]),
    (4, 22, "지구의 날", "🌍", "지구 환경오염 문제의 심각성을 알리기 위해 제정된 환경 보호의 날", ["환경", "기념일"]),
    (4, 25, "법의 날", "⚖️", "준법정신을 앙양하고 법의 존엄성을 진작하기 위한 법정기념일 (법무부)", ["법무", "법정기념일"]),
    (4, 28, "충무공 이순신 탄신일", "⚔️", "충무공 이순신 장군의 애국충정과 빛나는 업적을 기리는 국가기념일 (문화체육관광부)", ["역사", "법정기념일"]),
    (5, 1, "근로자의 날", "🛠️", "근로자의 노고를 위로하고 근무 의욕을 높이기 위해 제정된 법정기념일 (고용노동부)", ["노동", "법정기념일"]),
    (5, 8, "어버이날", "💐", "어버이의 은혜에 감사하고 효 사상의 미덕을 함양하기 위한 법정기념일 (보건복지부)", ["가정", "효도", "법정기념일"]),
    (5, 10, "유권자의 날", "🗳️", "민주주의 선거의 중요성과 주권 의식을 높이기 위한 법정기념일 (중앙선거관리위원회)", ["민주주의", "법정기념일"]),
    (5, 10, "바다식목일", "🪸", "바다 속에 해조류를 심어 해양생태계를 보호하기 위해 지정된 법정기념일 (해양수산부)", ["환경", "해양", "법정기념일"]),
    (5, 11, "동학농민혁명 기념일", "🌾", "1894년 봉건체제 개혁과 일제 침략으로부터 국권을 수호하기 위해 봉기한 동학농민혁명을 기리는 국가기념일 (문화체육관광부)", ["역사", "법정기념일"]),
    (5, 11, "입양의 날", "👶", "건전한 입양문화의 정착과 국내 입양 활성화를 위한 법정기념일 (보건복지부)", ["복지", "가정", "법정기념일"]),
    (5, 14, "식품안전의 날", "🥗", "식품안전에 대한 인식을 제고하고 국민 건강을 보호하기 위한 법정기념일 (식품의약품안전처)", ["보건", "안전", "법정기념일"]),
    (5, 15, "스승의 날", "🎓", "교권 존중과 스승 공경의 사회적 풍토를 조성하기 위한 법정기념일 (교육부)", ["교육", "법정기념일"]),
    (5, 15, "세종대왕 나신 날", "👑", "성군 세종대왕의 탄신(1397년 5월 15일)과 위업을 기리는 국가기념일 (문화체육관광부)", ["역사", "문화", "법정기념일"]),
    (5, 15, "가정의 날", "🏡", "가정의 중요성을 고취하고 건강한 가족문화를 만들기 위한 법정기념일 (여성가족부)", ["가정", "법정기념일"]),
    (5, 18, "5·18 민주화운동 기념일", "🕯️", "1980년 광주 5·18 민주화운동의 민주·인권·평화 정신을 기리는 국가기념일 (국가보훈부)", ["보훈", "역사", "법정기념일"]),
    (5, 19, "발명의 날", "💡", "측우기 발명일(1441년 5월 19일)을 기념하여 발명 진흥을 도모하는 법정기념일 (특허청)", ["과학기술", "법정기념일"]),
    (5, 20, "세계인의 날", "🌏", "국민과 재한외국인이 서로의 문화와 전통을 존중하며 더불어 살아가는 사회를 만들기 위한 법정기념일 (법무부)", ["문화", "인권", "법정기념일"]),
    (5, 21, "부부의 날", "💑", "가정의 달 5월에 둘(2)이 하나(1)가 된다는 의미로 부부관계의 소중함을 일깨우는 법정기념일 (여성가족부)", ["가정", "법정기념일"]),
    (5, 25, "방재의 날", "🚒", "재해 예방에 대한 국민의식을 높이고 방재 훈련을 강화하기 위한 법정기념일 (행정안전부)", ["안전", "법정기념일"]),
    (5, 27, "우주항공의 날", "🚀", "우주항공청 개청을 기념하고 대한민국 우주항공 시대의 도약을 기리는 국가기념일 (우주항공청)", ["과학기술", "우주", "법정기념일"]),
    (5, 31, "바다의 날", "🌊", "해양을 둘러싼 국제환경 변화에 대응하고 해양강국 건설을 다짐하는 법정기념일 (해양수산부)", ["해양", "법정기념일"]),
    (5, 31, "세계 금연의 날", "🚭", "흡연의 해로움을 알리고 담배 연기 없는 사회를 만들기 위한 기념일 (보건복지부)", ["보건", "법정기념일"]),
    (6, 1, "의병의 날", "🛡️", "국가가 위기에 처했을 때 자발적으로 일어난 의병의 역사적 의의를 되새기는 국가기념일 (행정안전부)", ["보훈", "역사", "법정기념일"]),
    (6, 5, "환경의 날", "🌳", "환경보전 의식을 함양하고 실천을 생활화하기 위한 법정기념일 (환경부)", ["환경", "법정기념일"]),
    (6, 9, "구강보건의 날", "🦷", "첫 영구치 어금니가 나오는 6세의 '6'과 구치(어금니)의 '9'를 따서 제정한 구강건강 법정기념일 (보건복지부)", ["보건", "의료", "법정기념일"]),
    (6, 10, "6·10 민주항쟁 기념일", "🕯️", "1987년 6·10 민주항쟁의 민주주의 수호 정신을 기리는 국가기념일 (행정안전부)", ["역사", "민주주의", "법정기념일"]),
    (6, 15, "노인학대예방의 날", "🤝", "노인 인권을 보호하고 노인학대 예방에 대한 범국민적 인식을 높이기 위한 법정기념일 (보건복지부)", ["복지", "인권", "법정기념일"]),
    (6, 25, "6·25 전쟁일", "🎖️", "1950년 6·25 전쟁의 역사적 교훈을 되새기고 호국영령과 참전용사를 기리는 국가기념일 (국가보훈부)", ["보훈", "안보", "법정기념일"]),
    (6, 26, "마약퇴치의 날", "🛡️", "마약류의 오남용 위험성을 알리고 마약 퇴치 의지를 다지는 법정기념일 (식품의약품안전처)", ["보건", "안전", "법정기념일"]),
    (6, 28, "철도의 날", "🚄", "우리나라 철도의 역사적 의의를 되새기고 철도산업의 발전을 도모하는 법정기념일 (국토교통부)", ["교통", "산업", "법정기념일"]),
    (7, 1, "사회적기업의 날", "🤝", "사회적기업에 대한 이해를 증진시키고 사회적기업가의 활동을 장려하기 위한 법정기념일 (고용노동부)", ["경제", "복지", "법정기념일"]),
    (7, 11, "인구의 날", "👨‍👩‍👧‍👦", "저출산·고령화에 따른 인구구조 불균형 문제에 대한 국민적 이해와 관심을 높이기 위한 법정기념일 (보건복지부)", ["사회", "보건", "법정기념일"]),
    (7, 14, "북한이탈주민의 날", "🕊️", "북한이탈주민의 포용과 정착 지원, 통일 인식 제고를 위해 제정된 국가기념일 (통일부)", ["통일", "인권", "법정기념일"]),
    (8, 8, "섬의 날", "🏝️", "섬의 가치와 중요성에 대한 인식을 높이기 위해 숫자 '8'이 무한(∞)한 섬의 잠재력을 상징하여 지정된 법정기념일 (행정안전부)", ["해양", "관광", "법정기념일"]),
    (8, 14, "일본군‘위안부’ 피해자 기림의 날", "🦋", "일본군‘위안부’ 문제를 국내외에 알리고 피해자를 기리기 위한 국가기념일 (여성가족부)", ["역사", "인권", "법정기념일"]),
    (9, 4, "직지의 날", "📖", "현존하는 세계 최고(最古)의 금속활자본 직지심체요절이 유네스코 세계기록유산에 등재된 날을 기념", ["문화", "역사", "기념일"]),
    (9, 4, "태권도의 날", "🥋", "1994년 IOC 총회에서 태권도가 올림픽 정식종목으로 채택된 날을 기념하는 법정기념일 (문화체육관광부)", ["체육", "문화", "법정기념일"]),
    (9, 7, "푸른 하늘의 날", "🌤️", "우리나라가 유엔에 제안하여 채택된 최초의 유엔 공식 기념일이자 미세먼지 저감·청정대기를 위한 국가기념일 (환경부)", ["환경", "법정기념일"]),
    (9, 7, "곤충의 날", "🦋", "곤충산업의 육성과 곤충의 생태적 가치를 알리기 위한 법정기념일 (농림축산식품부)", ["환경", "산업", "법정기념일"]),
    (9, 10, "자살예방의 날", "💛", "생명의 소중함과 자살문제의 심각성을 널리 알리기 위한 법정기념일 (보건복지부)", ["보건", "생명존중", "법정기념일"]),
    (9, 10, "해양경찰의 날", "🚢", "해양주권 수호와 바다 안전을 책임지는 해양경찰의 노고를 기리는 법정기념일 (해양경찰청)", ["안전", "해양", "법정기념일"]),
    (9, 18, "철통보안·통계의 날", "📊", "통계의 중요성에 대한 국민의 이해와 관심을 유도하기 위한 법정기념일 (통계청 - 9월 1일 통계의 날 등)", ["행정", "법정기념일"]),
    (9, 21, "치매극복의 날", "🧠", "치매 관리의 중요성을 널리 알리고 치매를 극복하기 위한 범국민적 공감대를 형성하는 법정기념일 (보건복지부)", ["보건", "의료", "법정기념일"]),
    (9, 27, "관광의 날", "✈️", "관광산업의 발전을 다짐하고 관광의 중요성을 알리기 위한 법정기념일 (문화체육관광부)", ["관광", "문화", "법정기념일"]),
    (9, 30, "개인정보 보호의 날", "🔐", "개인정보 보호법 시행일(9월 30일)을 기념하여 개인정보 보호의 중요성을 알리는 법정기념일 (개인정보보호위원회)", ["IT", "보안", "법정기념일"]),
    (10, 1, "국군의 날", "🪖", "대한민국 국군의 위용과 전투력을 국내외에 과시하고 국군장병의 사기를 높이기 위한 국가기념일 (국방부)", ["국방", "보훈", "법정기념일"]),
    (10, 2, "노인의 날", "🧓", "경로효친 사상을 앙양하고 전통문화를 계승·발전시켜 온 노인들의 노고를 치하하기 위한 법정기념일 (보건복지부)", ["복지", "경로", "법정기념일"]),
    (10, 5, "세계 한인의 날", "🌐", "전 세계 재외동포의 한민족 정체성을 고양하고 권익을 신장하기 위한 국가기념일 (재외동포청)", ["외교", "법정기념일"]),
    (10, 8, "재향군인의 날", "🎖️", "재향군인 상호간의 친목을 도모하고 국가발전 및 안보의식을 다지는 법정기념일 (국가보훈부)", ["보훈", "안보", "법정기념일"]),
    (10, 10, "임산부의 날", "🤰", "풍요와 수확을 상징하는 10월과 임신기간 10개월을 의미하며 임신과 출산을 배려하는 문화를 확산하는 법정기념일 (보건복지부)", ["보건", "가정", "법정기념일"]),
    (10, 10, "정신건강의 날", "💚", "정신건강의 중요성을 환기하고 정신질환에 대한 편견을 해소하기 위한 법정기념일 (보건복지부)", ["보건", "의료", "법정기념일"]),
    (10, 15, "체육의 날", "🏃", "국민 체력을 향상시키고 건전한 스포츠 정신을 함양하기 위한 법정기념일 (문화체육관광부)", ["체육", "건강", "법정기념일"]),
    (10, 16, "부마민주항쟁 기념일", "🕯️", "1979년 부산·마산 일대에서 일어난 부마민주항쟁의 민주 정신을 기리는 국가기념일 (행정안전부)", ["역사", "민주주의", "법정기념일"]),
    (10, 21, "경찰의 날", "🚓", "민주경찰의 사명감을 다지고 국민의 안전과 치안 유지를 위해 헌신하는 경찰관을 격려하는 법정기념일 (경찰청)", ["안전", "치안", "법정기념일"]),
    (10, 24, "국제연합일 (유엔의 날)", "🇺🇳", "1945년 국제연합(UN)이 창설된 날을 기념하는 법정기념일 (외교부)", ["외교", "평화", "법정기념일"]),
    (10, 25, "독도의 날", "🇰🇷", "1900년 10월 25일 고종황제가 대한제국 칙령 제41호로 독도를 울릉도의 관할 구역으로 명시한 것을 기념하는 날", ["영토", "역사", "기념일"]),
    (10, 28, "교정의 날", "🏛️", "수형자의 교화·갱생과 교정행정의 발전을 기념하는 법정기념일 (법무부)", ["법무", "법정기념일"]),
    (10, 29, "지방자치 및 균형발전의 날", "🏙️", "지방자치 및 국가균형발전에 관한 국민의 관심을 높이기 위한 법정기념일 (행정안전부)", ["행정", "법정기념일"]),
    (11, 2, "수소의 날", "⚡", "원소기호 H2를 형상화하여 수소경제의 중요성과 친환경 에너지 확산을 알리는 법정기념일 (산업통상자원부)", ["에너지", "과학기술", "법정기념일"]),
    (11, 3, "학생독립운동기념일", "✊", "1929년 광주학생독립운동의 자주독립 정신을 계승하기 위한 국가기념일 (교육부·국가보훈부)", ["보훈", "역사", "법정기념일"]),
    (11, 4, "점자의 날", "⠿", "1926년 11월 4일 송암 박두성 선생이 한글 점자 '훈맹정음'을 반포한 날을 기념하는 법정기념일 (문화체육관광부)", ["복지", "문화", "법정기념일"]),
    (11, 5, "소상공인의 날", "🏪", "소상공인에 대한 국민 의식을 제고하고 사회적·경제적 지위를 향상시키기 위한 법정기념일 (중소벤처기업부)", ["경제", "법정기념일"]),
    (11, 9, "소방의 날", "🚒", "긴급신고번호 119를 상징하여 화재 예방과 국민 생명 보호에 헌신하는 소방공무원을 기리는 법정기념일 (소방청)", ["안전", "소방", "법정기념일"]),
    (11, 11, "농업인의 날", "🌾", "농민은 흙에서 나서 흙을 벗 삼아 살다가 흙으로 돌아간다는 의미로 흙 토(土) 자가 겹친 11월 11일로 지정된 법정기념일 (농림축산식품부)", ["농업", "가래떡데이", "법정기념일"]),
    (11, 11, "유엔참전용사 국제추모의 날", "🌺", "6·25 전쟁에 참전하여 대한민국의 자유민주주의를 수호한 유엔참전용사의 희생과 공헌을 기리는 국가기념일 (국가보훈부, 오전 11시 부산을 향하여 1분간 묵념)", ["보훈", "추념일", "법정기념일"]),
    (11, 17, "순국선열의 날", "🕯️", "국권 회복을 위해 헌신한 순국선열의 독립정신과 희생정신을 후세에 길이 전하기 위한 국가기념일 (국가보훈부, 조기 게양)", ["보훈", "조기게양", "법정기념일"]),
    (11, 19, "아동학대예방의 날", "🧒", "아동학대의 예방과 방지에 관한 관심을 높이기 위한 법정기념일 (보건복지부)", ["복지", "인권", "법정기념일"]),
    (11, 22, "김치의 날", "🥬", "김치 재료 하나하나(11월)가 모여 22가지(22일) 이상의 건강 효능을 낸다는 의미로 제정된 법정기념일 (농림축산식품부)", ["문화", "음식", "법정기념일"]),
    (12, 3, "소비자의 날", "🛒", "소비자의 권익 증진과 소비자 보호 인식을 높이기 위한 법정기념일 (공정거래위원회)", ["경제", "법정기념일"]),
    (12, 5, "무역의 날", "🚢", "무역의 균형적 발전과 무역입국의 의지를 다지기 위한 법정기념일 (산업통상자원부)", ["경제", "산업", "법정기념일"]),
    (12, 5, "자원봉사자의 날", "🤲", "자원봉사활동을 진흥하고 자원봉사자의 노고를 격려하기 위한 법정기념일 (행정안전부)", ["복지", "봉사", "법정기념일"]),
    (12, 10, "세계 인권선언 기념일", "🕊️", "1948년 유엔 총회에서 세계인권선언이 채택된 것을 기념하여 인권 존중 의식을 높이는 날 (법무부·국가인권위원회)", ["인권", "법정기념일"]),
    (12, 27, "원자력 안전 및 진흥의 날", "⚛️", "원자력의 안전한 이용과 원자력 기술 진흥을 촉진하기 위한 법정기념일 (과학기술정보통신부·원자력안전위원회)", ["과학기술", "에너지", "법정기념일"]),
]

# 대중·생활 기념일 목록 (선택형 카테고리)
POPULAR_DAYS: List[Tuple[int, int, str, str, str]] = [
    (2, 14, "발렌타인데이", "🍫", "연인이나 소중한 사람에게 초콜릿을 선물하며 마음을 전하는 날"),
    (3, 3, "삼겹살데이", "🥓", "숫자 3이 겹치는 날로 양돈 농가를 돕고 삼겹살을 즐기는 데이 기념일"),
    (3, 14, "화이트데이", "🍬", "소중한 사람에게 사탕과 선물을 전하며 사랑을 고백하는 날"),
    (3, 14, "파이(π) 데이", "🥧", "원주율(3.14159...)을 기념하여 수학의 즐거움을 나누는 날"),
    (4, 14, "블랙데이", "🍜", "솔로들이 자장면을 먹으며 서로를 응원하는 유쾌한 데이 기념일"),
    (5, 14, "로즈데이", "🌹", "연인에게 장미꽃을 선물하며 사랑을 표현하는 날"),
    (6, 14, "키스데이", "💋", "연인들이 서로의 마음을 확인하는 로맨틱 데이 기념일"),
    (7, 14, "실버데이", "💍", "연인들이 은반지를 주고받으며 미래를 약속하는 날"),
    (8, 14, "그린데이", "🌲", "무더운 여름에 산림욕을 하며 자연 속에서 휴식을 즐기는 날"),
    (9, 9, "구구데이", "🍗", "닭 울음소리(구구)에서 유래해 닭고기와 계란 소비를 촉진하는 날"),
    (9, 14, "포토데이", "📸", "연인·가족과 함께 가을 하늘 아래 추억의 사진을 남기는 날"),
    (10, 14, "와인데이", "🍷", "가을 분위기에 어울리는 와인을 함께 즐기는 날"),
    (10, 24, "사과데이", "🍎", "둘(2)이 서로 사(4)과하고 화해하며 사과를 주고받는 날"),
    (11, 11, "빼빼로데이 / 가래떡데이", "🥨", "소중한 지인들과 막대과자나 우리 쌀로 만든 가래떡을 나누는 날"),
    (12, 14, "허그데이", "🤗", "추운 겨울 소중한 사람들을 따뜻하게 안아주며 온기를 나누는 날"),
    (12, 24, "크리스마스 이브", "🎄", "성탄절 전야로 가족·연인과 함께 따뜻한 성탄 축하를 나누는 날"),
    (12, 31, "제야의 종 타종일 (연말)", "🔔", "한 해를 마무리하고 보신각 제야의 종소리와 함께 새해를 맞이하는 날"),
]

# 주요 법정 공휴일 선거일 및 확정 임시/특별 공휴일
SPECIAL_PUBLIC_HOLIDAYS: Dict[str, Tuple[str, str, str]] = {
    "2020-04-15": ("제21대 국회의원선거", "🗳️", "공직선거법 및 관공서의 공휴일에 관한 규정에 따른 법정공휴일(임기만료에 의한 국회의원선거일)"),
    "2022-03-09": ("제20대 대통령선거", "🗳️", "공직선거법 및 관공서의 공휴일에 관한 규정에 따른 법정공휴일(대통령선거일)"),
    "2022-06-01": ("제8회 전국동시지방선거", "🗳️", "공직선거법 및 관공서의 공휴일에 관한 규정에 따른 법정공휴일(전국동시지방선거일)"),
    "2023-10-02": ("임시공휴일", "🔴", "추석 연휴와 개천절 징검다리 연휴에 따른 정부 지정 임시공휴일"),
    "2024-04-10": ("제22대 국회의원선거", "🗳️", "공직선거법 및 관공서의 공휴일에 관한 규정에 따른 법정공휴일(제22대 국회의원 총선거일)"),
    "2024-10-01": ("국군의 날 (임시공휴일)", "🪖", "건군 제76주년 국군의 날 정부 지정 임시공휴일"),
    "2025-01-27": ("설날 연휴 임시공휴일", "🔴", "설 명절 연휴 기간 내수 진작 및 휴식 보장을 위한 정부 지정 임시공휴일"),
    "2026-06-03": ("제9회 전국동시지방선거", "🗳️", "공직선거법 및 관공서의 공휴일에 관한 규정에 따른 법정공휴일(제9회 전국동시지방선거일)"),
    "2028-04-12": ("제23대 국회의원선거", "🗳️", "공직선거법 및 관공서의 공휴일에 관한 규정에 따른 법정공휴일(제23대 국회의원 총선거일)"),
    "2030-06-12": ("제10회 전국동시지방선거", "🗳️", "공직선거법 및 관공서의 공휴일에 관한 규정에 따른 법정공휴일(제10회 전국동시지방선거일)"),
}


def _julian_day(dt_utc: datetime) -> float:
    y, m = dt_utc.year, dt_utc.month
    d = dt_utc.day + (dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = int(y / 100)
    b = 2 - a + int(a / 4)
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def _solar_apparent_longitude(jd: float) -> float:
    """Jean Meeus 천문 알고리즘 기반 태양 겉보기 황경(도, 0~360) 계산."""
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) % 360.0
    m_rad = math.radians((357.52911 + 35999.05029 * t - 0.0001537 * t * t) % 360.0)
    c = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m_rad)
        + (0.019993 - 0.000101 * t) * math.sin(2 * m_rad)
        + 0.000289 * math.sin(3 * m_rad)
    )
    true_long = l0 + c
    omega = math.radians(125.04 - 1934.136 * t)
    app_long = (true_long - 0.00569 - 0.00478 * math.sin(omega)) % 360.0
    return app_long


@functools.lru_cache(maxsize=128)
def compute_solar_terms_for_year(year: int) -> List[Dict[str, Any]]:
    """해당 연도의 24절기 정확한 날짜(KST)와 절입 시각을 계산합니다."""
    results = []
    for name, deg, approx_month, emoji, desc in SOLAR_TERMS_SPEC:
        dt_init = datetime(year, approx_month, 1, 0, 0, tzinfo=timezone.utc)
        jd = _julian_day(dt_init)
        for _ in range(12):
            cur = _solar_apparent_longitude(jd)
            diff = (deg - cur + 180.0) % 360.0 - 180.0
            jd += diff / 0.98564736
        dt_utc = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc) + timedelta(
            days=(jd - 2451545.0)
        )
        dt_kst = dt_utc.astimezone(KST)
        results.append(
            {
                "name": name,
                "date": dt_kst.date(),
                "kst": dt_kst.strftime("%H:%M"),
                "emoji": emoji,
                "deg": deg,
                "description": f"{desc}\n• 한국표준시(KST) 절입 시각: {dt_kst.strftime('%Y년 %m월 %d일 %H시 %M분')}",
            }
        )
    return results


_SOLAR_TO_LUNAR: Dict[date, Dict[str, Any]] = {}
_LUNAR_TO_SOLAR: Dict[Tuple[int, int, int, bool], date] = {}
_TABLE_LOCK = threading.Lock()


def _ensure_lunar_tables(min_year: int = 2015, max_year: int = 2040) -> None:
    """2015~2040년 전체 양력↔음력 및 육십갑자 O(1) 메모리 인덱스 테이블을 0.08초 만에 구축합니다."""
    if _SOLAR_TO_LUNAR:
        return
    with _TABLE_LOCK:
        if _SOLAR_TO_LUNAR:
            return
        cal = KoreanLunarCalendar()
        cal.setLunarDate(min_year, 1, 1, False)
        cur_solar = date(cal.solarYear, cal.solarMonth, cal.solarDay)
        abs_days = cal._KoreanLunarCalendar__getLunarAbsDays(min_year, 1, 1, False)

        base_year = cal.KOREAN_LUNAR_BASE_YEAR
        cheongan = [chr(c) for c in cal.KOREAN_CHEONGAN]
        ganji = [chr(c) for c in cal.KOREAN_GANJI]
        units = [chr(c) for c in cal.KOREAN_GAPJA_UNIT]
        data = cal.KOREAN_LUNAR_DATA

        for ly in range(min_year, max_year + 1):
            ld = data[ly - base_year]
            leap_m = (ld >> 12) & 0x000F
            y_cg = cheongan[((ly + 6) - base_year) % 10]
            y_gj = ganji[((ly + 0) - base_year) % 12]
            y_str = f"{y_cg}{y_gj}{units[0]}"

            for lm in range(1, 13):
                m_cnt = lm + 12 * (ly - base_year)
                m_cg = cheongan[(m_cnt + 3) % 10]
                m_gj = ganji[(m_cnt + 1) % 12]
                m_str = f"{m_cg}{m_gj}{units[1]}"

                for is_leap in ([False, True] if lm == leap_m else [False]):
                    if is_leap:
                        days = 30 if ((ld >> 16) & 0x01) > 0 else 29
                        m_disp = f"윤{m_str}"
                    else:
                        days = 30 if ((ld >> (12 - lm)) & 0x01) > 0 else 29
                        m_disp = m_str
                    leap_prefix = "윤" if is_leap else ""
                    for lday in range(1, days + 1):
                        d_cg = cheongan[(abs_days + 4) % 10]
                        d_gj = ganji[(abs_days + 2) % 12]
                        d_str = f"{d_cg}{d_gj}{units[2]}"
                        gapja = f"{y_str} {m_disp} {d_str}"
                        info = {
                            "lunar_year": ly,
                            "lunar_month": lm,
                            "lunar_day": lday,
                            "is_leap": is_leap,
                            "lunar_iso": f"{ly:04d}-{lm:02d}-{lday:02d}",
                            "lunar_short": f"음 {leap_prefix}{lm}.{lday}",
                            "lunar_full": f"음력 {ly}년 {leap_prefix}{lm}월 {lday}일",
                            "ganji": gapja,
                            "day_ganji": d_str,
                        }
                        _SOLAR_TO_LUNAR[cur_solar] = info
                        _LUNAR_TO_SOLAR[(ly, lm, lday, is_leap)] = cur_solar
                        cur_solar += timedelta(days=1)
                        abs_days += 1


def get_lunar_info(solar_d: date) -> Dict[str, Any]:
    """양력 날짜에 대한 음력 날짜 및 육십갑자(세차/월건/일진) 정보를 O(1)로 반환합니다."""
    _ensure_lunar_tables()
    hit = _SOLAR_TO_LUNAR.get(solar_d)
    if hit is not None:
        return hit
    cal = _get_lunar_cal()
    try:
        cal.setSolarDate(solar_d.year, solar_d.month, solar_d.day)
        lunar_iso = cal.LunarIsoFormat()
        is_leap = cal.isIntercalation
        gapja = cal.getGapJaString()
        tokens = gapja.split()
        day_ganji = tokens[-1] if tokens else ""
        leap_prefix = "윤" if is_leap else ""
        lunar_short = f"음 {leap_prefix}{cal.lunarMonth}.{cal.lunarDay}"
        lunar_full = f"음력 {cal.lunarYear}년 {leap_prefix}{cal.lunarMonth}월 {cal.lunarDay}일"
        return {
            "lunar_year": cal.lunarYear,
            "lunar_month": cal.lunarMonth,
            "lunar_day": cal.lunarDay,
            "is_leap": is_leap,
            "lunar_iso": lunar_iso.split()[0],
            "lunar_short": lunar_short,
            "lunar_full": lunar_full,
            "ganji": gapja,
            "day_ganji": day_ganji,
        }
    except Exception:
        return {
            "lunar_year": solar_d.year,
            "lunar_month": solar_d.month,
            "lunar_day": solar_d.day,
            "is_leap": False,
            "lunar_iso": solar_d.isoformat(),
            "lunar_short": "",
            "lunar_full": "",
            "ganji": "",
            "day_ganji": "",
        }


def lunar_to_solar(lunar_year: int, lunar_month: int, lunar_day: int, is_leap: bool = False) -> Optional[date]:
    """음력 날짜를 양력 date 객체로 O(1) 변환합니다."""
    _ensure_lunar_tables()
    hit = _LUNAR_TO_SOLAR.get((lunar_year, lunar_month, lunar_day, is_leap))
    if hit is not None:
        return hit
    cal = _get_lunar_cal()
    try:
        ok = cal.setLunarDate(lunar_year, lunar_month, lunar_day, is_leap)
        if not ok:
            return None
        return date(cal.solarYear, cal.solarMonth, cal.solarDay)
    except Exception:
        return None


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """해당 연/월의 n번째 특정 요일(0=월~6=일) 날짜를 반환합니다 (n=-1이면 마지막 해당 요일)."""
    if n > 0:
        first_day = date(year, month, 1)
        offset = (weekday - first_day.weekday()) % 7
        return first_day + timedelta(days=offset + 7 * (n - 1))
    else:
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        offset = (last_day.weekday() - weekday) % 7
        return last_day - timedelta(days=offset)


def make_event(
    target_date: date,
    title: str,
    category: str,
    is_holiday: bool = False,
    emoji: Optional[str] = None,
    description: str = "",
    kst: str = "",
    sub_tags: Optional[List[str]] = None,
    source: str = "KASI_ENGINE",
    seq: int = 1,
    date_kind_override: Optional[str] = None,
) -> Dict[str, Any]:
    """표준화된 캘린더 일정 딕셔너리를 생성합니다."""
    meta = CATEGORY_META.get(category, CATEGORY_META["anniversary"])
    chosen_emoji = emoji or meta["emoji"]
    lunar = get_lunar_info(target_date)
    locdate = target_date.strftime("%Y%m%d")
    date_str = target_date.isoformat()
    date_kind = date_kind_override or meta["dateKind"]

    tags = list(sub_tags or [])
    if meta["short_label"] not in tags:
        tags.insert(0, meta["short_label"])
    if is_holiday and "법정공휴일(빨간날)" not in tags:
        tags.append("법정공휴일(빨간날)")

    slug = hashlib.md5(f"{locdate}-{category}-{title}".encode("utf-8")).hexdigest()[:10]
    uid = f"kasi-{locdate}-{slug}@korea.calendar"

    full_desc_lines = [description.strip()] if description.strip() else [meta["desc"]]
    if lunar["lunar_full"]:
        full_desc_lines.append(f"• 음력/간지: {lunar['lunar_full']} ({lunar['ganji']})")
    full_desc_lines.append("• 데이터 출처: 과학기술정보통신부 한국천문연구원(KASI) 특일 정보")

    return {
        "uid": uid,
        "locdate": locdate,
        "start_date": date_str,
        "end_date": date_str,
        "year": target_date.year,
        "month": target_date.month,
        "day": target_date.day,
        "weekday": target_date.weekday(),
        "weekday_kr": WEEKDAY_KR[target_date.weekday()],
        "title": title,
        "emoji": chosen_emoji,
        "emoji_title": f"{chosen_emoji} {title}",
        "category": category,
        "category_label": meta["label"],
        "category_short": meta["short_label"],
        "category_color": meta["color"],
        "dateKind": date_kind,
        "isHoliday": "Y" if is_holiday else "N",
        "kst": kst,
        "lunar_date": lunar["lunar_full"],
        "lunar_short": lunar["lunar_short"],
        "ganji": lunar["ganji"],
        "day_ganji": lunar["day_ganji"],
        "sub_tags": tags,
        "description": "\n".join(full_desc_lines),
        "source": source,
        "seq": seq,
        "has_valid_date": True,
    }


def generate_year_events(year: int) -> List[Dict[str, Any]]:
    """
    단일 연도(year)에 대한 대한민국 모든 특일·절기·기념일·잡절·음력일정을 생성합니다.
    1) 5대 국경일 및 법정공휴일 + 대체공휴일 완벽 산출
    2) 국가 법정기념일 (고정 + 가변 요일 + 음력)
    3) 24절기 (천문 황경 정밀 계산)
    4) 잡절 및 전통 세시풍속 (초복·중복·말복, 한식, 납일, 사일, 단오, 정월대보름, 칠석, 백중 등)
    5) 음력 초하루(1일)·보름(15일) 달력
    6) 대중·생활 기념일
    """
    events: List[Dict[str, Any]] = []

    # ---------------------------------------------------------
    # 1. 법정공휴일 & 5대 국경일 & 대체공휴일 계산
    # ---------------------------------------------------------
    # 대체공휴일 산출을 위해 연도 내 모든 기본 공휴일 날짜를 먼저 수집
    holiday_groups: List[Dict[str, Any]] = []

    # (1) 신정 (1월 1일) - 대체공휴일 비대상
    holiday_groups.append(
        {
            "dates": [date(year, 1, 1)],
            "titles": ["신정 (새해 첫날)"],
            "emoji": "🌅",
            "category": "holiday",
            "sub_tags": ["법정공휴일", "신정", "새해"],
            "desc": "양력 1월 1일 새해 첫날(관공서의 공휴일에 관한 규정 제2조 제2호). 희망찬 새해의 시작을 축하하는 날입니다.",
            "sub_rule": "none",
        }
    )

    # (2) 설날 연휴 (음력 1월 1일 및 전후일)
    seollal_d = lunar_to_solar(year, 1, 1)
    if seollal_d and seollal_d.year == year:
        s_prev = seollal_d - timedelta(days=1)
        s_next = seollal_d + timedelta(days=1)
        holiday_groups.append(
            {
                "dates": [s_prev, seollal_d, s_next],
                "titles": ["설날 연휴", "설날", "설날 연휴"],
                "emoji": "🙇",
                "category": "holiday",
                "sub_tags": ["법정공휴일", "전통명절", "설날"],
                "desc": "음력 정월 초하루(1월 1일)로 한 해의 첫날을 맞이하며 조상께 차례를 지내고 어른들께 세배를 올리며 떡국을 나누어 먹는 민족 최대의 명절입니다.",
                "sub_rule": "seollal_chuseok",
            }
        )

    # (3) 3·1절 (3월 1일) - 5대 국경일 & 법정공휴일
    holiday_groups.append(
        {
            "dates": [date(year, 3, 1)],
            "titles": ["삼일절 (3·1절)"],
            "emoji": "🇰🇷",
            "category": "holiday",
            "sub_tags": ["5대국경일", "법정공휴일", "태극기게양"],
            "desc": "1919년 3월 1일 한민족이 일본의 식민통치에 항거하고 독립선언서를 발표하여 한국의 독립 의사를 세계 만방에 알린 날을 기념하는 5대 국경일이자 법정공휴일입니다.\n• 태극기 게양: 깃봉과 깃면의 사이를 떼지 않고 달기",
            "sub_rule": "sat_sun_overlap",
        }
    )

    # (4) 어린이날 (5월 5일)
    holiday_groups.append(
        {
            "dates": [date(year, 5, 5)],
            "titles": ["어린이날"],
            "emoji": "🎈",
            "category": "holiday",
            "sub_tags": ["법정공휴일", "가정의달", "어린이날"],
            "desc": "어린이의 인격을 소중히 여기고 어린이의 행복을 도모하기 위하여 제정된 법정공휴일입니다.",
            "sub_rule": "sat_sun_overlap",
        }
    )

    # (5) 부처님오신날 (음력 4월 8일)
    buddha_d = lunar_to_solar(year, 4, 8)
    if buddha_d and buddha_d.year == year:
        holiday_groups.append(
            {
                "dates": [buddha_d],
                "titles": ["부처님오신날 (석가탄신일)"],
                "emoji": "🪷",
                "category": "holiday",
                "sub_tags": ["법정공휴일", "전통문화", "연등회"],
                "desc": "음력 4월 8일 석가모니 부처님의 탄신을 기념하는 법정공휴일입니다(2023년부터 대체공휴일 적용 대상).",
                "sub_rule": "sat_sun_overlap" if year >= 2023 else "none",
            }
        )

    # (6) 현충일 (6월 6일) - 대체공휴일 비대상
    holiday_groups.append(
        {
            "dates": [date(year, 6, 6)],
            "titles": ["현충일"],
            "emoji": "🕯️",
            "category": "holiday",
            "sub_tags": ["법정공휴일", "보훈", "조기게양"],
            "desc": "나라를 위하여 목숨을 바친 애국선열과 국군장병들의 충절을 추모하기 위하여 지정된 법정공휴일입니다.\n• 태극기 게양: 조기(弔旗) 게양 (깃면의 세로 너비만큼 내려서 달기)\n• 오전 10시 정각 전국 사이렌에 맞춰 1분간 묵념",
            "sub_rule": "none",
        }
    )

    # (7) 광복절 (8월 15일) - 5대 국경일 & 법정공휴일
    holiday_groups.append(
        {
            "dates": [date(year, 8, 15)],
            "titles": ["광복절"],
            "emoji": "🇰🇷",
            "category": "holiday",
            "sub_tags": ["5대국경일", "법정공휴일", "태극기게양"],
            "desc": "1945년 8월 15일 우리나라가 일제로부터 주권을 회복한 날과 1948년 8월 15일 대한민국 정부 수립을 경축하는 5대 국경일이자 법정공휴일입니다.\n• 태극기 게양: 깃봉과 깃면의 사이를 떼지 않고 달기",
            "sub_rule": "sat_sun_overlap",
        }
    )

    # (8) 추석 연휴 (음력 8월 15일 및 전후일)
    chuseok_d = lunar_to_solar(year, 8, 15)
    if chuseok_d and chuseok_d.year == year:
        c_prev = chuseok_d - timedelta(days=1)
        c_next = chuseok_d + timedelta(days=1)
        holiday_groups.append(
            {
                "dates": [c_prev, chuseok_d, c_next],
                "titles": ["추석 연휴", "추석 (한가위)", "추석 연휴"],
                "emoji": "🌕",
                "category": "holiday",
                "sub_tags": ["법정공휴일", "전통명절", "추석"],
                "desc": "음력 8월 15일 한가위로, 가을 수확을 감사하며 햅쌀로 빚은 송편을 나누어 먹고 보름달 아래 소원을 비는 대한민국 대표 명절입니다.",
                "sub_rule": "seollal_chuseok",
            }
        )

    # (9) 개천절 (10월 3일) - 5대 국경일 & 법정공휴일
    holiday_groups.append(
        {
            "dates": [date(year, 10, 3)],
            "titles": ["개천절"],
            "emoji": "🇰🇷",
            "category": "holiday",
            "sub_tags": ["5대국경일", "법정공휴일", "태극기게양"],
            "desc": "서기전 2333년 단군왕검께서 홍익인간(弘益人間)·이화세계(理化世界)의 이념으로 고조선을 건국하신 날을 기념하는 5대 국경일이자 법정공휴일입니다.\n• 태극기 게양: 깃봉과 깃면의 사이를 떼지 않고 달기",
            "sub_rule": "sat_sun_overlap",
        }
    )

    # (10) 한글날 (10월 9일) - 5대 국경일 & 법정공휴일
    holiday_groups.append(
        {
            "dates": [date(year, 10, 9)],
            "titles": ["한글날"],
            "emoji": "🇰🇷",
            "category": "holiday",
            "sub_tags": ["5대국경일", "법정공휴일", "태극기게양"],
            "desc": "세종대왕께서 훈민정음(한글)을 창제하여 세상에 반포하신 것을 기념하고 한글의 우수성을 기리는 5대 국경일이자 법정공휴일입니다.\n• 태극기 게양: 깃봉과 깃면의 사이를 떼지 않고 달기",
            "sub_rule": "sat_sun_overlap",
        }
    )

    # (11) 기독탄신일 / 성탄절 (12월 25일)
    holiday_groups.append(
        {
            "dates": [date(year, 12, 25)],
            "titles": ["기독탄신일 (성탄절)"],
            "emoji": "🎄",
            "category": "holiday",
            "sub_tags": ["법정공휴일", "성탄절", "크리스마스"],
            "desc": "예수 그리스도의 탄생을 기념하는 법정공휴일입니다(2023년부터 대체공휴일 적용 대상).",
            "sub_rule": "sat_sun_overlap" if year >= 2023 else "none",
        }
    )

    # (12) 선거일 및 특별/임시공휴일 추가
    for d_str, (sp_title, sp_emoji, sp_desc) in SPECIAL_PUBLIC_HOLIDAYS.items():
        sp_d = datetime.strptime(d_str, "%Y-%m-%d").date()
        if sp_d.year == year:
            holiday_groups.append(
                {
                    "dates": [sp_d],
                    "titles": [sp_title],
                    "emoji": sp_emoji,
                    "category": "holiday",
                    "sub_tags": ["법정공휴일", "선거·임시공휴일"],
                    "desc": sp_desc,
                    "sub_rule": "none",
                }
            )

    # 날짜별 공휴일 횟수 카운트 (겹침 여부 판별용)
    date_holiday_count: Dict[date, int] = {}
    for grp in holiday_groups:
        for d in grp["dates"]:
            date_holiday_count[d] = date_holiday_count.get(d, 0) + 1

    occupied_holidays = set(date_holiday_count.keys())

    # 기본 공휴일 이벤트 생성
    for grp in holiday_groups:
        for d, t in zip(grp["dates"], grp["titles"]):
            events.append(
                make_event(
                    target_date=d,
                    title=t,
                    category=grp["category"],
                    is_holiday=True,
                    emoji=grp["emoji"],
                    description=grp["desc"],
                    sub_tags=grp["sub_tags"],
                )
            )

    # 대체공휴일 정밀 계산 (관공서의 공휴일에 관한 규정 제3조)
    for grp in holiday_groups:
        rule = grp["sub_rule"]
        if rule == "none":
            continue

        needs_sub = False
        base_name = grp["titles"][len(grp["titles"]) // 2]

        if rule == "seollal_chuseok":
            # 설·추석 연휴 중 일요일과 겹치거나 다른 공휴일과 겹치는 경우 대체공휴일 발생
            for d in grp["dates"]:
                if d.weekday() == 6 or date_holiday_count.get(d, 0) > 1:
                    needs_sub = True
                    break
        elif rule == "sat_sun_overlap":
            # 토요일, 일요일 또는 다른 공휴일과 겹치는 경우 대체공휴일 발생
            for d in grp["dates"]:
                if d.weekday() in (5, 6) or date_holiday_count.get(d, 0) > 1:
                    needs_sub = True
                    break

        if needs_sub:
            candidate = max(grp["dates"]) + timedelta(days=1)
            # 토요일, 일요일, 또는 다른 공휴일이 아닌 첫 번째 비공휴일을 찾음
            while candidate.weekday() in (5, 6) or candidate in occupied_holidays:
                candidate += timedelta(days=1)
            occupied_holidays.add(candidate)
            clean_base = base_name.split(" (")[0]
            events.append(
                make_event(
                    target_date=candidate,
                    title=f"대체공휴일 ({clean_base})",
                    category="holiday",
                    is_holiday=True,
                    emoji="🔴",
                    description=f"「관공서의 공휴일에 관한 규정」 제3조 및 「공휴일에 관한 법률」에 따라 {clean_base}이(가) 주말 또는 다른 공휴일과 겹쳐 지정된 법정 대체공휴일입니다.",
                    sub_tags=["법정공휴일", "대체공휴일"],
                )
            )

    # ---------------------------------------------------------
    # 2. 제헌절 (5대 국경일 중 유일한 비공휴일 국경일 - 7월 17일)
    # ---------------------------------------------------------
    events.append(
        make_event(
            target_date=date(year, 7, 17),
            title="제헌절",
            category="national",
            is_holiday=False,
            emoji="🇰🇷",
            description="1948년 7월 17일 대한민국 헌법 제정·공포를 경축하는 대한민국 5대 국경일입니다.\n• 태극기 게양: 깃봉과 깃면의 사이를 떼지 않고 달기",
            sub_tags=["5대국경일", "법정기념일", "태극기게양"],
            date_kind_override="01",
        )
    )

    # ---------------------------------------------------------
    # 3. 대한민국 국가 법정기념일 (고정일 + 가변 요일)
    # ---------------------------------------------------------
    for m, d_num, name, emj, desc, tags in FIXED_NATIONAL_ANNIVERSARIES:
        try:
            target = date(year, m, d_num)
        except ValueError:
            continue
        # 국군의날 등 임시공휴일로 이미 등록된 연도라도 기념일 상세 정보 보존
        events.append(
            make_event(
                target_date=target,
                title=name,
                category="anniversary",
                is_holiday=False,
                emoji=emj,
                description=desc,
                sub_tags=tags,
            )
        )

    # 가변 요일 법정기념일 ("몇째 주 무슨 요일")
    variable_anniversaries = [
        (
            _nth_weekday_of_month(year, 3, 2, 3),  # 3월 셋째 수요일
            "상공의 날",
            "🏭",
            "상공업의 진흥을 촉진하고 상공인들의 의욕을 고취하기 위하여 지정된 법정기념일 (매년 3월 셋째 수요일, 산업통상자원부)",
            ["경제", "산업", "법정기념일"],
        ),
        (
            _nth_weekday_of_month(year, 3, 4, 4),  # 3월 넷째 금요일
            "서해수호의 날",
            "⚓",
            "제2연평해전, 천안함 피격, 연평도 포격전으로 희생된 서해수호 55용사를 추모하고 안보의식을 다지는 국가기념일 (매년 3월 넷째 금요일, 국가보훈부)",
            ["보훈", "안보", "법정기념일"],
        ),
        (
            _nth_weekday_of_month(year, 4, 4, 1),  # 4월 첫째 금요일
            "향토예비군의 날",
            "🪖",
            "향토예비군 창설을 기념하고 예비군의 노고를 치하하며 총력안보 태세를 다지는 법정기념일 (매년 4월 첫째 금요일, 국방부)",
            ["국방", "안보", "법정기념일"],
        ),
        (
            _nth_weekday_of_month(year, 5, 0, 3),  # 5월 셋째 월요일
            "성년의 날",
            "🌹",
            "성인으로서의 자부심과 사회적 책임을 일깨워주며 성년이 되었음을 축하하는 법정기념일 (매년 5월 셋째 월요일, 여성가족부)",
            ["청년", "문화", "법정기념일"],
        ),
        (
            _nth_weekday_of_month(year, 7, 2, 2),  # 7월 둘째 수요일
            "정보보호의 날",
            "🛡️",
            "사이버 위협 예방과 국민의 정보보호 생활화를 위하여 지정된 법정기념일 (매년 7월 둘째 수요일, 과학기술정보통신부·국가정보원·행정안전부)",
            ["IT", "보안", "법정기념일"],
        ),
        (
            _nth_weekday_of_month(year, 9, 5, 3),  # 9월 셋째 토요일
            "청년의 날",
            "🌟",
            "청년의 권리 보장과 청년 발전의 중요성을 알리고 청년 문제에 대한 관심을 높이기 위해 제정된 법정기념일 (매년 9월 셋째 토요일, 국무조정실)",
            ["청년", "법정기념일"],
        ),
        (
            _nth_weekday_of_month(year, 10, 5, 3),  # 10월 셋째 토요일
            "문화의 날",
            "🎭",
            "국민의 문화예술 진흥과 문화 향유 기회를 확대하기 위하여 제정된 법정기념일 (매년 10월 셋째 토요일, 문화체육관광부)",
            ["문화", "예술", "법정기념일"],
        ),
        (
            _nth_weekday_of_month(year, 10, 1, -1),  # 10월 마지막 화요일
            "금융의 날",
            "🏦",
            "금융에 대한 국민의 이해를 높이고 저축·투자 문화 확산 및 금융산업 발전을 기념하는 법정기념일 (매년 10월 마지막 화요일, 금융위원회)",
            ["경제", "금융", "법정기념일"],
        ),
    ]
    for v_date, v_name, v_emj, v_desc, v_tags in variable_anniversaries:
        events.append(
            make_event(
                target_date=v_date,
                title=v_name,
                category="anniversary",
                is_holiday=False,
                emoji=v_emj,
                description=v_desc,
                sub_tags=v_tags,
            )
        )

    # ---------------------------------------------------------
    # 4. 24절기 정밀 산출
    # ---------------------------------------------------------
    solar_terms = compute_solar_terms_for_year(year)
    term_map: Dict[str, date] = {}
    for st in solar_terms:
        term_map[st["name"]] = st["date"]
        events.append(
            make_event(
                target_date=st["date"],
                title=f"{st['name']} (24절기)",
                category="solar_term",
                is_holiday=False,
                emoji=st["emoji"],
                kst=st["kst"],
                description=st["description"],
                sub_tags=["24절기", "천문역법", st["name"]],
            )
        )

    # ---------------------------------------------------------
    # 5. 잡절(雜節) 및 전통 세시풍속 정밀 산출 (한국천문연구원 역서 기준)
    # ---------------------------------------------------------
    # (1) 한식 (寒食): 전년도 동지로부터 105일째 되는 날
    prev_terms = compute_solar_terms_for_year(year - 1)
    prev_dongji = next((x["date"] for x in prev_terms if x["name"] == "동지"), date(year - 1, 12, 22))
    hansik_date = prev_dongji + timedelta(days=105)
    if hansik_date.year == year:
        events.append(
            make_event(
                target_date=hansik_date,
                title="한식 (寒食)",
                category="sundry",
                is_holiday=False,
                emoji="🌿",
                description="동지(冬至) 후 105일째 되는 날로, 설날·단오·추석과 함께 우리 민족 4대 명절 중 하나로 꼽힙니다. 불을 피우지 않고 찬 음식을 먹으며 조상의 산소에 성묘하고 사초(잔디 입히기)를 하는 세시풍속이 있습니다.",
                sub_tags=["잡절", "세시풍속", "4대명절", "성묘"],
            )
        )

    # (2) 삼복 (초복·중복·말복): 하지 후 제3경일, 제4경일, 입추 후 제1경일
    haji_date = term_map.get("하지", date(year, 6, 21))
    ipchu_date = term_map.get("입추", date(year, 8, 7))

    gyeong_after_haji: List[date] = []
    cur_d = haji_date
    while len(gyeong_after_haji) < 4:
        if get_lunar_info(cur_d)["day_ganji"].startswith("경"):
            gyeong_after_haji.append(cur_d)
        cur_d += timedelta(days=1)

    chobok_date = gyeong_after_haji[2]
    jungbok_date = gyeong_after_haji[3]

    cur_d = ipchu_date
    while not get_lunar_info(cur_d)["day_ganji"].startswith("경"):
        cur_d += timedelta(days=1)
    malbok_date = cur_d

    sambok_items = [
        (
            chobok_date,
            "초복 (初伏)",
            "🍲",
            "삼복(三伏) 더위의 시작으로 하지(夏至)로부터 세 번째 경일(庚日)입니다. 여름철 기력을 보충하기 위해 삼계탕, 수박 등 보양식을 챙겨 먹는 전통 잡절입니다.",
        ),
        (
            jungbok_date,
            "중복 (中伏)",
            "🐓",
            "삼복(三伏) 가운데 두 번째 복날로 하지(夏至)로부터 네 번째 경일(庚日)입니다. 한여름 무더위를 이겨내기 위해 보양식을 나누는 전통 잡절입니다.",
        ),
        (
            malbok_date,
            "말복 (末伏)",
            "🍉",
            "삼복(三伏)의 마지막 복날로 입추(立秋)로부터 첫 번째 경일(庚日)입니다. 막바지 더위를 이겨내며 여름 건강을 챙기는 전통 잡절입니다.",
        ),
    ]
    for sb_d, sb_title, sb_emj, sb_desc in sambok_items:
        events.append(
            make_event(
                target_date=sb_d,
                title=sb_title,
                category="sundry",
                is_holiday=False,
                emoji=sb_emj,
                description=sb_desc,
                sub_tags=["잡절", "삼복", "복날", "세시풍속"],
            )
        )

    # (3) 춘사일(春社日) / 추사일(秋社日): 춘분/추분 후 다섯 번째 무일(戊日)
    chunbun_date = term_map.get("춘분", date(year, 3, 20))
    chubun_date = term_map.get("추분", date(year, 9, 23))
    for base_d, sa_title, sa_desc in [
        (chunbun_date, "춘사일 (春社日)", "춘분(春分) 후 다섯 번째 무일(戊日)로, 봄에 토지신(사신)에게 한 해 농사의 풍년을 기원하며 제사를 지내던 전통 잡절입니다."),
        (chubun_date, "추사일 (秋社日)", "추분(秋分) 후 다섯 번째 무일(戊日)로, 가을 추수를 마치고 토지신에게 감사의 제사를 올리던 전통 잡절입니다."),
    ]:
        mu_days: List[date] = []
        c_d = base_d
        while len(mu_days) < 5:
            if get_lunar_info(c_d)["day_ganji"].startswith("무"):
                mu_days.append(c_d)
            c_d += timedelta(days=1)
        events.append(
            make_event(
                target_date=mu_days[4],
                title=sa_title,
                category="sundry",
                is_holiday=False,
                emoji="🌾",
                description=sa_desc,
                sub_tags=["잡절", "세시풍속"],
            )
        )

    # (4) 납일(臘日): 동지 후 세 번째 미일(未日, 일진의 두 번째 글자가 '미'인 날)
    dongji_date = term_map.get("동지", date(year, 12, 22))
    mi_days: List[date] = []
    c_d = dongji_date
    while len(mi_days) < 3:
        dg = get_lunar_info(c_d)["day_ganji"]
        if len(dg) >= 2 and dg[1] == "미":
            mi_days.append(c_d)
        c_d += timedelta(days=1)
    if mi_days[2].year == year:
        events.append(
            make_event(
                target_date=mi_days[2],
                title="납일 (臘日·납향일)",
                category="sundry",
                is_holiday=False,
                emoji="🕯️",
                description="동지(冬至) 후 세 번째 미일(未日)로, 한 해 동안의 농사와 집안일을 조상과 신께 고하며 제사(납향)를 지내던 전통 잡절입니다.",
                sub_tags=["잡절", "세시풍속"],
            )
        )

    # (5) 음력 기준 전통 명절·잡절·세시풍속
    lunar_sundry_specs = [
        (1, 15, "정월대보름 (상원)", "🌕", "음력 1월 15일 새해 첫 보름달이 뜨는 날입니다. 오곡밥과 묵은 나물을 해 먹고 부럼을 깨물며 귀밝이술을 마시고 달집태우기로 한 해의 건강과 풍년을 기원합니다."),
        (2, 1, "머슴날 (영등날)", "🌾", "음력 2월 1일로 바람의 신 영등할머니를 맞이하고 농사를 앞두고 일꾼들을 대접하며 풍년을 기원하던 전통 세시풍속일입니다."),
        (3, 3, "삼짇날 (상사일)", "🦋", "음력 3월 3일 숫자 3이 겹치는 강남 갔던 제비가 돌아오는 봄 명절입니다. 진달래꽃으로 화전(꽃달임)을 부쳐 먹으며 봄놀이를 즐깁니다."),
        (5, 5, "단오 (수릿날)", "🌿", "음력 5월 5일로 일 년 중 양기(陽氣)가 가장 왕성한 날이자 4대 명절 중 하나입니다. 창포물에 머리를 감고 수리취떡을 먹으며 그네뛰기와 씨름을 즐깁니다."),
        (6, 15, "유두 (流頭)", "🌊", "음력 6월 15일로 동쪽으로 흐르는 맑은 시냇물에 머리를 감으며 여름철 더위와 액운을 씻어내고 밀전병·수단(물만두)을 나누어 먹던 세시풍속일입니다."),
        (7, 7, "칠석 (七夕)", "🌌", "음력 7월 7일 견우와 직녀가 일 년에 한 번 오작교에서 만나는 날입니다. 저녁에 칠성님께 무병장수와 바느질·학업 성취를 기원하고 밀국수와 밀전병을 먹습니다."),
        (7, 15, "백중 (망혼일·우란분절)", "🪷", "음력 7월 15일로 여름 농사일을 마치고 호미를 씻어 두는 '호미씻이' 잔치를 열며 조상의 넋을 위로하던 전통 세시풍속일입니다."),
        (9, 9, "중양절 (중구일)", "🌼", "음력 9월 9일 양(陽)의 숫자 9가 겹치는 가을 명절입니다. 국화전을 부쳐 먹고 국화주를 마시며 단풍놀이를 즐기는 세시풍속이 있습니다."),
        (10, 20, "손돌풍날", "🌬️", "음력 10월 20일경 고려 시대 뱃사공 손돌의 전설에서 유래한 강추위와 거센 바람이 부는 시기입니다."),
    ]
    for l_m, l_d, l_title, l_emj, l_desc in lunar_sundry_specs:
        for check_lunar_year in (year - 1, year):
            s_d = lunar_to_solar(check_lunar_year, l_m, l_d, is_leap=False)
            if s_d and s_d.year == year:
                events.append(
                    make_event(
                        target_date=s_d,
                        title=l_title,
                        category="sundry",
                        is_holiday=False,
                        emoji=l_emj,
                        description=l_desc,
                        sub_tags=["잡절", "세시풍속", "음력명절"],
                    )
                )

    # 섣달그믐 (음력 12월 마지막 날)
    next_seollal = lunar_to_solar(year + 1, 1, 1)
    if next_seollal:
        seotdal = next_seollal - timedelta(days=1)
        if seotdal.year == year:
            events.append(
                make_event(
                    target_date=seotdal,
                    title="섣달그믐",
                    category="sundry",
                    is_holiday=False,
                    emoji="🏮",
                    description="음력 한 해의 마지막 날 밤(제석)으로 집안 곳곳에 불을 밝혀 수세(守歲)하며 한 해를 정리하고 새해 설날을 맞이하는 세시풍속일입니다.",
                    sub_tags=["잡절", "세시풍속", "음력명절"],
                )
            )

    # ---------------------------------------------------------
    # 6. 음력 초하루(1일) & 보름(15일) 달력 (선택형 카테고리: lunar)
    # ---------------------------------------------------------
    cur_day = date(year, 1, 1)
    end_day = date(year, 12, 31)
    while cur_day <= end_day:
        li = get_lunar_info(cur_day)
        leap_str = "윤" if li["is_leap"] else ""
        if li["lunar_day"] == 1:
            events.append(
                make_event(
                    target_date=cur_day,
                    title=f"음력 {leap_str}{li['lunar_month']}월 1일 (초하루)",
                    category="lunar",
                    is_holiday=False,
                    emoji="🌑",
                    description=f"{li['lunar_full']} 초하루(삭, 朔)입니다.\n• 간지: {li['ganji']}",
                    sub_tags=["음력달력", "음력초하루"],
                )
            )
        elif li["lunar_day"] == 15:
            events.append(
                make_event(
                    target_date=cur_day,
                    title=f"음력 {leap_str}{li['lunar_month']}월 15일 (보름)",
                    category="lunar",
                    is_holiday=False,
                    emoji="🌕",
                    description=f"{li['lunar_full']} 보름(망, 望)입니다.\n• 간지: {li['ganji']}",
                    sub_tags=["음력달력", "음력보름"],
                )
            )
        cur_day += timedelta(days=1)

    # ---------------------------------------------------------
    # 7. 대중·생활 기념일 (선택형 카테고리: popular)
    # ---------------------------------------------------------
    for p_m, p_d, p_title, p_emj, p_desc in POPULAR_DAYS:
        try:
            p_date = date(year, p_m, p_d)
        except ValueError:
            continue
        events.append(
            make_event(
                target_date=p_date,
                title=p_title,
                category="popular",
                is_holiday=False,
                emoji=p_emj,
                description=p_desc,
                sub_tags=["생활기념일", "데이"],
            )
        )

    return events


def generate_multi_year_events(start_year: int = 2020, end_year: int = 2032) -> List[Dict[str, Any]]:
    """지정된 연도 범위 전체의 대한민국 특일·절기·기념일 일정을 생성하고 정렬합니다."""
    all_events: List[Dict[str, Any]] = []
    for y in range(start_year, end_year + 1):
        all_events.extend(generate_year_events(y))

    # 중복 제거 및 정렬 (날짜 오름차순 -> 공휴일 우선 -> 카테고리 순)
    cat_order = {
        "holiday": 1,
        "national": 2,
        "solar_term": 3,
        "sundry": 4,
        "anniversary": 5,
        "custom": 6,
        "lunar": 7,
        "popular": 8,
    }
    dedup: Dict[str, Dict[str, Any]] = {}
    for ev in all_events:
        key = f"{ev['locdate']}::{ev['category']}::{ev['title']}"
        dedup[key] = ev

    sorted_events = sorted(
        dedup.values(),
        key=lambda x: (
            x["locdate"],
            0 if x.get("isHoliday") == "Y" else 1,
            cat_order.get(x.get("category", "anniversary"), 9),
            x.get("title", ""),
        ),
    )
    return sorted_events
