# 🇰🇷 대한민국 특일·절기·기념일 스마트 캘린더 & 공유 허브 (`korea_calendar`)

[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-kimmingil%2Fkorea__calendar-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/kimmingil/korea_calendar)
[![GHCR](https://img.shields.io/badge/GHCR-ghcr.io%2Fmingil%2Fkorea__calendar-181717?logo=github&logoColor=white)](https://github.com/mingil/korea_calendar/pkgs/container/korea_calendar)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

> **누구나 도커(Docker) 한 줄로 셀프 호스팅 가능한 대한민국 올인원 역서·달력·공유 서버**  
> 공공데이터포털 **`한국천문연구원_특일 정보 (SpcdeInfoService)`** OpenAPI와 **한국천문연구원(KASI) 역서 규격 내장 천문·역법 계산 엔진**을 결합하여, **대한민국의 모든 5대 국경일 · 법정공휴일 · 대체공휴일 · 선거일 · 75종 국가 법정기념일 · 24절기(절입시각 포함) · 전통 잡절(초복·중복·말복 삼복, 한식, 단오, 정월대보름, 칠석, 백중, 납일 등) · 음력 초하루/보름 · 육십갑자(세차/월건/일진)**를 총망라하고, 내가 필요할 때 언제든 **맞춤형 `.ics` 캘린더 파일 생성 · 실시간 구독 URL · 모바일 QR코드 공유**를 제공하는 셀프호스팅 도커 솔루션입니다.

---

## ✨ 왜 `korea_calendar` 인가요? (핵심 특징)

1. **API 키 없이도 즉시 100% 작동 + 공공데이터포털 OpenAPI 하이브리드 연동**
   - **내장 KASI 천문·역법 엔진 기본 탑재:** 컨테이너를 띄우는 즉시(0.1초) 태양 황경(15° 간격) 천문 계산과 음양력·육십갑자 일진(경일·무일·미일) 알고리즘, 최신 「관공서의 공휴일에 관한 규정」 대체공휴일 법령 로직으로 **2020년~미래 연도(자동 확장) 약 2,580+건의 모든 대한민국 일정**을 생성합니다.
   - **공공데이터포털 실시간 병합:** 웹 대시보드 상단 **[🔑 공공데이터포털 API 설정]** 창(또는 `.env` 환경변수)에 공공데이터포털 `한국천문연구원_특일 정보` 일반 인증키(Encoding/Decoding 자동 호환)를 입력하면, **정부가 수시로 지정하는 임시공휴일이나 신규 법정기념일**까지 12시간마다 자동으로 병합·업데이트합니다.
2. **내가 필요할 때 언제든 만드는 `.ics` 캘린더 파일 공유 스튜디오**
   - **6종 기본 프리셋 `.ics` 파일** 상시 제공 (`종합 전체본`, `빨간날(공휴일) 전용`, `공휴일+24절기+삼복 실속 추천본`, `24절기+잡절 전용`, `75종 국가기념일 전용`, `음력 초하루·보름 전용`)
   - **나만의 맞춤 공유 캘린더 빌더:** 원하는 분류, 연도 범위, 음력 병기 여부, 미리 알림(하루 전/당일 오전 9시)을 골라 **고유 공유 링크(`/share/<ID>.ics`) 발급**, **스마트폰 카메라 스캔용 오프라인 SVG QR코드 생성**, **`.ics` 및 엑셀(CSV) 다운로드**를 지원합니다.
3. **양력 / 음력 매년 반복 '나만의 기념일·가족 행사' 등록**
   - 웹 화면에서 부모님 음력 생신이나 제사/기일, 결혼기념일을 한 번 등록해 두면 매년 자동으로 양력 날짜가 계산되어 달력과 `.ics` 공유 파일에 함께 포함됩니다.
4. **시간이 흐르면 달력도 평생 자동 업데이트 (Zero-Maintenance)**
   - 12시간마다 백그라운드 자동 동기화가 실행되며, 해가 바뀌면 **항상 '현재 연도 + 6년 뒤'까지 미래 연도 달력이 자동으로 확장**됩니다.

---

## 🚀 1분 셀프 호스팅 설치 방법 (Docker / Synology NAS)

### 방법 A: `docker-compose.yml`로 실행 (시놀로지 Container Manager / Portainer 권장)

원하는 폴더(예: `/volume1/docker/korea_calendar`)를 만들고 아래 `docker-compose.yml`로 실행하세요.

```yaml
services:
  korea-calendar:
    image: kimmingil/korea_calendar:latest
    # 또는 GHCR 이미지 사용 가능: ghcr.io/mingil/korea_calendar:latest
    container_name: korea_calendar
    restart: unless-stopped
    init: true
    user: "1026:100"          # 시놀로지 기본 사용자(1026:100) 또는 일반 리눅스(1000:1000)
    ports:
      - "38503:8500"          # 호스트 포트(원하는 포트로 변경 가능) : 컨테이너 내부 포트(8500)
    environment:
      - TZ=Asia/Seoul
      - KOREA_CAL_HOST=0.0.0.0
      - KOREA_CAL_PORT=8500
      - KOREA_CAL_AUTO_SYNC_MINUTES=720   # 12시간마다 자동 최신화
      - DATA_GO_KR_SERVICE_KEY=           # 선택사항 (웹 대시보드에서도 입력/저장 가능)
    volumes:
      - ./output:/app/output  # 6종 기본 .ics 및 공유 보관함(output/shared) 폴더
      - ./data:/app/data      # API 키 설정, 나만의 기념일 및 캐시 영구 보존 폴더
      - ./logs:/app/logs      # 실행 로그 폴더
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8500/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    deploy:
      resources:
        limits:
          memory: 256M
```

```bash
docker compose up -d
```

### 방법 B: 터미널 한 줄 명령어로 즉시 실행 (`docker run`)

```bash
docker run -d \
  --name korea_calendar \
  --restart unless-stopped \
  -p 38503:8500 \
  -e TZ=Asia/Seoul \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  kimmingil/korea_calendar:latest
```

---

## 🌐 웹 대시보드 접속 및 캘린더 앱 구독 URL 안내

컨테이너 실행 후 브라우저에서 **`http://<서버_또는_NAS_IP>:38503`** 으로 접속하시면 모든 기능을 바로 사용하실 수 있습니다.

### 🔗 6대 기본 프리셋 실시간 구독 URL (시놀로지 / 구글 / 아이폰 캘린더 'URL로 추가')

| 프리셋 이름 | 실시간 구독 및 다운로드 주소 | 포함 내용 |
| :--- | :--- | :--- |
| **🇰🇷 대한민국 종합 전체 캘린더** | `http://<서버IP>:38503/calendar.ics` | 국경일 + 공휴일 + 법정기념일 + 24절기 + 잡절·세시풍속 전체 |
| **🔴 빨간날(공휴일·국경일) 전용** | `http://<서버IP>:38503/calendar/holidays.ics` | 법정공휴일, 대체공휴일, 선거일 및 5대 국경일만 깔끔하게 수록 |
| **🌟 공휴일 + 24절기 + 삼복 실속본** | `http://<서버IP>:38503/calendar/essential.ics` | 가장 많이 찾는 휴일 + 24절기 + 초복·중복·말복·명절 추천 조합 |
| **🌿 24절기 + 전통 잡절 전용** | `http://<서버IP>:38503/calendar/seasons.ics` | 한국천문연구원 24절기(절입시각) + 삼복·한식·단오·대보름·칠석·백중 |
| **🏛️ 국가 법정기념일 + 국경일** | `http://<서버IP>:38503/calendar/anniversaries.ics` | 대통령령 75종 국가 법정기념일 및 5대 국경일 전체 |
| **🏮 음력 초하루(1일)·보름(15일)** | `http://<서버IP>:38503/calendar/lunar.ics` | 매월 음력 1일/15일(윤달 표기) 및 육십갑자 일진, 음력 명절 |

> 💡 파일로 직접 내려받으시려면 주소 뒤에 `?download=true`를 붙이거나 웹 대시보드에서 **[📥 .ics 파일 받기]** 버튼을 클릭하세요.

---

## 🔑 공공데이터포털 한국천문연구원 API 키 발급 및 등록 안내 (선택사항)

1. [공공데이터포털(data.go.kr)](https://www.data.go.kr)에서 **`한국천문연구원_특일 정보`** 검색 후 활용신청(즉시 자동승인, 만료기한 2년 및 연장 가능)을 진행합니다.
2. 발급된 **일반 인증키(Encoding 또는 Decoding 모두 호환)**를 복사합니다.
3. 웹 대시보드 우측 상단의 **[🔑 공공데이터포털 API 설정]** 버튼을 클릭하여 인증키와 만료예정일을 붙여넣고 **[💾 저장 및 연동 테스트]**를 누르면 즉시 연동됩니다.

---

## ⚙️ 환경변수 (`Environment Variables`) 전체 목록

| 환경변수명 | 기본값 | 설명 |
| :--- | :--- | :--- |
| `TZ` | `Asia/Seoul` | 컨테이너 표준 시간대 |
| `KOREA_CAL_HOST` | `0.0.0.0` | 웹 서버 바인딩 호스트 |
| `KOREA_CAL_PORT` | `8500` | 컨테이너 내부 웹 서버 포트 |
| `KOREA_CAL_AUTO_SYNC_MINUTES` | `720` | 백그라운드 자동 동기화 주기 (분 단위, 기본 12시간) |
| `KOREA_CAL_START_YEAR` | `2020` | 기본 생성 시작 연도 |
| `KOREA_CAL_END_YEAR` | `2032` | 기본 생성 종료 연도 (해가 바뀌면 `현재연도+6년`으로 자동 확장) |
| `DATA_GO_KR_SERVICE_KEY` | *(빈 값)* | 공공데이터포털 한국천문연구원_특일 정보 일반 인증키 (웹 UI에서도 설정 가능) |
| `KASI_APPLIED_DATE` | `2026-05-14` | API 신청일 표시용 메타데이터 |
| `KASI_EXPIRE_DATE` | `2028-05-14` | API 만료예정일 D-Day 계산용 메타데이터 |

---

## 💻 CLI 수동 실행 및 테스트

```bash
# 웹 서버 없이 1회성으로 output/ 폴더에 6종 .ics 파일만 즉시 생성 후 종료
./run.sh --cli

# 단위 테스트 실행
PYTHONPATH=. pytest tests/test_korea_calendar.py -v
```
