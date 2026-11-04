import argparse
import logging
import sys
import uvicorn

from app.config import DEFAULT_END_YEAR, DEFAULT_START_YEAR, HOST, LOG_DIR, PORT
from app.service import KoreaCalendarService

log_file = LOG_DIR / "korea_calendar.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def run_cli(start_year: int = DEFAULT_START_YEAR, end_year: int = DEFAULT_END_YEAR) -> None:
    logger.info("=" * 70)
    logger.info(f"🇰🇷 대한민국 특일·절기·기념일 종합 캘린더 생성기 CLI 실행 ({start_year}~{end_year}년)")
    logger.info("=" * 70)

    svc = KoreaCalendarService()
    res = svc.sync(start_year=start_year, end_year=end_year)
    svc._ensure_default_shared_calendars()

    logger.info(
        f"✅ 동기화 완료: 총 {res['total_events']}건 생성 (모드: {res['mode']}, 소요시간: {res['duration_sec']}초)"
    )
    for preset_id, fpath in res["preset_files"]["files"].items():
        cnt = res["preset_files"]["counts"].get(preset_id, 0)
        logger.info(f"📂 [{preset_id}] ({cnt}건) -> {fpath}")
    logger.info("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="공공데이터포털 한국천문연구원_특일 정보 기반 대한민국 종합 캘린더 & 파일 공유 서버"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="웹 서버를 띄우지 않고 1회성으로 6종 프리셋 .ics 캘린더 파일만 즉시 생성 후 종료합니다.",
    )
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    if args.cli:
        run_cli(start_year=args.start_year, end_year=args.end_year)
    else:
        logger.info("=" * 70)
        logger.info(
            f"🌐 대한민국 특일·절기·기념일 스마트 캘린더 & 공유 서버 시작 (http://{args.host}:{args.port})"
        )
        logger.info("=" * 70)
        uvicorn.run("app.server:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
