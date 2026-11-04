from datetime import date
from fastapi.testclient import TestClient

from app.ics_builder import events_to_ics_text
from app.kasi_api import _parse_kasi_response, _prepare_key_variants
from app.kasi_engine import (
    compute_solar_terms_for_year,
    generate_year_events,
    get_lunar_info,
    lunar_to_solar,
)
from app.server import app


def test_lunar_and_ganji_conversion():
    # 2026년 7월 15일(초복): 음력 2026-06-02, 병오년 을미월 경인일
    info = get_lunar_info(date(2026, 7, 15))
    assert info["lunar_year"] == 2026
    assert info["lunar_month"] == 6
    assert info["lunar_day"] == 2
    assert info["day_ganji"] == "경인일"
    assert "병오년" in info["ganji"]

    # 음력 2026년 1월 1일(설날) -> 양력 2026-02-17
    seollal = lunar_to_solar(2026, 1, 1, False)
    assert seollal == date(2026, 2, 17)


def test_24_solar_terms_precision():
    terms_2026 = {t["name"]: t["date"] for t in compute_solar_terms_for_year(2026)}
    assert len(terms_2026) == 24
    assert terms_2026["입춘"] == date(2026, 2, 4)
    assert terms_2026["춘분"] == date(2026, 3, 20)
    assert terms_2026["하지"] == date(2026, 6, 21)
    assert terms_2026["입추"] == date(2026, 8, 7)
    assert terms_2026["추분"] == date(2026, 9, 23)
    assert terms_2026["동지"] == date(2026, 12, 22)


def test_holidays_and_substitute_holidays_2026():
    evs = generate_year_events(2026)
    holidays = {e["start_date"]: e["title"] for e in evs if e["isHoliday"] == "Y"}

    # 삼일절(일) -> 3/2 대체공휴일
    assert "2026-03-01" in holidays
    assert "2026-03-02" in holidays
    # 부처님오신날(5/24 일) -> 5/25 대체공휴일
    assert "2026-05-24" in holidays
    assert "2026-05-25" in holidays
    # 광복절(8/15 토) -> 8/17 대체공휴일
    assert "2026-08-15" in holidays
    assert "2026-08-17" in holidays
    # 개천절(10/3 토) -> 10/5 대체공휴일
    assert "2026-10-03" in holidays
    assert "2026-10-05" in holidays

    # 삼복(초복·중복·말복) 검증
    sundry_map = {e["title"]: e["start_date"] for e in evs if e["category"] == "sundry"}
    assert sundry_map["초복 (初伏)"] == "2026-07-15"
    assert sundry_map["중복 (中伏)"] == "2026-07-25"
    assert sundry_map["말복 (末伏)"] == "2026-08-14"


def test_kasi_openapi_parser_and_key_variants():
    variants = _prepare_key_variants("abc+def/123==")
    assert len(variants) == 2
    assert "abc%2Bdef%2F123%3D%3D" in variants

    sample_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <response>
      <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
      <body>
        <items>
          <item>
            <dateKind>01</dateKind>
            <dateName>광복절</dateName>
            <isHoliday>Y</isHoliday>
            <locdate>20260815</locdate>
            <seq>1</seq>
          </item>
        </items>
      </body>
    </response>"""
    ok, msg, items = _parse_kasi_response(sample_xml)
    assert ok is True
    assert len(items) == 1
    assert items[0]["dateName"] == "광복절"


def test_ics_builder_rfc5545():
    evs = [e for e in generate_year_events(2026) if e["isHoliday"] == "Y"][:3]
    ics_text = events_to_ics_text(
        evs,
        calendar_name="테스트 공휴일 달력",
        include_emoji=True,
        include_lunar_in_title=True,
        alarm_mode="day_before_9am",
    )
    assert "BEGIN:VCALENDAR" in ics_text
    assert "DTSTART;VALUE=DATE:20260101" in ics_text
    assert "DTEND;VALUE=DATE:20260102" in ics_text
    assert "BEGIN:VALARM" in ics_text
    assert "END:VCALENDAR" in ics_text


def test_server_endpoints():
    with TestClient(app) as client:
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "healthy"

        r_stats = client.get("/api/stats")
        assert r_stats.status_code == 200
        data = r_stats.json()
        assert data["stats"]["total_events"] > 2000
        assert data["stats"]["api_config"]["expire_date"] == "2028-05-14"
        # 개인정보(인증키)가 API 응답에 절대 노출되지 않는지 검증
        assert "service_key" not in data["stats"]["api_config"]

        r_cfg = client.get("/api/kasi-config")
        assert r_cfg.status_code == 200
        assert "service_key" not in r_cfg.json()

        r_ver = client.post("/api/kasi-verify")
        assert r_ver.status_code == 200
        assert "service_key" not in r_ver.json()["config"]

        r_ics = client.get("/calendar/holidays.ics")
        assert r_ics.status_code == 200
        assert "BEGIN:VCALENDAR" in r_ics.text

        r_share = client.post(
            "/api/shared",
            json={
                "name": "단위테스트 공유달력",
                "categories": ["holiday", "solar_term"],
                "start_year": 2026,
                "end_year": 2027,
            },
        )
        assert r_share.status_code == 200
        share_id = r_share.json()["item"]["id"]

        r_dl = client.get(f"/share/{share_id}.ics")
        assert r_dl.status_code == 200
        assert "BEGIN:VCALENDAR" in r_dl.text

        r_del = client.delete(f"/api/shared/{share_id}")
        assert r_del.status_code == 200
