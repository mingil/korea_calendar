import logging
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
import requests

from app.config import DEFAULT_KASI_META
from app.kasi_engine import make_event

logger = logging.getLogger(__name__)

BASE_URL = DEFAULT_KASI_META["endpoint_base"]

OPERATIONS = [
    ("getRestDeInfo", "holiday", True, "🔴", "한국천문연구원 공휴일 정보조회 OpenAPI 공식 제공 일정"),
    ("getHoliDeInfo", "national", False, "🇰🇷", "한국천문연구원 국경일 정보조회 OpenAPI 공식 제공 일정"),
    ("getAnniversaryInfo", "anniversary", False, "🏛️", "한국천문연구원 기념일 정보조회 OpenAPI 공식 제공 일정"),
    ("get24DivisionsInfo", "solar_term", False, "🌿", "한국천문연구원 24절기 정보조회 OpenAPI 공식 제공 일정"),
    ("getSundryDayInfo", "sundry", False, "🌕", "한국천문연구원 잡절 정보조회 OpenAPI 공식 제공 일정"),
]


def _prepare_key_variants(raw_key: str) -> List[str]:
    """
    공공데이터포털 일반 인증키(Encoding / Decoding) 혼동 방지를 위해
    URL-encoded 버전과 Raw 버전을 모두 생성합니다.
    """
    clean = raw_key.strip()
    if not clean:
        return []
    unquoted = urllib.parse.unquote(clean)
    quoted = urllib.parse.quote(unquoted, safe="")
    variants = [quoted]
    if clean != quoted:
        variants.append(clean)
    return variants


