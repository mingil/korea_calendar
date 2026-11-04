import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.config import MAX_ICS_BACKUPS, OUTPUT_DIR

logger = logging.getLogger(__name__)

# 기본 제공 6대 프리셋 캘린더 정의
PRESET_CALENDARS: Dict[str, Dict[str, Any]] = {
    "all": {
        "id": "all",
        "filename": "Korea_All_Calendar.ics",
        "title": "🇰🇷 대한민국 종합 특일·절기·기념일 전체 캘린더",
        "subtitle": "국경일 + 법정공휴일 + 법정기념일 + 24절기 + 잡절·세시풍속 통합본",
        "categories": ["holiday", "national", "anniversary", "solar_term", "sundry", "custom"],
        "badge": "대표 통합본",
        "color": "#2563eb",
    },
    "holidays": {
        "id": "holidays",
        "filename": "Korea_Holidays_Only.ics",
        "title": "🔴 대한민국 공휴일·대체공휴일·국경일 전용 캘린더",
        "subtitle": "관공서 공휴일(빨간날), 대체공휴일, 선거일 및 5대 국경일만 깔끔하게 수록",
        "categories": ["holiday", "national"],
        "badge": "빨간날 전용",
        "color": "#ef4444",
    },
    "essential": {
        "id": "essential",
        "filename": "Korea_Holiday_And_Seasons.ics",
        "title": "🌟 대한민국 공휴일 + 24절기 + 삼복·명절 실속 캘린더",
        "subtitle": "가장 많이 찾는 휴일과 계절 절기(입춘~동지), 복날(초복·중복·말복)·세시풍속 추천 조합",
        "categories": ["holiday", "national", "solar_term", "sundry", "custom"],
        "badge": "인기 추천",
        "color": "#10b981",
    },
    "seasons": {
        "id": "seasons",
        "filename": "Korea_SolarTerms_And_Sundry.ics",
        "title": "🌿 한국천문연구원 24절기 & 전통 잡절(삼복·한식·단오) 캘린더",
        "subtitle": "24절기(절입시각 포함)와 초복·중복·말복, 한식, 단오, 정월대보름, 칠석, 백중, 납일",
        "categories": ["solar_term", "sundry"],
        "badge": "절기·세시풍속",
        "color": "#059669",
    },
    "anniversaries": {
        "id": "anniversaries",
        "filename": "Korea_Anniversaries.ics",
        "title": "🏛️ 대한민국 국가 법정기념일 & 국경일 캘린더",
        "subtitle": "대통령령 「각종 기념일 등에 관한 규정」 등 75종 국가 기념일 및 5대 국경일 전체",
        "categories": ["national", "anniversary"],
        "badge": "국가 기념일",
        "color": "#3b82f6",
    },
    "lunar": {
        "id": "lunar",
        "filename": "Korea_Lunar_Calendar.ics",
        "title": "🏮 음력 초하루(1일)·보름(15일) & 전통명절 캘린더",
        "subtitle": "매월 음력 1일/15일(윤달 표시) 및 일진(육십갑자), 음력 명절 확인용 달력",
        "categories": ["lunar", "sundry"],
        "badge": "음력·보름달",
        "color": "#8b5cf6",
    },
}


