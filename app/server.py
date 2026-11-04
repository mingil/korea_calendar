from contextlib import asynccontextmanager
import io
import logging
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
import qrcode
import qrcode.image.svg

from app.config import (
    DEFAULT_END_YEAR,
    DEFAULT_START_YEAR,
    OUTPUT_DIR,
    SHARED_DIR,
    load_api_config,
    save_api_config,
)
from app.ics_builder import (
    PRESET_CALENDARS,
    events_to_csv_text,
    events_to_ics_text,
)
from app.kasi_api import test_kasi_api_key
from app.kasi_engine import CATEGORY_META
from app.service import KoreaCalendarService

logger = logging.getLogger(__name__)

service = KoreaCalendarService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.initialize(perform_sync=True)
    service.start_background_scheduler()
    yield
    service.stop_background_scheduler()


app = FastAPI(
    title="대한민국 특일·절기·기념일 종합 스마트 캘린더 허브",
    description="공공데이터포털 한국천문연구원(KASI) 특일 정보 기반 모든 국경일·공휴일·법정기념일·24절기·잡절·음력 캘린더 및 파일 공유 도커 서버",
    version="1.0.0",
    lifespan=lifespan,
)


class ApiKeyConfigRequest(BaseModel):
    service_key: str = ""
    applied_date: str = "2026-05-14"
    expire_date: str = "2028-05-14"


class SharedCalendarCreateRequest(BaseModel):
    name: str
    categories: List[str] = ["holiday", "national", "solar_term", "sundry"]
    start_year: int = 2025
    end_year: int = 2028
    holiday_only: bool = False
    include_emoji: bool = True
    include_lunar_in_title: bool = True
    holiday_prefix: bool = False
    alarm_mode: str = "none"
    note: str = ""


class CustomEventCreateRequest(BaseModel):
    title: str
    calendar_type: str = "solar"  # "solar" or "lunar"
    month: int
    day: int
    year: Optional[int] = None
    recurring: bool = True
    is_holiday: bool = False
    emoji: str = "⭐"
    description: str = ""


@app.get("/health")
def health_check() -> Dict[str, Any]:
    stats = service.get_stats()
    return {
        "status": "healthy",
        "service": "korea_calendar",
        "total_events": stats["total_events"],
        "last_synced_at": stats["last_synced_at"],
        "mode": stats["last_sync_mode"],
    }


@app.get("/api/stats")
def api_stats() -> Dict[str, Any]:
    return {
        "stats": service.get_stats(),
        "briefing": service.get_today_briefing(),
        "categories": CATEGORY_META,
        "presets": PRESET_CALENDARS,
    }


@app.get("/api/month-grid")
def api_month_grid(
    year: int = Query(default_factory=lambda: date.today().year),
    month: int = Query(default_factory=lambda: date.today().month),
    categories: Optional[str] = Query(default=None, description="콤마 구분 카테고리 목록"),
    holiday_only: bool = Query(default=False),
) -> Dict[str, Any]:
    cat_list = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    return service.get_month_calendar_grid(
        year=year,
        month=month,
        categories=cat_list,
        holiday_only=holiday_only,
    )


@app.get("/api/events")
def api_events(
    q: str = Query(default=""),
    categories: Optional[str] = Query(default=None),
    year: Optional[int] = Query(default=None),
    start_year: Optional[int] = Query(default=None),
    end_year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
    holiday_only: bool = Query(default=False),
    upcoming_only: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=5000),
) -> Dict[str, Any]:
    cat_list = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    items = service.query_events(
        q=q,
        categories=cat_list,
        year=year,
        start_year=start_year,
        end_year=end_year,
        month=month,
        holiday_only=holiday_only,
        upcoming_only=upcoming_only,
    )
    return {
        "total": len(items),
        "items": items[:limit],
    }


@app.post("/api/sync")
def api_sync(
    start_year: int = Query(default=DEFAULT_START_YEAR),
    end_year: int = Query(default=DEFAULT_END_YEAR),
) -> Dict[str, Any]:
    return service.sync(start_year=start_year, end_year=end_year)


# ------------------------------------------------------------------
# 공공데이터포털 한국천문연구원_특일 정보 API 키 설정 & 테스트
# ------------------------------------------------------------------
@app.get("/api/kasi-config")
def api_get_kasi_config() -> Dict[str, Any]:
    return load_api_config()


@app.post("/api/kasi-config")
def api_save_kasi_config(req: ApiKeyConfigRequest) -> Dict[str, Any]:
    key = req.service_key.strip()
    if key:
        test_res = test_kasi_api_key(key)
        status_msg = test_res["message"]
    else:
        test_res = {"ok": False, "message": "인증키가 비어 있어 내장 KASI 천문·역법 엔진 단독 모드로 동작합니다."}
        status_msg = test_res["message"]

    saved = save_api_config(
        service_key=key,
        applied_date=req.applied_date,
        expire_date=req.expire_date,
        last_api_status=status_msg,
    )
    if test_res.get("ok"):
        service.sync()
    return {
        "config": saved,
        "test_result": test_res,
    }


# ------------------------------------------------------------------
# 나만의 기념일·행사 (양력/음력) 관리 API
# ------------------------------------------------------------------
@app.get("/api/custom-events")
def api_list_custom_events() -> Dict[str, Any]:
    return {"items": service.list_custom_definitions()}


@app.post("/api/custom-events")
def api_add_custom_event(req: CustomEventCreateRequest) -> Dict[str, Any]:
    if not (1 <= req.month <= 12) or not (1 <= req.day <= 31):
        raise HTTPException(status_code=400, detail="월(1~12)과 일(1~31) 범위를 확인해 주세요.")
    created = service.add_custom_definition(
        title=req.title,
        calendar_type=req.calendar_type,
        month=req.month,
        day=req.day,
        year=req.year,
        recurring=req.recurring,
        is_holiday=req.is_holiday,
        emoji=req.emoji,
        description=req.description,
    )
    return {"status": "ok", "item": created}


@app.delete("/api/custom-events/{item_id}")
def api_delete_custom_event(item_id: str) -> Dict[str, Any]:
    ok = service.delete_custom_definition(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="삭제할 기념일을 찾지 못했습니다.")
    return {"status": "ok"}


# ------------------------------------------------------------------
# 공유 캘린더 파일 생성 & 보관함 관리 API
# ------------------------------------------------------------------
@app.get("/api/shared")
def api_list_shared() -> Dict[str, Any]:
    return {"items": service.list_shared_calendars()}


@app.post("/api/shared")
def api_create_shared(req: SharedCalendarCreateRequest) -> Dict[str, Any]:
    created = service.create_shared_calendar(
        name=req.name,
        categories=req.categories,
        start_year=req.start_year,
        end_year=req.end_year,
        holiday_only=req.holiday_only,
        include_emoji=req.include_emoji,
        include_lunar_in_title=req.include_lunar_in_title,
        holiday_prefix=req.holiday_prefix,
        alarm_mode=req.alarm_mode,
        note=req.note,
    )
    return {"status": "ok", "item": created}


@app.delete("/api/shared/{share_id}")
def api_delete_shared(share_id: str) -> Dict[str, Any]:
    ok = service.delete_shared_calendar(share_id)
    if not ok:
        raise HTTPException(status_code=404, detail="공유 캘린더 파일을 찾지 못했습니다.")
    return {"status": "ok"}


@app.get("/share/{share_id}.ics")
@app.get("/share/{share_id}")
def download_shared_ics(share_id: str, download: bool = Query(default=False)) -> Response:
    clean_id = share_id.replace(".ics", "")
    items = service.list_shared_calendars()
    target = next((x for x in items if x.get("id") == clean_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="요청하신 공유 캘린더 파일이 존재하지 않습니다.")

    fpath = SHARED_DIR / target["filename"]
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="캘린더 파일이 디스크에 존재하지 않습니다.")

    content = fpath.read_text(encoding="utf-8")
    quoted_fn = urllib.parse.quote(target["filename"])
    disp_type = "attachment" if download else "inline"
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f"{disp_type}; filename*=UTF-8''{quoted_fn}",
            "Cache-Control": "no-cache",
        },
    )


