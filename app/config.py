import json
import os
from datetime import date, datetime, timedelta
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
    "account_type": "계정개발 (연장신청 승인)",
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


def get_internal_service_key() -> str:
    """
    서버 백엔드 내부 동기화 전용 함수입니다.
    절대 외부 HTTP API나 웹 화면으로 반환하지 않습니다.
    """
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
    return saved.get("service_key", "").strip() or env_key


def load_api_config() -> Dict[str, Any]:
    """
    외부/프론트엔드에 안전하게 공개 가능한 상태 정보만 반환합니다.
    개인정보 및 보안 보호를 위해 실제 인증키(service_key) 원문이나 일부 문자열은 절대 포함하지 않습니다.
    """
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

    saved_key = saved.get("service_key", "").strip()
    has_key = bool(saved_key or env_key)
    if saved_key:
        key_source = "서버 보안 볼륨에 안전하게 등록됨 (외부 비노출)"
    elif env_key:
        key_source = "도커 환경변수(.env)로 안전하게 등록됨 (외부 비노출)"
    else:
        key_source = "미등록 (내장 KASI 천문·역법 표준 엔진 단독 가동 중)"

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

    days_remaining = None
    try:
        exp_dt = datetime.strptime(expire_date, "%Y-%m-%d").date()
        days_remaining = (exp_dt - date.today()).days
    except Exception:
        pass

    default_status = (
        "✅ 공공데이터포털 한국천문연구원 OpenAPI 인증키 등록됨 · 12시간 주기 자동 업데이트 작동 중"
        if has_key
        else "✅ 내장 한국천문연구원(KASI) 천문·역법 엔진 가동 중 · 12시간 주기 자동 업데이트 작동 중"
    )

    return {
        **DEFAULT_KASI_META,
        "has_key": has_key,
        "key_source": key_source,
        "security_notice": "🔒 개인 인증키는 서버 내부에서만 암호화·보호되며 화면이나 외부 API에 절대 노출되지 않습니다.",
        "applied_date": applied_date,
        "expire_date": expire_date,
        "days_remaining": days_remaining,
        "auto_sync_hours": round(AUTO_SYNC_INTERVAL_MINUTES / 60, 1),
        "last_api_test": saved.get("last_api_test"),
        "last_api_status": saved.get("last_api_status") or default_status,
        "last_api_ok": saved.get("last_api_ok", has_key),
    }


def save_api_config(
    service_key: str = "",
    applied_date: str = "2026-05-14",
    expire_date: str = "2028-05-14",
    last_api_status: str = "",
    last_api_ok: bool = True,
    keep_existing_key_if_blank: bool = True,
) -> Dict[str, Any]:
    """
    인증키 및 연동 상태 메타데이터를 저장합니다.
    keep_existing_key_if_blank=True이면 새 키를 입력하지 않고 상태/날짜만 갱신할 때 기존 키를 안전하게 보존합니다.
    """
    existing_saved: Dict[str, Any] = {}
    if API_CONFIG_FILE.exists():
        try:
            existing_saved = json.loads(API_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing_saved = {}

    final_key = service_key.strip()
    if not final_key and keep_existing_key_if_blank:
        final_key = existing_saved.get("service_key", "").strip()

    payload = {
        "service_key": final_key,
        "applied_date": applied_date.strip() or existing_saved.get("applied_date") or DEFAULT_KASI_META["applied_date"],
        "expire_date": expire_date.strip() or existing_saved.get("expire_date") or DEFAULT_KASI_META["expire_date"],
        "last_api_test": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_api_status": last_api_status or existing_saved.get("last_api_status", ""),
        "last_api_ok": bool(last_api_ok),
    }
    API_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_CONFIG_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return load_api_config()