def _parse_kasi_response(text: str) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    한국천문연구원 OpenAPI의 JSON 또는 XML 응답을 파싱합니다.
    반환값: (성공여부, 상태메시지, 아이템리스트)
    """
    raw = text.strip()
    if not raw:
        return False, "빈 응답 수신", []

    # 1. JSON 파싱 시도
    if raw.startswith("{"):
        try:
            import json
            data = json.loads(raw)
            resp = data.get("response", {})
            header = resp.get("header", {})
            result_code = str(header.get("resultCode", ""))
            result_msg = str(header.get("resultMsg", ""))
            if result_code and result_code != "00":
                return False, f"API 오류 ({result_code}): {result_msg}", []

            body = resp.get("body", {})
            items_node = body.get("items", "")
            if not items_node or not isinstance(items_node, dict):
                return True, "정상 (해당 기간 데이터 없음)", []
            item_list = items_node.get("item", [])
            if isinstance(item_list, dict):
                item_list = [item_list]
            elif not isinstance(item_list, list):
                item_list = []
            return True, "정상 (00)", item_list
        except Exception as exc:
            logger.debug(f"JSON 파싱 실패, XML 파싱 시도: {exc}")

    # 2. XML 파싱 시도 (공공데이터포털 게이트웨이 에러 또는 XML 응답)
    try:
        root = ET.fromstring(raw)
        # OpenAPI_ServiceResponse 에러 체크
        err_msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg")
        err_code = root.findtext(".//returnReasonCode")
        if err_msg or err_code:
            return False, f"공공데이터포털 게이트웨이 오류 ({err_code}): {err_msg}", []

        result_code = root.findtext(".//header/resultCode") or ""
        result_msg = root.findtext(".//header/resultMsg") or ""
        if result_code and result_code != "00":
            return False, f"KASI API 오류 ({result_code}): {result_msg}", []

        items: List[Dict[str, Any]] = []
        for item_el in root.findall(".//body/items/item"):
            row: Dict[str, Any] = {}
            for child in item_el:
                row[child.tag] = (child.text or "").strip()
            if row:
                items.append(row)
        return True, f"정상 ({result_code or '00'})", items
    except Exception as exc:
        return False, f"응답 파싱 실패: {exc}", []


def _call_single_operation(
    service_key: str,
    operation: str,
    year: int,
    month: Optional[int] = None,
    timeout: int = 8,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """단일 오퍼레이션 호출 (인코딩/디코딩 인증키 자동 폴백 포함)."""
    variants = _prepare_key_variants(service_key)
    if not variants:
        return False, "인증키(ServiceKey)가 비어 있습니다.", []

    last_msg = ""
    for encoded_key in variants:
        params = [
            f"ServiceKey={encoded_key}",
            f"solYear={year}",
            "numOfRows=200",
            "pageNo=1",
            "_type=json",
        ]
        if month is not None:
            params.append(f"solMonth={month:02d}")

        url = f"{BASE_URL}/{operation}?" + "&".join(params)
        try:
            resp = requests.get(url, timeout=timeout)
            ok, msg, items = _parse_kasi_response(resp.text)
            if ok:
                return True, msg, items
            last_msg = msg
            # 인증키 오류인 경우 다음 인코딩 변형 시도
            if "KEY" in msg.upper() or "AUTH" in msg.upper():
                continue
        except Exception as exc:
            last_msg = f"네트워크 요청 실패: {exc}"

    return False, last_msg, []


def test_kasi_api_key(service_key: str, test_year: int = 2026) -> Dict[str, Any]:
    """
    입력된 공공데이터포털 한국천문연구원_특일 정보 API 키의 유효성을 즉시 검증합니다.
    """
    if not service_key or not service_key.strip():
        return {
            "ok": False,
            "message": "인증키(ServiceKey)가 입력되지 않았습니다.",
            "sample_count": 0,
            "samples": [],
        }

    ok, msg, items = _call_single_operation(
        service_key=service_key,
        operation="getRestDeInfo",
        year=test_year,
        month=5,
        timeout=8,
    )
    if not ok:
        return {
            "ok": False,
            "message": msg,
            "sample_count": 0,
            "samples": [],
        }

    return {
        "ok": True,
        "message": f"✅ 한국천문연구원_특일 정보 OpenAPI 정상 연결 완료 ({test_year}년 5월 샘플 {len(items)}건 수신)",
        "sample_count": len(items),
        "samples": items[:5],
    }


def fetch_kasi_openapi_events(
    service_key: str,
    years: List[int],
    max_workers: int = 8,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    공공데이터포털 한국천문연구원_특일 정보 5대 오퍼레이션을 병렬 호출하여
    표준 이벤트 리스트로 변환합니다.
    """
    if not service_key or not service_key.strip():
        return [], {"ok": False, "reason": "no_service_key", "fetched_count": 0}

    tasks = []
    for y in years:
        for op_name, cat, default_hol, emj, desc in OPERATIONS:
            tasks.append((y, op_name, cat, default_hol, emj, desc))

    collected: List[Dict[str, Any]] = []
    errors: List[str] = []
    success_calls = 0

    def _worker(task_tuple: Tuple[int, str, str, bool, str, str]) -> List[Dict[str, Any]]:
        nonlocal success_calls
        y, op_name, cat, default_hol, emj, desc = task_tuple
        ok, msg, items = _call_single_operation(service_key, op_name, year=y)
        # 만약 연도 전체 조회가 비어있거나 월 파라미터 필수인 경우 1~12월 조회 폴백
        if ok and not items:
            month_items: List[Dict[str, Any]] = []
            for m in range(1, 13):
                m_ok, _, m_list = _call_single_operation(service_key, op_name, year=y, month=m)
                if m_ok and m_list:
                    month_items.extend(m_list)
            items = month_items

        if not ok:
            errors.append(f"{y}/{op_name}: {msg}")
            return []

        success_calls += 1
        out: List[Dict[str, Any]] = []
        for idx, it in enumerate(items, start=1):
            loc = str(it.get("locdate", "")).strip()
            name = str(it.get("dateName", "")).strip()
            if len(loc) != 8 or not name:
                continue
            try:
                d_obj = datetime.strptime(loc, "%Y%m%d").date()
            except ValueError:
                continue

            is_hol_flag = str(it.get("isHoliday", "Y" if default_hol else "N")).upper() == "Y"
            kst_raw = str(it.get("kst", "")).strip()
            kst_fmt = f"{kst_raw[:2]}:{kst_raw[2:]}" if len(kst_raw) == 4 and kst_raw.isdigit() else kst_raw
            date_kind = str(it.get("dateKind", "")).strip()

            actual_cat = cat
            if is_hol_flag and cat == "national":
                actual_cat = "holiday"

            ev = make_event(
                target_date=d_obj,
                title=name,
                category=actual_cat,
                is_holiday=is_hol_flag,
                emoji=emj,
                description=f"{desc}\n• 공공데이터포털 한국천문연구원_특일 정보({op_name}) 공식 데이터",
                kst=kst_fmt,
                source="KASI_OPENAPI",
                seq=int(it.get("seq", idx)) if str(it.get("seq", "")).isdigit() else idx,
                date_kind_override=date_kind or None,
            )
            out.append(ev)
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_worker, t) for t in tasks]
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    collected.extend(res)
            except Exception as exc:
                errors.append(str(exc))

    stats = {
        "ok": success_calls > 0,
        "success_calls": success_calls,
        "total_calls": len(tasks),
        "fetched_count": len(collected),
        "errors": errors[:5],
    }
    return collected, stats