# ------------------------------------------------------------------
# 프리셋 & 맞춤 .ics / .csv 다운로드 및 실시간 구독 엔드포인트
# ------------------------------------------------------------------
def _build_ics_response(
    events: List[Dict[str, Any]],
    cal_name: str,
    filename: str,
    include_emoji: bool = True,
    include_lunar_in_title: bool = True,
    holiday_prefix: bool = False,
    alarm_mode: str = "none",
    download: bool = False,
) -> Response:
    ics_text = events_to_ics_text(
        events=events,
        calendar_name=cal_name,
        include_emoji=include_emoji,
        include_lunar_in_title=include_lunar_in_title,
        holiday_prefix=holiday_prefix,
        alarm_mode=alarm_mode,
    )
    quoted_fn = urllib.parse.quote(filename)
    disp_type = "attachment" if download else "inline"
    return Response(
        content=ics_text,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f"{disp_type}; filename*=UTF-8''{quoted_fn}",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/calendar.ics")
def get_all_calendar_ics(
    emoji: bool = Query(default=True),
    lunar: bool = Query(default=True),
    holiday_only: bool = Query(default=False),
    alarm: str = Query(default="none"),
    download: bool = Query(default=False),
) -> Response:
    preset = PRESET_CALENDARS["all"]
    evs = service.query_events(
        categories=preset["categories"],
        holiday_only=holiday_only,
    )
    return _build_ics_response(
        events=evs,
        cal_name=preset["title"],
        filename=preset["filename"],
        include_emoji=emoji,
        include_lunar_in_title=lunar,
        alarm_mode=alarm,
        download=download,
    )


@app.get("/calendar/{preset_id}.ics")
def get_preset_or_custom_ics(
    preset_id: str,
    categories: Optional[str] = Query(default=None),
    start_year: Optional[int] = Query(default=None),
    end_year: Optional[int] = Query(default=None),
    holiday_only: bool = Query(default=False),
    emoji: bool = Query(default=True),
    lunar: bool = Query(default=True),
    holiday_prefix: bool = Query(default=False),
    alarm: str = Query(default="none"),
    name: Optional[str] = Query(default=None),
    download: bool = Query(default=False),
) -> Response:
    if preset_id in PRESET_CALENDARS and not categories:
        meta = PRESET_CALENDARS[preset_id]
        evs = service.query_events(
            categories=meta["categories"],
            start_year=start_year,
            end_year=end_year,
            holiday_only=holiday_only,
        )
        return _build_ics_response(
            events=evs,
            cal_name=name or meta["title"],
            filename=meta["filename"],
            include_emoji=emoji,
            include_lunar_in_title=lunar,
            holiday_prefix=holiday_prefix,
            alarm_mode=alarm,
            download=download,
        )

    # Custom dynamic subscription / download
    cat_list = (
        [c.strip() for c in categories.split(",") if c.strip()]
        if categories
        else ["holiday", "national", "solar_term", "sundry"]
    )
    evs = service.query_events(
        categories=cat_list,
        start_year=start_year,
        end_year=end_year,
        holiday_only=holiday_only,
    )
    cal_title = name or "대한민국 맞춤 특일·절기 캘린더"
    return _build_ics_response(
        events=evs,
        cal_name=cal_title,
        filename="Korea_Custom_Calendar.ics",
        include_emoji=emoji,
        include_lunar_in_title=lunar,
        holiday_prefix=holiday_prefix,
        alarm_mode=alarm,
        download=download,
    )


@app.get("/export/events.csv")
def export_events_csv(
    categories: Optional[str] = Query(default=None),
    start_year: Optional[int] = Query(default=None),
    end_year: Optional[int] = Query(default=None),
    holiday_only: bool = Query(default=False),
    q: str = Query(default=""),
) -> Response:
    cat_list = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    evs = service.query_events(
        q=q,
        categories=cat_list,
        start_year=start_year,
        end_year=end_year,
        holiday_only=holiday_only,
    )
    csv_text = events_to_csv_text(evs)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=\"Korea_Special_Calendar.csv\"",
        },
    )


@app.get("/api/qr")
def generate_qr_svg(text: str = Query(..., min_length=1)) -> Response:
    """공유 링크 또는 구독 URL을 스마트폰으로 즉시 스캔할 수 있는 SVG QR코드로 변환합니다."""
    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


