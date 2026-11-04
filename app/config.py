import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("KOREA_CAL_DATA_DIR", str(BASE_DIR / "data")))
OUTPUT_DIR = Path(os.environ.get("KOREA_CAL_OUTPUT_DIR", str(BASE_DIR / "output")))
SHARED_DIR = OUTPUT_DIR / "shared"
LOG_DIR = Path(os.environ.get("KOREA_CAL_LOG_DIR", str(BASE_DIR / "logs")))
SEED_DIR = BASE_DIR / "seed"

for _d in (DATA_DIR, OUTPUT_DIR, SHARED_DIR, LOG_DIR, SEED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("KOREA_CAL_HOST", "0.0.0.0")
PORT = int(os.environ.get("KOREA_CAL_PORT", "8500"))
AUTO_SYNC_INTERVAL_MINUTES = int(os.environ.get("KOREA_CAL_AUTO_SYNC_MINUTES", "720"))
DEFAULT_START_YEAR = int(os.environ.get("KOREA_CAL_START_YEAR", "2020"))
DEFAULT_END_YEAR = int(os.environ.get("KOREA_CAL_END_YEAR", "2032"))
MAX_ICS_BACKUPS = int(os.environ.get("KOREA_CAL_MAX_ICS_BACKUPS", "5"))

API_CONFIG_FILE = DATA_DIR / "api_config.json"

# 공공데이터포털 한국천문연구원_특일 정보 기본 승인 메타데이터
DEFAULT_KASI_META = {
    "category": "과학기술",
    "provider": "한국천문연구원 (KASI)",
    "service_name": "[승인] 한국천문연구원_특일 정보",
    "endpoint_base": "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService",
    "account_type": "개발계정 (연장신청 승인)",
    "applied_date": "2026-05-14",
    "expire_date": "2028-05-14",
    "operations": [
        {"op": "getHoliDeInfo", "name": "국경일 정보조회", "dateKind": "01"},
        {"op": "getRestDeInfo", "name": "공휴일 정보조회", "dateKind": "01"},
        {"op": "getAnniversaryInfo", "name": "기념일 정보조회", "dateKind": "02"},
        {"op": "get24DivisionsInfo", "name": "24절기 정보조회", "dateKind": "03"},
        {"op": "getSundryDayInfo", "name": "잡절 정보조회", "dateKind": "04"},
    ],
}


def load_api_config() -> Dict[str, Any]:
    """환경변수 또는 data/api_config.json에서 공공데이터포털 인증키 및 설정을 불러옵니다."""
    env_key = (
        os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
        or os.environ.get("KASI_SERVICE_KEY", "").strip()
        or os.environ.get("SERVICE_KEY", "").strip()
    )
    saved: Dict[str, Any] = {}
    if API_CONFIG_FILE.exists():
        try:
            saved = json.loads(API_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            saved = {}

    service_key = saved.get("service_key", "").strip() or env_key
    applied_date = (
        saved.get("applied_date")
        or os.environ.get("KASI_APPLIED_DATE", "").strip()
        or DEFAULT_KASI_META["applied_date"]
    )
    expire_date = (
        saved.get("expire_date")
        or os.environ.get("KASI_EXPIRE_DATE", "").strip()
        or DEFAULT_KASI_META["expire_date"]
    )

    # 만료예정일까지 남은 일수 계산
    days_remaining = None
    try:
        exp_dt = datetime.strptime(expire_date, "%Y-%m-%d").date()
        days_remaining = (exp_dt - date.today()).days
    except Exception:
        pass

    masked_key = ""
    if service_key:
        if len(service_key) > 12:
            masked_key = f"{service_key[:6]}...{service_key[-6:]}"
        else:
            masked_key = "설정됨"

    return {
        **DEFAULT_KASI_META,
        "service_key": service_key,
        "has_key": bool(service_key),
        "masked_key": masked_key,
        "applied_date": applied_date,
        "expire_date": expire_date,
        "days_remaining": days_remaining,
        "last_api_test": saved.get("last_api_test"),
        "last_api_status": saved.get("last_api_status", "내장 KASI 정밀 역법 엔진 활성 (API 키 입력 시 실시간 OpenAPI 병합)"),
    }


def save_api_config(
    service_key: str,
    applied_date: str = "2026-05-14",
    expire_date: str = "2028-05-14",
    last_api_status: str = "",
) -> Dict[str, Any]:
    """웹 대시보드 또는 CLI에서 입력한 공공데이터포털 ServiceKey를 영구 저장합니다."""
    current = load_api_config()
    payload = {
        "service_key": service_key.strip(),
        "applied_date": applied_date.strip() or DEFAULT_KASI_META["applied_date"],
        "expire_date": expire_date.strip() or DEFAULT_KASI_META["expire_date"],
        "last_api_test": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_api_status": last_api_status or current.get("last_api_status", ""),
    }
    API_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_CONFIG_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return load_api_config()