def _escape_ics_text(value: str) -> str:
    """RFC 5545 텍스트 이스케이프 처리."""
    if not value:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def events_to_ics_text(
    events: Iterable[Dict[str, Any]],
    calendar_name: str = "대한민국 특일·절기·기념일 캘린더",
    include_emoji: bool = True,
    include_lunar_in_title: bool = False,
    holiday_prefix: bool = False,
    alarm_mode: str = "none",
) -> str:
    """
    이벤트 리스트를 RFC 5545 표준 iCalendar(.ics) 문자열로 직렬화합니다.
    - 종일 일정(VALUE=DATE)의 DTEND에 +1일을 적용하여 시놀로지/구글/아이폰 캘린더에서 끊김 없이 표시합니다.
    - 선택적 미리 알림(VALARM) 및 음력 병기, 이모티콘 옵션을 지원합니다.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Korea Special Day Calendar Hub//KASI SpcdeInfoService//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ics_text(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Seoul",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]

    for ev in events:
        if not ev.get("has_valid_date", True) or not ev.get("start_date"):
            continue

        try:
            start_dt = datetime.strptime(ev["start_date"], "%Y-%m-%d").date()
            end_str = ev.get("end_date") or ev["start_date"]
            end_dt = datetime.strptime(end_str, "%Y-%m-%d").date()
            if end_dt < start_dt:
                end_dt = start_dt
            exclusive_end_dt = end_dt + timedelta(days=1)
        except ValueError:
            continue

        base_title = ev.get("emoji_title", ev["title"]) if include_emoji else ev["title"]
        if holiday_prefix and ev.get("isHoliday") == "Y" and "[휴일]" not in base_title:
            base_title = f"[휴일] {base_title}"
        if include_lunar_in_title and ev.get("lunar_short") and ev.get("category") != "lunar":
            base_title = f"{base_title} ({ev['lunar_short']})"

        category_label = ev.get("category_label", "특일정보")
        is_hol_str = "공휴일(빨간날)" if ev.get("isHoliday") == "Y" else "비공휴일"
        lunar_info = ev.get("lunar_date", "")
        ganji_info = ev.get("ganji", "")
        kst_info = ev.get("kst", "")

        desc_parts = [
            f"[분류] {ev.get('emoji', '📅')} {category_label} ({is_hol_str})",
            f"[양력] {ev['start_date']} ({ev.get('weekday_kr', '')}요일)",
        ]
        if lunar_info:
            desc_parts.append(f"[음력/간지] {lunar_info} ({ganji_info})")
        if kst_info:
            desc_parts.append(f"[절입/기준시각] {kst_info} (KST)")
        if ev.get("description"):
            desc_parts.append(f"\n[상세 안내]\n{ev['description']}")

        description = "\n".join(desc_parts)
        categories_csv = ",".join(ev.get("sub_tags") or [category_label])

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{ev['uid']}",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;VALUE=DATE:{start_dt.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{exclusive_end_dt.strftime('%Y%m%d')}",
                f"SUMMARY:{_escape_ics_text(base_title)}",
                f"CATEGORIES:{_escape_ics_text(categories_csv)}",
                f"DESCRIPTION:{_escape_ics_text(description)}",
                "TRANSP:TRANSPARENT",
            ]
        )

        # 선택적 미리 알림 (VALARM)
        if alarm_mode == "same_day_9am":
            lines.extend(
                [
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:{_escape_ics_text(base_title)} 안내",
                    "TRIGGER:PT9H",
                    "END:VALARM",
                ]
            )
        elif alarm_mode == "day_before_9am":
            lines.extend(
                [
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:내일은 {_escape_ics_text(base_title)}입니다.",
                    "TRIGGER:-PT15H",
                    "END:VALARM",
                ]
            )

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def events_to_csv_text(events: Iterable[Dict[str, Any]]) -> str:
    """엑셀 호환 UTF-8 BOM CSV 텍스트를 생성합니다."""
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(
        [
            "양력날짜",
            "요일",
            "명칭",
            "분류",
            "공휴일여부(빨간날)",
            "음력날짜",
            "세차/월건/일진(육십갑자)",
            "절입시각(KST)",
            "태그",
            "상세설명",
            "데이터출처",
        ]
    )
    for ev in events:
        writer.writerow(
            [
                ev.get("start_date", ""),
                ev.get("weekday_kr", ""),
                ev.get("title", ""),
                ev.get("category_label", ""),
                "Y (공휴일)" if ev.get("isHoliday") == "Y" else "N",
                ev.get("lunar_short", ""),
                ev.get("ganji", ""),
                ev.get("kst", ""),
                ", ".join(ev.get("sub_tags") or []),
                (ev.get("description") or "").replace("\n", " / "),
                ev.get("source", ""),
            ]
        )
    return buf.getvalue()


def save_preset_ics_files(
    events: List[Dict[str, Any]],
    output_dir: Optional[Path] = None,
    include_emoji: bool = True,
) -> Dict[str, Any]:
    """
    6대 기본 프리셋 캘린더(.ics) 파일과 타임스탬프 백업본을 output 폴더에 자동 생성합니다.
    """
    target_dir = output_dir or OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_files: Dict[str, str] = {}
    counts: Dict[str, int] = {}

    for preset_id, meta in PRESET_CALENDARS.items():
        allowed_cats = set(meta["categories"])
        filtered = [e for e in events if e.get("category") in allowed_cats]
        ics_text = events_to_ics_text(
            filtered,
            calendar_name=meta["title"],
            include_emoji=include_emoji,
            include_lunar_in_title=(preset_id in ("seasons", "lunar")),
        )
        file_path = target_dir / meta["filename"]
        file_path.write_text(ics_text, encoding="utf-8")
        saved_files[preset_id] = str(file_path)
        counts[preset_id] = len(filtered)

    # 대표 종합본 백업 관리
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target_dir / f"Korea_All_Calendar_{ts}.ics"
    all_path = target_dir / PRESET_CALENDARS["all"]["filename"]
    if all_path.exists():
        backup_path.write_text(all_path.read_text(encoding="utf-8"), encoding="utf-8")

    backups = sorted(
        target_dir.glob("Korea_All_Calendar_20*.ics"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_b in backups[MAX_ICS_BACKUPS:]:
        try:
            old_b.unlink()
        except OSError:
            pass

    return {
        "files": saved_files,
        "counts": counts,
        "latest_all_path": saved_files.get("all", ""),
        "latest_holidays_path": saved_files.get("holidays", ""),
    }