# ------------------------------------------------------------------
# 메인 웹 대시보드 (반응형 한국어 SPA)
# ------------------------------------------------------------------
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>🇰🇷 대한민국 특일·절기·기념일 스마트 캘린더 & 공유 허브</title>
  <style>
    :root {
      --bg: #0f172a;
      --bg-card: #1e293b;
      --bg-card-hover: #26354d;
      --bg-sub: #0b1120;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --border: #334155;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --red: #ef4444;
      --red-soft: rgba(239, 68, 68, 0.16);
      --green: #10b981;
      --green-soft: rgba(16, 185, 129, 0.16);
      --amber: #f59e0b;
      --amber-soft: rgba(245, 158, 11, 0.16);
      --purple: #8b5cf6;
      --blue-soft: rgba(59, 130, 246, 0.16);
      --radius: 14px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Pretendard", "Noto Sans KR", "Malgun Gothic", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      min-height: 100vh;
    }
    a { color: inherit; text-decoration: none; }
    button {
      cursor: pointer;
      font-family: inherit;
      border: none;
      border-radius: 10px;
      transition: all 0.15s ease;
    }
    .container {
      max-width: 1440px;
      margin: 0 auto;
      padding: 20px 24px 60px;
    }
    /* 상단 헤더 */
    .hero-header {
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 22px 26px;
      margin-bottom: 18px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
    }
    .hero-title-wrap h1 {
      font-size: 1.55rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .hero-sub {
      color: var(--text-muted);
      font-size: 0.9rem;
      margin-top: 6px;
    }
    .kasi-approval-strip {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-top: 10px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 11px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.07);
      border: 1px solid rgba(255, 255, 255, 0.12);
    }
    .chip.approved {
      background: var(--green-soft);
      color: #34d399;
      border-color: rgba(16, 185, 129, 0.35);
    }
    .chip.expire {
      background: var(--amber-soft);
      color: #fbbf24;
      border-color: rgba(245, 158, 11, 0.35);
    }
    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .btn {
      padding: 10px 16px;
      font-size: 0.88rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      background: #334155;
      color: var(--text);
      border: 1px solid rgba(255,255,255,0.1);
    }
    .btn:hover { background: #475569; transform: translateY(-1px); }
    .btn-primary {
      background: var(--primary);
      color: #fff;
      border-color: transparent;
    }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-red {
      background: var(--red);
      color: #fff;
    }
    .btn-green {
      background: var(--green);
      color: #06281e;
      font-weight: 700;
    }
    .btn-sm {
      padding: 6px 11px;
      font-size: 0.8rem;
      border-radius: 8px;
    }

    /* 오늘의 역서 브리핑 4열 카드 */
    .briefing-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
      margin-bottom: 20px;
    }
    .brief-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .brief-label {
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .brief-main {
      font-size: 1.2rem;
      font-weight: 800;
      margin: 8px 0 4px;
    }
    .brief-sub {
      font-size: 0.84rem;
      color: var(--text-muted);
    }
    .dday-badge {
      padding: 2px 9px;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
      background: var(--red-soft);
      color: #f87171;
    }

    /* 메인 탭 네비게이션 */
    .tabs-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 18px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
    }
    .tab-btn {
      padding: 11px 18px;
      font-size: 0.93rem;
      font-weight: 700;
      border-radius: 11px;
      background: var(--bg-card);
      color: var(--text-muted);
      border: 1px solid var(--border);
    }
    .tab-btn.active {
      background: var(--primary);
      color: #fff;
      border-color: var(--primary);
      box-shadow: 0 4px 14px rgba(59, 130, 246, 0.35);
    }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* 카테고리 필터 바 */
    .cat-filter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 16px;
      background: var(--bg-card);
      padding: 12px 16px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
    }
    .cat-pill {
      padding: 6px 13px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 600;
      background: var(--bg-sub);
      color: var(--text-muted);
      border: 1px solid var(--border);
      cursor: pointer;
      user-select: none;
    }
    .cat-pill.active {
      background: var(--blue-soft);
      color: #60a5fa;
      border-color: #3b82f6;
    }
    .cat-pill.red-active {
      background: var(--red-soft);
      color: #f87171;
      border-color: var(--red);
    }

    /* 월간 달력 그리드 */
    .cal-toolbar {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }
    .cal-nav {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .cal-title {
      font-size: 1.45rem;
      font-weight: 800;
      min-width: 145px;
      text-align: center;
    }
    .cal-grid-wrap {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
    }
    .cal-weekdays {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      background: var(--bg-sub);
      border-bottom: 1px solid var(--border);
      text-align: center;
      font-weight: 700;
      font-size: 0.85rem;
      padding: 10px 0;
    }
    .cal-weekdays div:first-child { color: #f87171; }
    .cal-weekdays div:last-child { color: #60a5fa; }
    .cal-cells {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
    }
    .cal-cell {
      min-height: 122px;
      border-right: 1px solid rgba(255, 255, 255, 0.06);
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      transition: background 0.12s;
    }
    .cal-cell:nth-child(7n) { border-right: none; }
    .cal-cell:hover { background: rgba(255, 255, 255, 0.03); }
    .cal-cell.other-month { opacity: 0.33; background: rgba(0, 0, 0, 0.2); }
    .cal-cell.today-cell {
      background: rgba(59, 130, 246, 0.12);
      box-shadow: inset 0 0 0 2px #3b82f6;
    }
    .cell-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 3px;
    }
    .day-num {
      font-size: 1rem;
      font-weight: 800;
    }
    .day-num.red { color: #f87171; }
    .day-num.sat { color: #60a5fa; }
    .lunar-mini {
      font-size: 0.7rem;
      color: var(--text-muted);
    }
    .ev-chip {
      font-size: 0.74rem;
      padding: 3px 6px;
      border-radius: 6px;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      cursor: pointer;
      border-left: 3px solid transparent;
    }
    .ev-chip.cat-holiday {
      background: rgba(239, 68, 68, 0.2);
      color: #fca5a5;
      border-left-color: #ef4444;
    }
    .ev-chip.cat-national {
      background: rgba(220, 38, 38, 0.2);
      color: #fecaca;
      border-left-color: #dc2626;
    }
    .ev-chip.cat-solar_term {
      background: rgba(16, 185, 129, 0.18);
      color: #6ee7b7;
      border-left-color: #10b981;
    }
    .ev-chip.cat-sundry {
      background: rgba(245, 158, 11, 0.18);
      color: #fde68a;
      border-left-color: #f59e0b;
    }
    .ev-chip.cat-anniversary {
      background: rgba(59, 130, 246, 0.16);
      color: #93c5fd;
      border-left-color: #3b82f6;
    }
    .ev-chip.cat-lunar {
      background: rgba(139, 92, 246, 0.16);
      color: #c4b5fd;
      border-left-color: #8b5cf6;
    }
    .ev-chip.cat-popular {
      background: rgba(236, 72, 153, 0.16);
      color: #f9a8d4;
      border-left-color: #ec4899;
    }
    .ev-chip.cat-custom {
      background: rgba(6, 182, 212, 0.2);
      color: #67e8f9;
      border-left-color: #06b6d4;
    }

    /* 공유 & 맞춤 생성 스튜디오 */
    .studio-grid {
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 20px;
      margin-bottom: 24px;
    }
    @media (max-width: 1024px) {
      .studio-grid { grid-template-columns: 1fr; }
      .cal-cell { min-height: 92px; padding: 5px; }
    }
    .panel-box {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 22px;
    }
    .panel-title {
      font-size: 1.15rem;
      font-weight: 800;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .panel-desc {
      font-size: 0.86rem;
      color: var(--text-muted);
      margin-bottom: 16px;
    }
    .preset-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 12px;
      margin-bottom: 22px;
    }
    .preset-card {
      background: var(--bg-sub);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 15px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 12px;
    }
    .preset-card h4 { font-size: 0.96rem; font-weight: 700; }
    .preset-card p { font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; }
    .preset-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    /* 폼 컨트롤 */
    .form-group { margin-bottom: 14px; }
    .form-label {
      display: block;
      font-size: 0.83rem;
      font-weight: 700;
      margin-bottom: 6px;
      color: #cbd5e1;
    }
    .input, .select {
      width: 100%;
      padding: 10px 12px;
      background: var(--bg-sub);
      border: 1px solid var(--border);
      border-radius: 10px;
      color: var(--text);
      font-size: 0.9rem;
    }
    .check-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 8px;
    }
    .check-item {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-sub);
      padding: 8px 11px;
      border-radius: 9px;
      border: 1px solid var(--border);
      font-size: 0.83rem;
      cursor: pointer;
    }
    .shared-item {
      background: var(--bg-sub);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
      margin-bottom: 10px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }

    /* 리스트 뷰 테이블/카드 */
    .search-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 16px;
      background: var(--bg-card);
      padding: 14px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
    }
    .event-list-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: 12px;
    }
    .ev-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 13px;
      padding: 15px 17px;
      cursor: pointer;
      transition: transform 0.12s, border-color 0.12s;
    }
    .ev-card:hover {
      transform: translateY(-2px);
      border-color: var(--primary);
    }

    /* 모달 */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.72);
      display: none;
      justify-content: center;
      align-items: center;
      z-index: 1000;
      padding: 16px;
    }
    .modal-backdrop.open { display: flex; }
    .modal-box {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 18px;
      max-width: 560px;
      width: 100%;
      padding: 24px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
    }
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #10b981;
      color: #042f2e;
      font-weight: 800;
      padding: 12px 20px;
      border-radius: 12px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.35);
      display: none;
      z-index: 2000;
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- 상단 헤더 -->
    <header class="hero-header">
      <div class="hero-title-wrap">
        <h1>🇰🇷 대한민국 특일·절기·기념일 스마트 캘린더 허브</h1>
        <p class="hero-sub">
          공공데이터포털 <strong>한국천문연구원_특일 정보</strong> 기반 국경일 · 법정공휴일 · 대체공휴일 · 75종 국가기념일 · 24절기 · 삼복(초복·중복·말복) · 음력 올인원 도커 서버
        </p>
        <div class="kasi-approval-strip" id="kasiApprovalStrip">
          <span class="chip approved">✓ [승인] 한국천문연구원_특일 정보 (과학기술)</span>
          <span class="chip">계정개발 · 연장신청 승인</span>
          <span class="chip">신청일: 2026-05-14</span>
          <span class="chip expire" id="expireChip">만료예정일: 2028-05-14</span>
          <span class="chip" id="syncModeChip">로딩 중...</span>
        </div>
      </div>
      <div class="hero-actions">
        <button class="btn btn-green" onclick="switchTab('share')">📤 캘린더 파일 공유 & 다운로드</button>
        <button class="btn" onclick="openCustomModal()">⭐ 나만의 기념일 추가</button>
        <button class="btn" onclick="openApiModal()">🔑 공공데이터포털 API 설정</button>
        <button class="btn btn-primary" onclick="triggerSync()">🔄 즉시 동기화</button>
      </div>
    </header>

    <!-- 오늘의 역서 브리핑 -->
    <section class="briefing-grid" id="briefingGrid">
      <div class="brief-card">
        <div class="brief-label"><span>📅 오늘의 대한민국 일력(日曆)</span><span id="todayWeekdayBadge" class="dday-badge">오늘</span></div>
        <div class="brief-main" id="todaySolarText">-</div>
        <div class="brief-sub" id="todayLunarText">-</div>
      </div>
      <div class="brief-card">
        <div class="brief-label"><span>🔴 다가오는 다음 공휴일 (빨간날)</span><span id="nextHolDday" class="dday-badge">-</span></div>
        <div class="brief-main" id="nextHolTitle">-</div>
        <div class="brief-sub" id="nextHolSub">-</div>
      </div>
      <div class="brief-card">
        <div class="brief-label"><span>🌿 다가오는 다음 24절기</span><span id="nextTermDday" class="dday-badge" style="background:var(--green-soft);color:#34d399;">-</span></div>
        <div class="brief-main" id="nextTermTitle">-</div>
        <div class="brief-sub" id="nextTermSub">-</div>
      </div>
      <div class="brief-card">
        <div class="brief-label"><span>🌕 다가오는 세시풍속·잡절 & 공유팩</span><span id="nextSundryDday" class="dday-badge" style="background:var(--amber-soft);color:#fbbf24;">-</span></div>
        <div class="brief-main" id="nextSundryTitle">-</div>
        <div class="brief-sub" id="totalStatsSub">-</div>
      </div>
    </section>

    <!-- 메인 워크스페이스 탭 -->
    <nav class="tabs-bar">
      <button class="tab-btn active" data-tab="calendar" onclick="switchTab('calendar')">📅 월간 달력 (양력·음력·절기·휴일)</button>
      <button class="tab-btn" data-tab="share" onclick="switchTab('share')">📤 캘린더 파일 공유 & 맞춤 생성 스튜디오</button>
      <button class="tab-btn" data-tab="list" onclick="switchTab('list')">📋 전체 일정 검색 & 타임라인 목록</button>
      <button class="tab-btn" data-tab="manage" onclick="switchTab('manage')">🏛️ 한국천문연구원 API & 내 기념일 관리</button>
    </nav>

    <!-- 탭 1: 월간 대한민국 달력 -->
    <section id="tab-calendar" class="tab-panel active">
      <div class="cat-filter-bar" id="calCatFilterBar">
        <span style="font-size:0.83rem;font-weight:700;color:var(--text-muted);margin-right:4px;">표시 분류:</span>
        <span class="cat-pill active" data-cat="ALL" onclick="toggleCalCat('ALL')">전체 보기</span>
        <span class="cat-pill" data-cat="RED_ONLY" onclick="toggleCalCat('RED_ONLY')">🔴 빨간날(공휴일)만</span>
        <span class="cat-pill" data-cat="holiday" onclick="toggleCalCat('holiday')">🔴 법정공휴일·대체공휴일</span>
        <span class="cat-pill" data-cat="national" onclick="toggleCalCat('national')">🇰🇷 5대 국경일</span>
        <span class="cat-pill" data-cat="solar_term" onclick="toggleCalCat('solar_term')">🌿 24절기</span>
        <span class="cat-pill" data-cat="sundry" onclick="toggleCalCat('sundry')">🌕 잡절·삼복·명절</span>
        <span class="cat-pill" data-cat="anniversary" onclick="toggleCalCat('anniversary')">🏛️ 국가 법정기념일</span>
        <span class="cat-pill" data-cat="lunar" onclick="toggleCalCat('lunar')">🏮 음력 초하루·보름</span>
        <span class="cat-pill" data-cat="popular" onclick="toggleCalCat('popular')">💝 생활기념일</span>
        <span class="cat-pill" data-cat="custom" onclick="toggleCalCat('custom')">⭐ 내 기념일</span>
      </div>

      <div class="cal-toolbar">
        <div class="cal-nav">
          <button class="btn btn-sm" onclick="moveMonth(-1)">◀ 이전 달</button>
          <div class="cal-title" id="calMonthTitle">2026년 11월</div>
          <button class="btn btn-sm" onclick="moveMonth(1)">다음 달 ▶</button>
          <button class="btn btn-sm" onclick="goTodayMonth()">오늘</button>
          <select id="calYearSelect" class="select" style="width:110px;padding:6px 10px;" onchange="onYearMonthSelect()"></select>
          <select id="calMonthSelect" class="select" style="width:90px;padding:6px 10px;" onchange="onYearMonthSelect()"></select>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <span id="calMonthSummary" style="font-size:0.85rem;color:var(--text-muted);"></span>
          <button class="btn btn-sm btn-primary" onclick="downloadCurrentMonthIcs()">📥 이달 일정 .ics 다운로드</button>
        </div>
      </div>

      <div class="cal-grid-wrap">
        <div class="cal-weekdays">
          <div>일 (SUN)</div><div>월 (MON)</div><div>화 (TUE)</div><div>수 (WED)</div><div>목 (THU)</div><div>금 (FRI)</div><div>토 (SAT)</div>
        </div>
        <div class="cal-cells" id="calCellsContainer"></div>
      </div>
    </section>

    <!-- 탭 2: 캘린더 파일 공유 & 맞춤 생성 스튜디오 -->
    <section id="tab-share" class="tab-panel">
      <div class="panel-box" style="margin-bottom:20px;">
        <div class="panel-title">⚡ 1. 원클릭 프리셋 캘린더 파일 다운로드 & 실시간 자동 구독</div>
        <p class="panel-desc">
          필요할 때 바로 파일(<code>.ics</code>)로 다운로드하여 카카오톡·이메일·메신저로 공유하거나, 시놀로지/구글/아이폰 캘린더에 <strong>구독 URL</strong>로 연결하면 매년 자동으로 최신 특일·절기가 반영됩니다.
        </p>
        <div class="preset-cards" id="presetCardsContainer"></div>
      </div>

      <div class="studio-grid">
        <!-- 나만의 맞춤 공유 캘린더 빌더 -->
        <div class="panel-box">
          <div class="panel-title">🎛️ 2. 내가 필요할 때 만드는 맞춤 공유 캘린더 생성기</div>
          <p class="panel-desc">
            원하는 항목(예: 공휴일+24절기+삼복만, 또는 국경일+기념일만)과 연도·알림을 조합해 공유용 고정 <code>.ics</code> 파일을 생성하거나 즉시 다운로드하세요.
          </p>
          <div class="form-group">
            <label class="form-label">공유 캘린더 이름 (파일명 및 달력 제목으로 표시)</label>
            <input type="text" id="builderName" class="input" value="대한민국 공휴일·24절기·삼복 맞춤 달력" placeholder="예: 가족 공유용 공휴일+절기 달력" />
          </div>
          <div class="form-group">
            <label class="form-label">메모 / 용도 설명 (선택)</label>
            <input type="text" id="builderNote" class="input" value="한국천문연구원 특일정보 기반 맞춤 공유 캘린더" />
          </div>
          <div class="form-group">
            <label class="form-label">포함할 일정 분류 선택 (다중 선택 가능)</label>
            <div class="check-grid" id="builderCatChecks">
              <label class="check-item"><input type="checkbox" value="holiday" checked /> 🔴 법정공휴일·대체공휴일</label>
              <label class="check-item"><input type="checkbox" value="national" checked /> 🇰🇷 5대 국경일</label>
              <label class="check-item"><input type="checkbox" value="solar_term" checked /> 🌿 24절기 (입춘~동지)</label>
              <label class="check-item"><input type="checkbox" value="sundry" checked /> 🌕 잡절·삼복(초·중·말복)·명절</label>
              <label class="check-item"><input type="checkbox" value="anniversary" /> 🏛️ 국가 법정기념일 (75종)</label>
              <label class="check-item"><input type="checkbox" value="lunar" /> 🏮 음력 초하루(1일)·보름(15일)</label>
              <label class="check-item"><input type="checkbox" value="popular" /> 💝 대중·생활 데이 기념일</label>
              <label class="check-item"><input type="checkbox" value="custom" checked /> ⭐ 나만의 등록 기념일</label>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px;">
            <div>
              <label class="form-label">시작 연도</label>
              <input type="number" id="builderStartYear" class="input" value="2025" min="2020" max="2035" />
            </div>
            <div>
              <label class="form-label">종료 연도</label>
              <input type="number" id="builderEndYear" class="input" value="2028" min="2020" max="2035" />
            </div>
            <div>
              <label class="form-label">미리 알림 (VALARM)</label>
              <select id="builderAlarm" class="select">
                <option value="none">알림 없음</option>
                <option value="day_before_9am">하루 전 오전 9시 알림</option>
                <option value="same_day_9am">당일 오전 9시 알림</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">표시 스타일 옵션</label>
            <div class="check-grid">
              <label class="check-item"><input type="checkbox" id="builderEmoji" checked /> 제목에 이모티콘 표시</label>
              <label class="check-item"><input type="checkbox" id="builderLunarTitle" checked /> 제목에 음력 날짜 병기</label>
              <label class="check-item"><input type="checkbox" id="builderHolidayPrefix" /> 공휴일에 [휴일] 말머리</label>
              <label class="check-item"><input type="checkbox" id="builderHolidayOnly" /> 빨간날(공휴일)만 추출</label>
            </div>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:18px;">
            <button class="btn btn-green" onclick="createSharedCalendarFile()">💾 공유 보관함에 파일 생성 & 링크 발급</button>
            <button class="btn btn-primary" onclick="directDownloadCustomIcs()">📥 즉시 .ics 파일 다운로드</button>
            <button class="btn" onclick="copyCustomSubscribeUrl()">🔗 맞춤 구독 URL 복사</button>
            <button class="btn" onclick="downloadCustomCsv()">📊 엑셀(CSV) 다운로드</button>
          </div>
        </div>

        <!-- 내가 만든 공유 캘린더 파일 보관함 -->
        <div class="panel-box">
          <div class="panel-title">📂 3. 공유 캘린더 파일 보관함 (언제든 링크·QR·파일 공유)</div>
          <p class="panel-desc">
            생성된 <code>.ics</code> 파일은 도커 볼륨(<code>output/shared/</code>)에 영구 보관되며, 고유 링크나 QR코드로 스마트폰·가족·동료에게 즉시 공유할 수 있습니다.
          </p>
          <div id="sharedFilesContainer"></div>
        </div>
      </div>
    </section>

    <!-- 탭 3: 전체 일정 검색 & 목록 -->
    <section id="tab-list" class="tab-panel">
      <div class="search-bar">
        <input type="text" id="listSearchInput" class="input" style="flex:1;min-width:220px;" placeholder="🔍 행사·기념일·절기·음력·간지 검색 (예: 초복, 대체공휴일, 입춘, 한글날, 과학의 날...)" oninput="loadEventList()" />
        <select id="listYearSelect" class="select" style="width:130px;" onchange="loadEventList()">
          <option value="">전체 연도</option>
        </select>
        <select id="listMonthSelect" class="select" style="width:110px;" onchange="loadEventList()">
          <option value="">전체 월</option>
          <option value="1">1월</option><option value="2">2월</option><option value="3">3월</option>
          <option value="4">4월</option><option value="5">5월</option><option value="6">6월</option>
          <option value="7">7월</option><option value="8">8월</option><option value="9">9월</option>
          <option value="10">10월</option><option value="11">11월</option><option value="12">12월</option>
        </select>
        <select id="listCatSelect" class="select" style="width:185px;" onchange="loadEventList()">
          <option value="">모든 분류</option>
          <option value="holiday">🔴 법정공휴일·대체공휴일</option>
          <option value="national">🇰🇷 5대 국경일</option>
          <option value="anniversary">🏛️ 국가 법정기념일</option>
          <option value="solar_term">🌿 24절기</option>
          <option value="sundry">🌕 잡절·세시풍속</option>
          <option value="lunar">🏮 음력 초하루·보름</option>
          <option value="popular">💝 대중·생활기념일</option>
          <option value="custom">⭐ 나만의 기념일</option>
        </select>
        <label class="check-item" style="padding:8px 12px;">
          <input type="checkbox" id="listHolidayOnly" onchange="loadEventList()" /> 🔴 빨간날만
        </label>
        <button class="btn" onclick="exportCurrentSearchCsv()">📊 검색결과 CSV 저장</button>
      </div>
      <div style="margin-bottom:12px;font-size:0.86rem;color:var(--text-muted);" id="listResultMeta"></div>
      <div class="event-list-grid" id="eventListGrid"></div>
    </section>

    <!-- 탭 4: 한국천문연구원 OpenAPI & 내 기념일 관리 -->
    <section id="tab-manage" class="tab-panel">
      <div class="studio-grid">
        <div class="panel-box">
          <div class="panel-title">🏛️ 공공데이터포털 한국천문연구원_특일 정보 연동 현황</div>
          <p class="panel-desc">
            내장된 한국천문연구원(KASI) 표준 역법·천문 계산 엔진이 기본 동작하며, 공공데이터포털 일반 인증키(ServiceKey)를 등록하면 5대 특일 정보 OpenAPI와 실시간으로 병합·검증합니다.
          </p>
          <div style="background:var(--bg-sub);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px;font-size:0.86rem;">
            <div style="display:grid;grid-template-columns:130px 1fr;row-gap:8px;">
              <span style="color:var(--text-muted);">제공기관 / 분류</span><strong>과학기술정보통신부 한국천문연구원 (과학기술)</strong>
              <span style="color:var(--text-muted);">승인 서비스명</span><strong style="color:#34d399;">[승인] 한국천문연구원_특일 정보 (SpcdeInfoService)</strong>
              <span style="color:var(--text-muted);">활용유형 / 상태</span><strong>계정개발 (연장신청 완료)</strong>
              <span style="color:var(--text-muted);">신청일 / 만료예정일</span><strong>2026-05-14 ~ 2028-05-14</strong>
              <span style="color:var(--text-muted);">연동 오퍼레이션</span><span>국경일(getHoliDeInfo) · 공휴일(getRestDeInfo) · 기념일(getAnniversaryInfo) · 24절기(get24DivisionsInfo) · 잡절(getSundryDayInfo)</span>
              <span style="color:var(--text-muted);">현재 엔진 상태</span><strong id="manageApiStatusText" style="color:#60a5fa;">-</strong>
            </div>
          </div>
          <button class="btn btn-primary" onclick="openApiModal()">🔑 공공데이터포털 일반 인증키(ServiceKey) 입력 / 변경</button>
        </div>

        <div class="panel-box">
          <div class="panel-title">⭐ 나만의 기념일·행사 관리 (양력 / 음력 매년 반복 지원)</div>
          <p class="panel-desc">
            가족 생일(음력 생신 포함), 결혼기념일, 제사/기일, 회사 창립기념일 등을 등록하면 매년 자동으로 양력 날짜가 계산되어 달력과 <code>.ics</code> 공유 파일에 함께 포함됩니다.
          </p>
          <button class="btn btn-green" style="margin-bottom:14px;" onclick="openCustomModal()">➕ 새 기념일·행사 등록하기</button>
          <div id="customEventsListContainer"></div>
        </div>
      </div>
    </section>
  </div>

  <!-- 일정 상세 모달 -->
  <div class="modal-backdrop" id="eventDetailModal" onclick="if(event.target===this)closeModal('eventDetailModal')">
    <div class="modal-box">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">
        <h3 id="modalEvTitle" style="font-size:1.3rem;font-weight:800;"></h3>
        <button class="btn btn-sm" onclick="closeModal('eventDetailModal')">✕ 닫기</button>
      </div>
      <div id="modalEvBadges" style="display:flex;flex-wrap:wrap;gap:6px;margin:12px 0;"></div>
      <div style="background:var(--bg-sub);border:1px solid var(--border);border-radius:12px;padding:15px;font-size:0.9rem;white-space:pre-line;line-height:1.65;" id="modalEvBody"></div>
    </div>
  </div>

  <!-- QR 코드 & 공유 모달 -->
  <div class="modal-backdrop" id="qrModal" onclick="if(event.target===this)closeModal('qrModal')">
    <div class="modal-box" style="text-align:center;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h3 id="qrModalTitle" style="font-size:1.15rem;font-weight:800;">📱 스마트폰 QR코드 스캔 & 링크 공유</h3>
        <button class="btn btn-sm" onclick="closeModal('qrModal')">✕ 닫기</button>
      </div>
      <p style="font-size:0.84rem;color:var(--text-muted);margin-bottom:16px;">
        아이폰·갤럭시 카메라로 아래 QR코드를 스캔하면 캘린더에 바로 추가되거나 <code>.ics</code> 파일을 내려받을 수 있습니다.
      </p>
      <div id="qrImageWrap" style="background:#fff;padding:16px;border-radius:14px;display:inline-block;margin-bottom:14px;"></div>
      <div class="form-group" style="text-align:left;">
        <label class="form-label">공유 및 구독 주소 (URL)</label>
        <input type="text" id="qrUrlInput" class="input" readonly onclick="this.select()" />
      </div>
      <div style="display:flex;justify-content:center;gap:10px;">
        <button class="btn btn-primary" onclick="copyText(document.getElementById('qrUrlInput').value, '공유 주소가 복사되었습니다!')">📋 주소 복사하기</button>
        <a id="qrDirectDownloadBtn" href="#" class="btn btn-green" download>📥 .ics 파일 직접 받기</a>
      </div>
    </div>
  </div>

  <!-- 공공데이터포털 API 키 설정 모달 -->
  <div class="modal-backdrop" id="apiModal" onclick="if(event.target===this)closeModal('apiModal')">
    <div class="modal-box">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <h3 style="font-size:1.2rem;font-weight:800;">🔑 한국천문연구원_특일 정보 OpenAPI 설정</h3>
        <button class="btn btn-sm" onclick="closeModal('apiModal')">✕ 닫기</button>
      </div>
      <p style="font-size:0.84rem;color:var(--text-muted);margin-bottom:14px;">
        공공데이터포털(data.go.kr) 마이페이지 ➔ <strong>[승인] 한국천문연구원_특일 정보</strong>의 일반 인증키(Encoding 또는 Decoding 아무거나)를 붙여넣으시면 자동으로 판별하여 실시간 연동합니다. (비워두셔도 내장 KASI 천문·역법 엔진으로 100% 동작합니다.)
      </p>
      <div class="form-group">
        <label class="form-label">일반 인증키 (ServiceKey - Encoding / Decoding 모두 호환)</label>
        <input type="text" id="apiServiceKeyInput" class="input" placeholder="공공데이터포털 일반 인증키를 입력하세요" />
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label class="form-label">신청일</label>
          <input type="text" id="apiAppliedDateInput" class="input" value="2026-05-14" />
        </div>
        <div class="form-group">
          <label class="form-label">만료예정일</label>
          <input type="text" id="apiExpireDateInput" class="input" value="2028-05-14" />
        </div>
      </div>
      <div id="apiTestResultBox" style="font-size:0.84rem;margin:10px 0;color:#34d399;"></div>
      <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
        <button class="btn" onclick="closeModal('apiModal')">취소</button>
        <button class="btn btn-primary" onclick="saveApiKeyConfig()">💾 저장 및 연동 테스트</button>
      </div>
    </div>
  </div>

  <!-- 나만의 기념일 추가 모달 -->
  <div class="modal-backdrop" id="customModal" onclick="if(event.target===this)closeModal('customModal')">
    <div class="modal-box">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <h3 style="font-size:1.2rem;font-weight:800;">⭐ 나만의 기념일·가족 행사 추가</h3>
        <button class="btn btn-sm" onclick="closeModal('customModal')">✕ 닫기</button>
      </div>
      <div class="form-group">
        <label class="form-label">기념일·행사 이름</label>
        <input type="text" id="custTitle" class="input" placeholder="예: 어머니 생신, 결혼기념일, 창립기념일" />
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">
        <div class="form-group">
          <label class="form-label">양력 / 음력 기준</label>
          <select id="custCalType" class="select">
            <option value="solar">☀️ 양력 기준</option>
            <option value="lunar">🌕 음력 기준 (자동 양력변환)</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">월 (1~12)</label>
          <input type="number" id="custMonth" class="input" value="5" min="1" max="12" />
        </div>
        <div class="form-group">
          <label class="form-label">일 (1~31)</label>
          <input type="number" id="custDay" class="input" value="8" min="1" max="31" />
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label class="form-label">아이콘 이모티콘</label>
          <input type="text" id="custEmoji" class="input" value="🎂" />
        </div>
        <div class="form-group">
          <label class="form-label">반복 및 휴일 표시</label>
          <div style="display:flex;gap:10px;padding-top:8px;">
            <label style="font-size:0.84rem;"><input type="checkbox" id="custRecurring" checked /> 매년 반복</label>
            <label style="font-size:0.84rem;"><input type="checkbox" id="custHoliday" /> 빨간날 표시</label>
          </div>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">상세 메모</label>
        <input type="text" id="custDesc" class="input" placeholder="기념일 설명이나 메모를 입력하세요" />
      </div>
      <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
        <button class="btn" onclick="closeModal('customModal')">취소</button>
        <button class="btn btn-green" onclick="submitCustomEvent()">➕ 등록 및 캘린더 반영</button>
      </div>
    </div>
  </div>

  <div class="toast" id="toastBox"></div>

  <script>
    let curYear = new Date().getFullYear();
    let curMonth = new Date().getMonth() + 1;
    let calSelectedCat = 'ALL';
    let globalStats = null;

    function showToast(msg) {
      const el = document.getElementById('toastBox');
      el.textContent = msg;
      el.style.display = 'block';
      setTimeout(() => { el.style.display = 'none'; }, 2800);
    }

    function copyText(text, msg) {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => showToast(msg || '복사 완료!'));
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast(msg || '복사 완료!');
      }
    }

    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tabId);
      });
      document.querySelectorAll('.tab-panel').forEach(p => {
        p.classList.toggle('active', p.id === 'tab-' + tabId);
      });
      if (tabId === 'calendar') loadMonthGrid();
      if (tabId === 'share') loadSharedCalendars();
      if (tabId === 'list') loadEventList();
      if (tabId === 'manage') loadCustomEventsList();
    }

    function initSelectors() {
      const ySel = document.getElementById('calYearSelect');
      const mSel = document.getElementById('calMonthSelect');
      const lySel = document.getElementById('listYearSelect');
      ySel.innerHTML = '';
      for (let y = 2020; y <= 2032; y++) {
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y + '년';
        if (y === curYear) opt.selected = true;
        ySel.appendChild(opt);

        const lopt = document.createElement('option');
        lopt.value = y;
        lopt.textContent = y + '년';
        if (y === curYear) lopt.selected = true;
        lySel.appendChild(lopt);
      }
      mSel.innerHTML = '';
      for (let m = 1; m <= 12; m++) {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m + '월';
        if (m === curMonth) opt.selected = true;
        mSel.appendChild(opt);
      }
    }

    async function loadDashboardStats() {
      const res = await fetch('/api/stats');
      const data = await res.json();
      globalStats = data;
      const st = data.stats;
      const br = data.briefing;
      const cfg = st.api_config;

      // 상단 만료일 및 모드 배지
      const expChip = document.getElementById('expireChip');
      const dRem = cfg.days_remaining;
      expChip.textContent = `만료예정일: ${cfg.expire_date}` + (dRem !== null ? ` (D-${dRem})` : '');
      document.getElementById('syncModeChip').textContent =
        `총 ${st.total_events.toLocaleString()}건 수록 (${st.min_year}~${st.max_year}년)`;
      document.getElementById('manageApiStatusText').textContent = cfg.last_api_status;

      // 브리핑 카드
      document.getElementById('todaySolarText').textContent = br.today_formatted;
      const todayEvNames = (br.today_events || []).map(e => e.emoji_title).join(', ');
      document.getElementById('todayLunarText').textContent =
        `${br.lunar.lunar_full} (${br.lunar.ganji})` + (todayEvNames ? ` · ${todayEvNames}` : '');

      if (br.next_holiday) {
        document.getElementById('nextHolDday').textContent = br.next_holiday.d_day_label;
        document.getElementById('nextHolTitle').textContent = br.next_holiday.emoji_title;
        document.getElementById('nextHolSub').textContent =
          `${br.next_holiday.start_date} (${br.next_holiday.weekday_kr}) · 올해 남은 공휴일 ${br.remaining_holidays_count}일`;
      }
      if (br.next_solar_term) {
        document.getElementById('nextTermDday').textContent = br.next_solar_term.d_day_label;
        document.getElementById('nextTermTitle').textContent = br.next_solar_term.emoji_title;
        document.getElementById('nextTermSub').textContent =
          `${br.next_solar_term.start_date} (${br.next_solar_term.weekday_kr}) · 절입 ${br.next_solar_term.kst || '-'} KST`;
      }
      if (br.next_sundry) {
        document.getElementById('nextSundryDday').textContent = br.next_sundry.d_day_label;
        document.getElementById('nextSundryTitle').textContent = br.next_sundry.emoji_title;
      }
      document.getElementById('totalStatsSub').textContent =
        `공휴일 ${st.holiday_count}건 · 공유 보관함 ${st.shared_count}개 파일 준비됨`;

      renderPresetCards(data.presets);
    }

    function renderPresetCards(presets) {
      const wrap = document.getElementById('presetCardsContainer');
      const origin = window.location.origin;
      wrap.innerHTML = '';
      Object.values(presets).forEach(p => {
        const subPath = p.id === 'all' ? '/calendar.ics' : `/calendar/${p.id}.ics`;
        const fullUrl = origin + subPath;
        const dlUrl = fullUrl + '?download=true';
        const card = document.createElement('div');
        card.className = 'preset-card';
        card.innerHTML = `
          <div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
              <span class="chip" style="color:${p.color};border-color:${p.color};">${p.badge}</span>
              <code style="font-size:0.74rem;color:var(--text-muted);">${p.filename}</code>
            </div>
            <h4>${p.title}</h4>
            <p>${p.subtitle}</p>
          </div>
          <div class="preset-actions">
            <a href="${dlUrl}" class="btn btn-sm btn-primary" download>📥 .ics 파일 받기</a>
            <button class="btn btn-sm" onclick="copyText('${fullUrl}', '캘린더 자동 구독 URL이 복사되었습니다!')">🔗 구독 URL 복사</button>
            <button class="btn btn-sm" onclick="openQrModal('${p.title}', '${fullUrl}', '${dlUrl}')">📱 QR 공유</button>
          </div>
        `;
        wrap.appendChild(card);
      });
    }

    function toggleCalCat(cat) {
      calSelectedCat = cat;
      document.querySelectorAll('#calCatFilterBar .cat-pill').forEach(el => {
        const isMatch = el.dataset.cat === cat;
        el.classList.toggle('active', isMatch && cat !== 'RED_ONLY');
        el.classList.toggle('red-active', isMatch && cat === 'RED_ONLY');
      });
      loadMonthGrid();
    }

    function moveMonth(delta) {
      curMonth += delta;
      if (curMonth < 1) { curMonth = 12; curYear--; }
      if (curMonth > 12) { curMonth = 1; curYear++; }
      document.getElementById('calYearSelect').value = curYear;
      document.getElementById('calMonthSelect').value = curMonth;
      loadMonthGrid();
    }

    function goTodayMonth() {
      const now = new Date();
      curYear = now.getFullYear();
      curMonth = now.getMonth() + 1;
      document.getElementById('calYearSelect').value = curYear;
      document.getElementById('calMonthSelect').value = curMonth;
      loadMonthGrid();
    }

    function onYearMonthSelect() {
      curYear = parseInt(document.getElementById('calYearSelect').value, 10);
      curMonth = parseInt(document.getElementById('calMonthSelect').value, 10);
      loadMonthGrid();
    }

    async function loadMonthGrid() {
      let url = `/api/month-grid?year=${curYear}&month=${curMonth}`;
      if (calSelectedCat === 'RED_ONLY') {
        url += '&holiday_only=true';
      } else if (calSelectedCat !== 'ALL') {
        url += `&categories=${encodeURIComponent(calSelectedCat)}`;
      }
      const res = await fetch(url);
      const data = await res.json();
      document.getElementById('calMonthTitle').textContent = data.title;
      document.getElementById('calMonthSummary').textContent =
        `이달의 공휴일(빨간날) ${data.month_holiday_count}일 · 전체 특일·절기 ${data.month_event_count}건`;

      const container = document.getElementById('calCellsContainer');
      container.innerHTML = '';
      data.cells.forEach(cell => {
        const div = document.createElement('div');
        div.className = 'cal-cell' + (!cell.in_month ? ' other-month' : '') + (cell.is_today ? ' today-cell' : '');
        const dayClass = cell.is_red_day ? 'red' : (cell.is_saturday ? 'sat' : '');
        let evHtml = '';
        cell.events.slice(0, 5).forEach(ev => {
          const payload = encodeURIComponent(JSON.stringify(ev));
          evHtml += `<div class="ev-chip cat-${ev.category}" onclick="showEventModal('${payload}')" title="${ev.title}">${ev.emoji_title}</div>`;
        });
        if (cell.events.length > 5) {
          evHtml += `<div style="font-size:0.7rem;color:var(--text-muted);padding-left:4px;">+${cell.events.length - 5}건 더보기</div>`;
        }
        div.innerHTML = `
          <div class="cell-header">
            <span class="day-num ${dayClass}">${cell.day}</span>
            <span class="lunar-mini">${cell.lunar_short} · ${cell.day_ganji}</span>
          </div>
          ${evHtml}
        `;
        container.appendChild(div);
      });
    }

    function showEventModal(encodedJson) {
      const ev = JSON.parse(decodeURIComponent(encodedJson));
      document.getElementById('modalEvTitle').textContent = ev.emoji_title;
      const bWrap = document.getElementById('modalEvBadges');
      bWrap.innerHTML = `
        <span class="chip" style="border-color:${ev.category_color};color:${ev.category_color};">${ev.category_label}</span>
        ${ev.isHoliday === 'Y' ? '<span class="chip" style="background:var(--red-soft);color:#f87171;">🔴 법정공휴일 (빨간날)</span>' : ''}
        <span class="chip">📅 양력 ${ev.start_date} (${ev.weekday_kr}요일)</span>
        <span class="chip">🌕 ${ev.lunar_date} (${ev.ganji})</span>
        ${ev.kst ? `<span class="chip">⏰ 절입시각: ${ev.kst} KST</span>` : ''}
      `;
      document.getElementById('modalEvBody').textContent = ev.description || '';
      document.getElementById('eventDetailModal').classList.add('open');
    }

    function closeModal(id) {
      document.getElementById(id).classList.remove('open');
    }

    function openQrModal(title, url, dlUrl) {
      document.getElementById('qrModalTitle').textContent = '📱 ' + title;
      document.getElementById('qrUrlInput').value = url;
      document.getElementById('qrDirectDownloadBtn').href = dlUrl || (url + '?download=true');
      document.getElementById('qrImageWrap').innerHTML =
        `<img src="/api/qr?text=${encodeURIComponent(url)}" alt="QR Code" style="width:210px;height:210px;display:block;" />`;
      document.getElementById('qrModal').classList.add('open');
    }

    function getBuilderParams() {
      const cats = Array.from(document.querySelectorAll('#builderCatChecks input:checked')).map(c => c.value);
      return {
        name: document.getElementById('builderName').value.trim() || '대한민국 맞춤 캘린더',
        note: document.getElementById('builderNote').value.trim(),
        categories: cats.length ? cats : ['holiday'],
        start_year: parseInt(document.getElementById('builderStartYear').value, 10) || 2025,
        end_year: parseInt(document.getElementById('builderEndYear').value, 10) || 2028,
        alarm_mode: document.getElementById('builderAlarm').value,
        include_emoji: document.getElementById('builderEmoji').checked,
        include_lunar_in_title: document.getElementById('builderLunarTitle').checked,
        holiday_prefix: document.getElementById('builderHolidayPrefix').checked,
        holiday_only: document.getElementById('builderHolidayOnly').checked,
      };
    }

    function buildCustomQueryUrl(download = false) {
      const p = getBuilderParams();
      const qs = new URLSearchParams({
        categories: p.categories.join(','),
        start_year: p.start_year,
        end_year: p.end_year,
        holiday_only: p.holiday_only,
        emoji: p.include_emoji,
        lunar: p.include_lunar_in_title,
        holiday_prefix: p.holiday_prefix,
        alarm: p.alarm_mode,
        name: p.name,
        download: download,
      });
      return `${window.location.origin}/calendar/custom.ics?${qs.toString()}`;
    }

    function directDownloadCustomIcs() {
      window.location.href = buildCustomQueryUrl(true);
      showToast('맞춤 .ics 캘린더 파일 다운로드를 시작합니다!');
    }

    function copyCustomSubscribeUrl() {
      const url = buildCustomQueryUrl(false);
      copyText(url, '맞춤 캘린더 실시간 구독 URL이 복사되었습니다!');
    }

    function downloadCustomCsv() {
      const p = getBuilderParams();
      const qs = new URLSearchParams({
        categories: p.categories.join(','),
        start_year: p.start_year,
        end_year: p.end_year,
        holiday_only: p.holiday_only,
      });
      window.location.href = `/export/events.csv?${qs.toString()}`;
    }

    async function createSharedCalendarFile() {
      const p = getBuilderParams();
      const res = await fetch('/api/shared', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(p),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast('✅ 공유 보관함에 새 캘린더 파일이 생성되었습니다!');
        loadSharedCalendars();
        loadDashboardStats();
      }
    }

    async function loadSharedCalendars() {
      const res = await fetch('/api/shared');
      const data = await res.json();
      const wrap = document.getElementById('sharedFilesContainer');
      wrap.innerHTML = '';
      const origin = window.location.origin;
      (data.items || []).forEach(it => {
        const shareUrl = origin + it.download_path;
        const dlUrl = shareUrl + '?download=true';
        const div = document.createElement('div');
        div.className = 'shared-item';
        div.innerHTML = `
          <div style="flex:1;min-width:220px;">
            <div style="font-weight:800;font-size:0.96rem;">${it.name}</div>
            <div style="font-size:0.8rem;color:var(--text-muted);margin-top:3px;">
              ${it.note} · <strong>${it.event_count}건</strong> (${it.size_kb} KB) · 생성: ${it.created_at}
            </div>
            <code style="font-size:0.75rem;color:#60a5fa;">${shareUrl}</code>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;">
            <a href="${dlUrl}" class="btn btn-sm btn-green" download>📥 파일 다운로드</a>
            <button class="btn btn-sm btn-primary" onclick="copyText('${shareUrl}', '공유 링크가 클립보드에 복사되었습니다!')">🔗 공유링크 복사</button>
            <button class="btn btn-sm" onclick="openQrModal('${it.name}', '${shareUrl}', '${dlUrl}')">📱 QR코드</button>
            <button class="btn btn-sm" style="background:rgba(239,68,68,0.2);color:#fca5a5;" onclick="deleteSharedFile('${it.id}')">🗑️</button>
          </div>
        `;
        wrap.appendChild(div);
      });
    }

    async function deleteSharedFile(id) {
      await fetch(`/api/shared/${id}`, { method: 'DELETE' });
      showToast('공유 파일이 삭제되었습니다.');
      loadSharedCalendars();
      loadDashboardStats();
    }

    function downloadCurrentMonthIcs() {
      const url = `/calendar/custom.ics?start_year=${curYear}&end_year=${curYear}&name=${encodeURIComponent(curYear + '년 대한민국 특일 캘린더')}&download=true`;
      window.location.href = url;
    }

    async function loadEventList() {
      const q = document.getElementById('listSearchInput').value.trim();
      const y = document.getElementById('listYearSelect').value;
      const m = document.getElementById('listMonthSelect').value;
      const c = document.getElementById('listCatSelect').value;
      const hol = document.getElementById('listHolidayOnly').checked;

      const qs = new URLSearchParams({ limit: 300 });
      if (q) qs.set('q', q);
      if (y) qs.set('year', y);
      if (m) qs.set('month', m);
      if (c) qs.set('categories', c);
      if (hol) qs.set('holiday_only', 'true');

      const res = await fetch('/api/events?' + qs.toString());
      const data = await res.json();
      document.getElementById('listResultMeta').textContent =
        `검색 조건에 해당하는 일정 총 ${data.total.toLocaleString()}건 (상위 ${data.items.length}건 표시 중)`;

      const grid = document.getElementById('eventListGrid');
      grid.innerHTML = '';
      data.items.forEach(ev => {
        const card = document.createElement('div');
        card.className = 'ev-card';
        const payload = encodeURIComponent(JSON.stringify(ev));
        card.onclick = () => showEventModal(payload);
        card.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <span style="font-size:0.82rem;font-weight:700;color:${ev.isHoliday === 'Y' ? '#f87171' : '#94a3b8'};">
              ${ev.start_date} (${ev.weekday_kr}) · ${ev.lunar_short}
            </span>
            <span class="chip" style="font-size:0.72rem;padding:2px 8px;color:${ev.category_color};">${ev.category_short}</span>
          </div>
          <div style="font-size:1.05rem;font-weight:800;margin-bottom:6px;">
            ${ev.emoji_title}
            ${ev.isHoliday === 'Y' ? '<span style="color:#ef4444;font-size:0.76rem;margin-left:4px;">[공휴일]</span>' : ''}
          </div>
          <div style="font-size:0.8rem;color:var(--text-muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">
            ${ev.description}
          </div>
        `;
        grid.appendChild(card);
      });
    }

    function exportCurrentSearchCsv() {
      const q = document.getElementById('listSearchInput').value.trim();
      const y = document.getElementById('listYearSelect').value;
      const c = document.getElementById('listCatSelect').value;
      const hol = document.getElementById('listHolidayOnly').checked;
      const qs = new URLSearchParams();
      if (q) qs.set('q', q);
      if (y) { qs.set('start_year', y); qs.set('end_year', y); }
      if (c) qs.set('categories', c);
      if (hol) qs.set('holiday_only', 'true');
      window.location.href = '/export/events.csv?' + qs.toString();
    }

    async function openApiModal() {
      const res = await fetch('/api/kasi-config');
      const cfg = await res.json();
      document.getElementById('apiServiceKeyInput').value = cfg.service_key || '';
      document.getElementById('apiAppliedDateInput').value = cfg.applied_date || '2026-05-14';
      document.getElementById('apiExpireDateInput').value = cfg.expire_date || '2028-05-14';
      document.getElementById('apiTestResultBox').textContent = cfg.last_api_status || '';
      document.getElementById('apiModal').classList.add('open');
    }

    async function saveApiKeyConfig() {
      const body = {
        service_key: document.getElementById('apiServiceKeyInput').value.trim(),
        applied_date: document.getElementById('apiAppliedDateInput').value.trim(),
        expire_date: document.getElementById('apiExpireDateInput').value.trim(),
      };
      const res = await fetch('/api/kasi-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      document.getElementById('apiTestResultBox').textContent = data.test_result.message;
      showToast('API 설정이 저장되었습니다.');
      await loadDashboardStats();
      await loadMonthGrid();
    }

    function openCustomModal() {
      document.getElementById('customModal').classList.add('open');
    }

    async function submitCustomEvent() {
      const title = document.getElementById('custTitle').value.trim();
      if (!title) { alert('기념일 이름을 입력해 주세요.'); return; }
      const body = {
        title: title,
        calendar_type: document.getElementById('custCalType').value,
        month: parseInt(document.getElementById('custMonth').value, 10),
        day: parseInt(document.getElementById('custDay').value, 10),
        emoji: document.getElementById('custEmoji').value.trim() || '⭐',
        recurring: document.getElementById('custRecurring').checked,
        is_holiday: document.getElementById('custHoliday').checked,
        description: document.getElementById('custDesc').value.trim(),
      };
      const res = await fetch('/api/custom-events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        closeModal('customModal');
        showToast('⭐ 나만의 기념일이 등록되어 모든 연도 달력에 반영되었습니다!');
        loadDashboardStats();
        loadMonthGrid();
        loadCustomEventsList();
      }
    }

    async function loadCustomEventsList() {
      const res = await fetch('/api/custom-events');
      const data = await res.json();
      const wrap = document.getElementById('customEventsListContainer');
      wrap.innerHTML = '';
      if (!data.items || !data.items.length) {
        wrap.innerHTML = '<div style="font-size:0.85rem;color:var(--text-muted);">아직 등록된 개인 기념일이 없습니다. 위 버튼을 눌러 양력/음력 생일이나 가족 행사를 추가해 보세요!</div>';
        return;
      }
      data.items.forEach(it => {
        const div = document.createElement('div');
        div.className = 'shared-item';
        const calLabel = it.calendar_type === 'lunar' ? `🌕 음력 ${it.month}월 ${it.day}일` : `☀️ 양력 ${it.month}월 ${it.day}일`;
        div.innerHTML = `
          <div>
            <strong>${it.emoji} ${it.title}</strong>
            <span class="chip" style="margin-left:6px;">${calLabel}</span>
            <div style="font-size:0.8rem;color:var(--text-muted);margin-top:3px;">${it.description}</div>
          </div>
          <button class="btn btn-sm" style="background:rgba(239,68,68,0.2);color:#fca5a5;" onclick="deleteCustomEvent('${it.id}')">🗑️ 삭제</button>
        `;
        wrap.appendChild(div);
      });
    }

    async function deleteCustomEvent(id) {
      await fetch(`/api/custom-events/${id}`, { method: 'DELETE' });
      showToast('기념일이 삭제되었습니다.');
      loadCustomEventsList();
      loadDashboardStats();
      loadMonthGrid();
    }

    async function triggerSync() {
      showToast('🔄 한국천문연구원 특일·절기 데이터 동기화 중...');
      const res = await fetch('/api/sync', { method: 'POST' });
      const data = await res.json();
      showToast(`✅ 동기화 완료! 총 ${data.total_events.toLocaleString()}건 (${data.duration_sec}초)`);
      await loadDashboardStats();
      await loadMonthGrid();
    }

    window.addEventListener('DOMContentLoaded', async () => {
      initSelectors();
      await loadDashboardStats();
      await loadMonthGrid();
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=DASHBOARD_HTML)
