import hashlib
import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    AUTO_SYNC_INTERVAL_MINUTES,
    BASE_DIR,
    DATA_DIR,
    DEFAULT_END_YEAR,
    DEFAULT_START_YEAR,
    OUTPUT_DIR,
    SHARED_DIR,
    load_api_config,
    save_api_config,
)
from app.ics_builder import PRESET_CALENDARS, events_to_ics_text, save_preset_ics_files
from app.kasi_api import fetch_kasi_openapi_events
from app.kasi_engine import (
    CATEGORY_META,
    WEEKDAY_KR,
    generate_multi_year_events,
    get_lunar_info,
    lunar_to_solar,
    make_event,
)

logger = logging.getLogger(__name__)

CACHE_FILE = DATA_DIR / "events_cache.json"
SEED_FILE = BASE_DIR / "seed" / "events_cache.json"
CUSTOM_EVENTS_FILE = DATA_DIR / "custom_events.json"
SHARED_META_FILE = DATA_DIR / "shared_calendars.json"


class KoreaCalendarService:
    def __init__(
        self,
        cache_file: Path = CACHE_FILE,
        output_dir: Path = OUTPUT_DIR,
        shared_dir: Path = SHARED_DIR,
    ) -> None:
        self.cache_file = cache_file
        self.output_dir = output_dir
        self.shared_dir = shared_dir
        self._lock = threading.RLock()
        self.events: List[Dict[str, Any]] = []
        self.last_synced_at: Optional[str] = None
        self.last_sync_mode: str = "init"
        self.last_sync_duration_sec: float = 0.0
        self.openapi_stats: Dict[str, Any] = {}
        self.is_syncing: bool = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def initialize(self, perform_sync: bool = True) -> None:
        """
        초기 데이터를 로드하고 프리셋 .ics 파일 및 기본 공유 패키지를 준비합니다.
        """
        loaded = self._load_cache()
        if not loaded or perform_sync:
            self.sync(start_year=DEFAULT_START_YEAR, end_year=DEFAULT_END_YEAR)
        else:
            save_preset_ics_files(self.events, self.output_dir)

        self._ensure_default_shared_calendars()

    def _load_cache(self) -> bool:
        target = self.cache_file
        if not target.exists() and SEED_FILE.exists():
            target = SEED_FILE
        if not target.exists():
            return False
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            evs = payload.get("events", [])
            if not evs:
                return False
            with self._lock:
                self.events = evs
                self.last_synced_at = payload.get("last_synced_at")
                self.last_sync_mode = payload.get("last_sync_mode", "cache")
                self.last_sync_duration_sec = payload.get("last_sync_duration_sec", 0.0)
                self.openapi_stats = payload.get("openapi_stats", {})
            logger.info(f"📦 캐시({target.name})에서 {len(self.events)}건의 대한민국 특일 일정을 로드했습니다.")
            return True
        except Exception as exc:
            logger.warning(f"캐시 로드 실패: {exc}")
            return False

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "last_synced_at": self.last_synced_at,
                "last_sync_mode": self.last_sync_mode,
                "last_sync_duration_sec": self.last_sync_duration_sec,
                "openapi_stats": self.openapi_stats,
                "total_count": len(self.events),
                "events": self.events,
            }
            self.cache_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning(f"캐시 저장 실패: {exc}")

    # ------------------------------------------------------------------
    # 나만의 기념일·행사 (양력/음력 반복 지원) 관리
    # ------------------------------------------------------------------
    def list_custom_definitions(self) -> List[Dict[str, Any]]:
        if not CUSTOM_EVENTS_FILE.exists():
            return []
        try:
            return json.loads(CUSTOM_EVENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def add_custom_definition(
        self,
        title: str,
        calendar_type: str = "solar",  # "solar" | "lunar"
        month: int = 1,
        day: int = 1,
        year: Optional[int] = None,
        recurring: bool = True,
        is_holiday: bool = False,
        emoji: str = "⭐",
        description: str = "",
    ) -> Dict[str, Any]:
        defs = self.list_custom_definitions()
        item_id = hashlib.md5(f"{title}-{calendar_type}-{month}-{day}-{time.time()}".encode()).hexdigest()[:8]
        new_def = {
            "id": item_id,
            "title": title.strip(),
            "calendar_type": calendar_type,
            "month": int(month),
            "day": int(day),
            "year": int(year) if year else None,
            "recurring": bool(recurring),
            "is_holiday": bool(is_holiday),
            "emoji": emoji.strip() or "⭐",
            "description": description.strip() or "사용자 등록 맞춤 기념일·행사",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        defs.append(new_def)
        CUSTOM_EVENTS_FILE.write_text(json.dumps(defs, ensure_ascii=False, indent=2), encoding="utf-8")
        self.sync()
        return new_def

    def delete_custom_definition(self, item_id: str) -> bool:
        defs = self.list_custom_definitions()
        filtered = [d for d in defs if d.get("id") != item_id]
        if len(filtered) == len(defs):
            return False
        CUSTOM_EVENTS_FILE.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
        self.sync()
        return True

    def _expand_custom_events(self, start_year: int, end_year: int) -> List[Dict[str, Any]]:
        defs = self.list_custom_definitions()
        expanded: List[Dict[str, Any]] = []
        for d in defs:
            years = range(start_year, end_year + 1) if d.get("recurring", True) else [d.get("year") or date.today().year]
            for y in years:
                if not d.get("recurring", True) and d.get("year") and y != int(d["year"]):
                    continue
                target_d: Optional[date] = None
                if d.get("calendar_type") == "lunar":
                    target_d = lunar_to_solar(y, int(d["month"]), int(d["day"]), is_leap=False)
                else:
                    try:
                        target_d = date(y, int(d["month"]), int(d["day"]))
                    except ValueError:
                        target_d = None
                if not target_d:
                    continue
                cal_label = f"음력 {d['month']}월 {d['day']}일" if d.get("calendar_type") == "lunar" else f"양력 {d['month']}월 {d['day']}일"
                ev = make_event(
                    target_date=target_d,
                    title=d["title"],
                    category="custom",
                    is_holiday=bool(d.get("is_holiday", False)),
                    emoji=d.get("emoji", "⭐"),
                    description=f"{d.get('description', '')}\n• 기준일: {cal_label} ({'매년 반복' if d.get('recurring', True) else f'{y}년 단일'})",
                    sub_tags=["커스텀일정", "나만의기념일"],
                    source="USER_CUSTOM",
                )
                ev["custom_id"] = d["id"]
                expanded.append(ev)
        return expanded

    # ------------------------------------------------------------------
    # 동기화 (내장 KASI 역법 엔진 + 공공데이터포털 KASI 특일정보 OpenAPI)
    # ------------------------------------------------------------------
    def sync(
        self,
        start_year: int = DEFAULT_START_YEAR,
        end_year: int = DEFAULT_END_YEAR,
        openapi_years: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if self.is_syncing:
                return {"status": "already_syncing", "total_events": len(self.events)}
            self.is_syncing = True

        t0 = time.time()
        try:
            # 1. 내장 KASI 표준 천문·역법 엔진으로 전 연도 기본 데이터 생성
            base_events = generate_multi_year_events(start_year, end_year)

            # 2. 공공데이터포털 한국천문연구원_특일 정보 OpenAPI 키가 있으면 실시간 병합
            api_cfg = load_api_config()
            service_key = api_cfg.get("service_key", "")
            api_stats: Dict[str, Any] = {"ok": False, "fetched_count": 0, "mode": "KASI_ENGINE"}

            if service_key:
                cur_y = date.today().year
                target_api_years = openapi_years or [cur_y - 1, cur_y, cur_y + 1]
                api_events, api_stats = fetch_kasi_openapi_events(
                    service_key=service_key,
                    years=target_api_years,
                )
                if api_stats.get("ok") and api_events:
                    base_events = self._merge_openapi_events(base_events, api_events)
                    save_api_config(
                        service_key=service_key,
                        applied_date=api_cfg.get("applied_date", "2026-05-14"),
                        expire_date=api_cfg.get("expire_date", "2028-05-14"),
                        last_api_status=f"✅ 공공데이터포털 KASI OpenAPI 실시간 연동됨 ({api_stats.get('fetched_count', 0)}건 동기화)",
                    )

            # 3. 사용자 정의 커스텀 기념일 병합
            custom_evs = self._expand_custom_events(start_year, end_year)
            if custom_evs:
                base_events.extend(custom_evs)

            # 정렬
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
            sorted_events = sorted(
                base_events,
                key=lambda x: (
                    x["locdate"],
                    0 if x.get("isHoliday") == "Y" else 1,
                    cat_order.get(x.get("category", "anniversary"), 9),
                    x.get("title", ""),
                ),
            )

            duration = round(time.time() - t0, 2)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mode_str = "KASI_HYBRID_OPENAPI" if api_stats.get("ok") else "KASI_ASTRONOMICAL_ENGINE"

            with self._lock:
                self.events = sorted_events
                self.last_synced_at = now_str
                self.last_sync_mode = mode_str
                self.last_sync_duration_sec = duration
                self.openapi_stats = api_stats

            self._save_cache()
            ics_res = save_preset_ics_files(sorted_events, self.output_dir)

            return {
                "status": "ok",
                "mode": mode_str,
                "total_events": len(sorted_events),
                "duration_sec": duration,
                "last_synced_at": now_str,
                "openapi_stats": api_stats,
                "preset_files": ics_res,
            }
        finally:
            with self._lock:
                self.is_syncing = False

    @staticmethod
    def _normalize_title_for_match(title: str) -> str:
        """OpenAPI 명칭과 내장 명칭 매칭용 정규화 (괄호/공백/특수문자 제거)."""
        base = title.split("(")[0].strip()
        base = re.sub(r"[\s·ㆍ\-_]", "", base)
        synonyms = {
            "1월1일": "신정",
            "신정": "신정",
            "기독탄신일": "기독탄신일",
            "성탄절": "기독탄신일",
            "부처님오신날": "부처님오신날",
            "석가탄신일": "부처님오신날",
            "삼일절": "삼일절",
            "31절": "삼일절",
        }
        return synonyms.get(base, base)

    def _merge_openapi_events(
        self,
        engine_events: List[Dict[str, Any]],
        api_events: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        내장 정밀 엔진 이벤트와 한국천문연구원 OpenAPI 응답 이벤트를 스마트하게 병합합니다.
        - 이미 내장 엔진에 있는 일정은 풍부한 해설과 이모티콘을 유지하면서 source를 'KASI_OPENAPI+ENGINE'으로 표시하고 공휴일 여부/절입시각을 최신화합니다.
        - 내장 엔진에 없는 신규 임시공휴일이나 신규 지정 특일은 즉시 추가합니다.
        """
        by_date_norm: Dict[Tuple[str, str], Dict[str, Any]] = {}
        result_list: List[Dict[str, Any]] = []

        for ev in engine_events:
            norm = self._normalize_title_for_match(ev["title"])
            by_date_norm[(ev["locdate"], norm)] = ev
            result_list.append(ev)

        for api_ev in api_events:
            norm = self._normalize_title_for_match(api_ev["title"])
            match = by_date_norm.get((api_ev["locdate"], norm))
            # 대체공휴일 매칭 보강
            if not match and "대체공휴일" in api_ev["title"]:
                for cand in result_list:
                    if cand["locdate"] == api_ev["locdate"] and "대체공휴일" in cand["title"]:
                        match = cand
                        break

            if match:
                match["source"] = "KASI_OPENAPI"
                if api_ev.get("isHoliday") == "Y":
                    match["isHoliday"] = "Y"
                if api_ev.get("kst"):
                    match["kst"] = api_ev["kst"]
            else:
                result_list.append(api_ev)
                by_date_norm[(api_ev["locdate"], norm)] = api_ev

        return result_list

    # ------------------------------------------------------------------
    # 필터링, 검색, 오늘 브리핑, 월간 달력 그리드
    # ------------------------------------------------------------------
    def query_events(
        self,
        q: str = "",
        categories: Optional[List[str]] = None,
        year: Optional[int] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        month: Optional[int] = None,
        holiday_only: bool = False,
        upcoming_only: bool = False,
        include_lunar_cat: bool = True,
        include_popular_cat: bool = True,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self.events)

        today_str = date.today().isoformat()
        allowed_cats = set(categories) if categories else None

        out: List[Dict[str, Any]] = []
        q_lower = q.strip().lower()

        for ev in items:
            cat = ev.get("category", "anniversary")
            if allowed_cats is not None:
                # 'national' 선택 시 5대 국경일 태그가 있는 공휴일(삼일절, 광복절, 개천절, 한글날)도 함께 포함
                if cat not in allowed_cats:
                    if not ("national" in allowed_cats and "5대국경일" in (ev.get("sub_tags") or [])):
                        continue
            else:
                if not include_lunar_cat and cat == "lunar":
                    continue
                if not include_popular_cat and cat == "popular":
                    continue

            if year is not None and ev.get("year") != year:
                continue
            if start_year is not None and ev.get("year", 0) < start_year:
                continue
            if end_year is not None and ev.get("year", 9999) > end_year:
                continue
            if month is not None and ev.get("month") != month:
                continue
            if holiday_only and ev.get("isHoliday") != "Y":
                continue
            if upcoming_only and ev.get("start_date", "") < today_str:
                continue

            if q_lower:
                haystack = " ".join(
                    [
                        ev.get("title", ""),
                        ev.get("category_label", ""),
                        ev.get("description", ""),
                        ev.get("lunar_date", ""),
                        ev.get("ganji", ""),
                        " ".join(ev.get("sub_tags") or []),
                        ev.get("start_date", ""),
                    ]
                ).lower()
                if q_lower not in haystack:
                    continue

            out.append(ev)

        return out

    def get_today_briefing(self, ref_date: Optional[date] = None) -> Dict[str, Any]:
        """오늘의 양력·음력·육십갑자 정보와 오늘 일정, 다가오는 공휴일/절기/명절 D-Day 브리핑."""
        today = ref_date or date.today()
        today_str = today.isoformat()
        lunar = get_lunar_info(today)

        with self._lock:
            all_evs = list(self.events)

        today_events = [e for e in all_evs if e["start_date"] == today_str]
        future_events = [e for e in all_evs if e["start_date"] >= today_str]

        next_holiday = next((e for e in future_events if e.get("isHoliday") == "Y"), None)
        next_solar_term = next((e for e in future_events if e.get("category") == "solar_term"), None)
        next_sundry = next((e for e in future_events if e.get("category") == "sundry"), None)

        def _with_dday(ev: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not ev:
                return None
            ev_d = datetime.strptime(ev["start_date"], "%Y-%m-%d").date()
            diff = (ev_d - today).days
            dday_label = "오늘 (D-Day)" if diff == 0 else f"D-{diff}"
            return {**ev, "d_day": diff, "d_day_label": dday_label}

        # 올해 남은 공휴일 수 계산
        remaining_holidays_this_year = [
            e for e in future_events if e["year"] == today.year and e.get("isHoliday") == "Y"
        ]

        return {
            "today_solar": today_str,
            "today_formatted": f"{today.year}년 {today.month}월 {today.day}일 ({WEEKDAY_KR[today.weekday()]}요일)",
            "lunar": lunar,
            "today_events": today_events,
            "next_holiday": _with_dday(next_holiday),
            "next_solar_term": _with_dday(next_solar_term),
            "next_sundry": _with_dday(next_sundry),
            "remaining_holidays_count": len(remaining_holidays_this_year),
        }

    def get_month_calendar_grid(
        self,
        year: int,
        month: int,
        categories: Optional[List[str]] = None,
        holiday_only: bool = False,
    ) -> Dict[str, Any]:
        """월간 달력 그리드(일~토 7열 달력) 렌더링용 데이터를 생성합니다."""
        import calendar as pycal

        cal = pycal.Calendar(firstweekday=6)  # 일요일 시작 달력
        month_days = list(cal.itermonthdates(year, month))

        month_events = self.query_events(
            categories=categories,
            holiday_only=holiday_only,
        )
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for ev in month_events:
            by_date.setdefault(ev["start_date"], []).append(ev)

        today_str = date.today().isoformat()
        cells: List[Dict[str, Any]] = []
        for d in month_days:
            d_str = d.isoformat()
            li = get_lunar_info(d)
            day_evs = by_date.get(d_str, [])
            is_red_day = (d.weekday() == 6) or any(e.get("isHoliday") == "Y" for e in day_evs)
            is_saturday = d.weekday() == 5 and not is_red_day
            cells.append(
                {
                    "date": d_str,
                    "year": d.year,
                    "month": d.month,
                    "day": d.day,
                    "in_month": d.month == month,
                    "is_today": d_str == today_str,
                    "weekday": d.weekday(),
                    "weekday_kr": WEEKDAY_KR[d.weekday()],
                    "is_red_day": is_red_day,
                    "is_saturday": is_saturday,
                    "lunar_short": li["lunar_short"],
                    "day_ganji": li["day_ganji"],
                    "events": day_evs,
                }
            )

        return {
            "year": year,
            "month": month,
            "title": f"{year}년 {month}월",
            "cells": cells,
            "month_event_count": sum(len(c["events"]) for c in cells if c["in_month"]),
            "month_holiday_count": sum(
                1
                for c in cells
                if c["in_month"] and any(e.get("isHoliday") == "Y" for e in c["events"])
            ),
        }

    # ------------------------------------------------------------------
    # 내가 필요할 때 캘린더 파일 공유 — 커스텀 공유 파일 보관함 관리
    # ------------------------------------------------------------------
    def list_shared_calendars(self) -> List[Dict[str, Any]]:
        if not SHARED_META_FILE.exists():
            return []
        try:
            items = json.loads(SHARED_META_FILE.read_text(encoding="utf-8"))
            # 실제 파일이 존재하는 항목만 필터링
            valid = []
            for it in items:
                fpath = self.shared_dir / it.get("filename", "")
                if fpath.exists():
                    it["size_kb"] = round(fpath.stat().st_size / 1024, 1)
                    valid.append(it)
            return valid
        except Exception:
            return []

    def create_shared_calendar(
        self,
        name: str,
        categories: List[str],
        start_year: int = 2025,
        end_year: int = 2028,
        holiday_only: bool = False,
        include_emoji: bool = True,
        include_lunar_in_title: bool = True,
        holiday_prefix: bool = False,
        alarm_mode: str = "none",
        note: str = "",
        fixed_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        사용자가 선택한 조건으로 즉시 공유 가능한 독립 .ics 파일을 생성하고
        고유 공유 링크(/share/<id>.ics) 및 QR 코드 정보를 등록합니다.
        """
        events = self.query_events(
            categories=categories,
            start_year=start_year,
            end_year=end_year,
            holiday_only=holiday_only,
        )
        clean_name = name.strip() or "대한민국 맞춤 공유 캘린더"
        safe_slug = re.sub(r"[^0-9a-zA-Z가-힣_-]+", "_", clean_name).strip("_")[:40] or "Korea_Custom"
        share_id = fixed_id or hashlib.md5(f"{clean_name}-{time.time()}".encode("utf-8")).hexdigest()[:8]
        filename = f"{share_id}_{safe_slug}.ics"

        ics_text = events_to_ics_text(
            events=events,
            calendar_name=clean_name,
            include_emoji=include_emoji,
            include_lunar_in_title=include_lunar_in_title,
            holiday_prefix=holiday_prefix,
            alarm_mode=alarm_mode,
        )
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.shared_dir / filename
        file_path.write_text(ics_text, encoding="utf-8")

        meta_entry = {
            "id": share_id,
            "name": clean_name,
            "filename": filename,
            "note": note.strip() or f"{start_year}~{end_year}년 선택 일정 {len(events)}건 수록",
            "categories": categories,
            "start_year": start_year,
            "end_year": end_year,
            "holiday_only": holiday_only,
            "include_emoji": include_emoji,
            "include_lunar_in_title": include_lunar_in_title,
            "holiday_prefix": holiday_prefix,
            "alarm_mode": alarm_mode,
            "event_count": len(events),
            "size_kb": round(file_path.stat().st_size / 1024, 1),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "download_path": f"/share/{share_id}.ics",
        }

        existing = [x for x in self.list_shared_calendars() if x.get("id") != share_id]
        existing.insert(0, meta_entry)
        SHARED_META_FILE.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return meta_entry

    def delete_shared_calendar(self, share_id: str) -> bool:
        existing = self.list_shared_calendars()
        target = next((x for x in existing if x.get("id") == share_id), None)
        if not target:
            return False
        fpath = self.shared_dir / target["filename"]
        if fpath.exists():
            try:
                fpath.unlink()
            except OSError:
                pass
        remaining = [x for x in existing if x.get("id") != share_id]
        SHARED_META_FILE.write_text(
            json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True

    def _ensure_default_shared_calendars(self) -> None:
        """최초 실행 시 바로 공유 가능한 대표 추천 캘린더 파일 3종을 공유 보관함에 자동 생성합니다."""
        if self.list_shared_calendars():
            return
        cur_y = date.today().year
        defaults = [
            {
                "fixed_id": "kr-reddays",
                "name": f"🇰🇷 대한민국 공휴일·대체공휴일 공유팩 ({cur_y-1}~{cur_y+3}년)",
                "categories": ["holiday", "national"],
                "start_year": cur_y - 1,
                "end_year": cur_y + 3,
                "holiday_only": False,
                "include_emoji": True,
                "include_lunar_in_title": True,
                "holiday_prefix": True,
                "alarm_mode": "day_before_9am",
                "note": "가족·직장 동료에게 바로 공유하기 좋은 빨간날+국경일+하루 전 알림 달력",
            },
            {
                "fixed_id": "kr-seasons",
                "name": f"🌿 한국천문연구원 24절기 & 삼복(초복·중복·말복)·세시풍속 공유팩",
                "categories": ["solar_term", "sundry"],
                "start_year": cur_y - 1,
                "end_year": cur_y + 3,
                "holiday_only": False,
                "include_emoji": True,
                "include_lunar_in_title": True,
                "holiday_prefix": False,
                "alarm_mode": "same_day_9am",
                "note": "입춘~동지 24절기(절입시각 포함)와 삼복더위 복날, 한식, 단오, 대보름 안내 달력",
            },
            {
                "fixed_id": "kr-allinone",
                "name": f"🏛️ 대한민국 모든 행사·국경일·기념일·절기 마스터 공유팩",
                "categories": ["holiday", "national", "anniversary", "solar_term", "sundry"],
                "start_year": cur_y - 1,
                "end_year": cur_y + 2,
                "holiday_only": False,
                "include_emoji": True,
                "include_lunar_in_title": True,
                "holiday_prefix": False,
                "alarm_mode": "none",
                "note": "대한민국 관련 모든 법정기념일·국경일·공휴일·24절기·잡절이 총망라된 마스터 파일",
            },
        ]
        for item in reversed(defaults):
            self.create_shared_calendar(**item)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            evs = list(self.events)

        by_cat: Dict[str, int] = {k: 0 for k in CATEGORY_META}
        holiday_count = 0
        years_set = set()
        for e in evs:
            c = e.get("category", "anniversary")
            by_cat[c] = by_cat.get(c, 0) + 1
            if e.get("isHoliday") == "Y":
                holiday_count += 1
            if e.get("year"):
                years_set.add(e["year"])

        return {
            "total_events": len(evs),
            "holiday_count": holiday_count,
            "by_category": by_cat,
            "min_year": min(years_set) if years_set else DEFAULT_START_YEAR,
            "max_year": max(years_set) if years_set else DEFAULT_END_YEAR,
            "last_synced_at": self.last_synced_at,
            "last_sync_mode": self.last_sync_mode,
            "last_sync_duration_sec": self.last_sync_duration_sec,
            "shared_count": len(self.list_shared_calendars()),
            "custom_count": len(self.list_custom_definitions()),
            "api_config": load_api_config(),
        }

    # ------------------------------------------------------------------
    # 백그라운드 자동 동기화 데몬 스레드
    # ------------------------------------------------------------------
    def start_background_scheduler(self) -> None:
        if AUTO_SYNC_INTERVAL_MINUTES <= 0:
            return
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return

        def _loop() -> None:
            interval_sec = max(300, AUTO_SYNC_INTERVAL_MINUTES * 60)
            while not self._stop_event.wait(interval_sec):
                try:
                    logger.info("⏰ 백그라운드 정기 특일·절기 동기화 실행 중...")
                    self.sync()
                except Exception as exc:
                    logger.warning(f"백그라운드 동기화 오류: {exc}")

        self._scheduler_thread = threading.Thread(target=_loop, daemon=True, name="kasi-sync-scheduler")
        self._scheduler_thread.start()

    def stop_background_scheduler(self) -> None:
        self._stop_event.set()
