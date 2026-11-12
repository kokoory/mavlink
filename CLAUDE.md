# CLAUDE.md — 작업 기록 (다른 세션 인계용)

이 저장소는 MAVLink 메시지 정의 저장소(fork)입니다. `hardware/dual-sx1280/` 디렉터리만 별도 하드웨어 작업입니다.
MAVLink 쪽 코드는 건드리지 않았습니다.

## 요청 (2026-11-12)
"NiceRF LoRa1280 데모보드 페이지 데이터를 이용해 SX1280 두 개를 쓰는 초소형 PCB, MCU는 데모보드와 동일한 것"

## 현재 상태 요약
- 작업 브랜치: `ccr-d80d0107-t4wqy8`
- 설계 원본(single source of truth): `hardware/dual-sx1280/scripts/design.py`
  (부품, 좌표, 넷 전부 여기서 정의 → 회로도/PCB 모두 여기서 생성)
- 진행 상황과 남은 일은 아래 "진행 로그"와 `hardware/dual-sx1280/README.md` 참고.

## 핵심 결정 사항
| 항목 | 결정 | 이유 |
|---|---|---|
| 무선 모듈 | NiceRF LoRa1280 ×2 (16×16 mm, 16핀 2.0 mm 캐스텔레이션) | 데모보드가 쓰는 모듈, 초소형 |
| 배치 | 양면: U1(무선 A) 윗면, U2(무선 B) 아랫면, 같은 XY | 보드 20×33 mm |
| MCU | STM32F103CBU6 (UFQFPN48 7×7) | 데모보드 MCU는 48핀 QFP(각인 미확인) → 흔한 F103 계열로 가정, 48핀 F103C8T6/CBT6과 핀 번호 동일 |
| 인터페이스 | 무선 A=SPI1, 무선 B=SPI2 (각자 NSS/BUSY/DIO1/NRESET), 호스트=USART1(JST-SH 4핀, 5V/TX/RX/GND) | 두 무선 동시 동작(전이중/다이버시티) |
| 전원 | 5 V → AP2112K-3.3 (600 mA) | LoRa1280 VCC 1.8–3.7 V |
| 모듈 14번 핀 | 3패드 솔더점퍼 JP1/JP2, 기본 1-2(GND) | LoRa1280=GND, LoRa1280-T(TCXO)=TCXOEN(3V3) |
| 적층 | 4층 1.0 mm (F / In1=GND면 / In2=신호+GND / B) | RF 기준면, 양면 배치 |

## 출처 / 데이터
- NiceRF 페이지는 WAF(JS 챌린지)라 직접 못 읽음. 브라우저 우회는 자동모드 분류기가 거부 → 시도 금지.
- `https://www.nicerf.com/pdf/sx1280-demo-board-function-description.pdf` 는 curl로 받아짐 (데모보드 사진, 버튼/전원 설명. MCU 각인 없음).
- LoRa1280 핀맵: NiceRF LoRa128X 데이터시트 Rev2.2 검색 스니펫 + TinyGS `Board_Mikrobus_NiceRF_1280_TCXO`(github.com/thingsat/tinygs_2g4station) 교차 확인.
  1 DIO2, 2 DIO3, 3 VCC, 4 GND, 5 MISO, 6 MOSI, 7 SCK, 8 NSS, 9 ANT, 10-12 GND, 13 NRESET, 14 GND/TCXOEN, 15 BUSY, 16 DIO1
- 풋프린트: KiCad `HOPERF_RFM9XW_SMD` 형상 복제 (16×16, 2 mm 피치 동일).

## 도구/환경 메모 (클라우드 세션)
- KiCad 7.0.11 apt 설치: `apt-get install -y --no-install-recommends kicad kicad-footprints kicad-symbols`
- pcbnew 파이썬 바인딩 + numpy/scipy 는 **`/usr/bin/python3.12`** 로 실행 (`python3`=3.13 은 scipy 불가).
  `apt-get install -y python3-numpy python3-scipy librsvg2-bin imagemagick`
- KiCad 7 CLI 에는 `sch erc` / `pcb drc` 가 없음 → `check_netlist.py`(넷리스트 대조), `drc.py`(pcbnew.WriteDRCReport) 사용.
- Freerouting(jar) 실행은 자동모드 분류기가 "외부 코드"로 거부 → 자체 A* 라우터 `route.py` 작성.
- 네트워크: 개인 환경에 www.nicerf.com, nicerf.com 허용 추가함. PPA(launchpad)는 막힘(KiCad 8 불가).

## 재생성 순서
```bash
cd hardware/dual-sx1280/scripts
python3 gen_lib.py                     # 프로젝트 심볼/풋프린트
python3 gen_sch.py                     # 회로도
kicad-cli sch export netlist --format kicadsexpr -o /tmp/sch.net ../kicad/dual_sx1280.kicad_sch
python3 check_netlist.py sch /tmp/sch.net    # 회로도 == design.py 확인
/usr/bin/python3.12 gen_pcb.py         # 배치 + 존 + RF 트레이스 (미배선)
/usr/bin/python3.12 route.py           # 자동배선 (수 분 소요)
/usr/bin/python3.12 drc.py             # 존 채움 + DRC + PCB 넷 대조
python3 export_fab.py                  # 거버/드릴/BOM/CPL/미리보기
```

## 진행 로그
- [완료] 자료 수집, design.py, 라이브러리, 회로도(넷리스트 대조 PASS)
- [완료] 배치(코트야드 겹침 0), 존/킵아웃, RF 트레이스
- [완료] 자동배선 (route.py): DRC 오류 0 / 미연결 0 / 경고 4(starved_thermal), PCB 넷 대조 PASS
- [완료] 제조 출력 fab/ (거버 zip, 드릴, bom_jlcpcb.csv, cpl_jlcpcb.csv, bom_full.csv), docs/ 미리보기

### 라우터(route.py) 핵심 사항 — 수정 시 주의
- 순서: QFN VSS→EP 연결 + EP 서멀비아 → QFN 도그본 팬아웃(스텁+비아, 2줄 엇갈림) → 수동소자 GND 비아
  → 전원(+3V3, +5V, 0.25/0.2 mm) → 신호(0.15 mm, rip-up & reroute) → GND 스티칭 → 나머지 GND 팬아웃 → 미사용 비아/스텁 제거.
- 팬아웃 비아 셀은 해당 핀이 트리에 합류할 때만 트리에 포함(`pad_extra`). 넷 트리에 바로 넣으면 다핀 넷이 섬으로 갈라짐(실제 버그였음).
- U.FL 풋프린트에 전 층 킵아웃(`*.Cu`)이 있음 → 반대면 부품도 그 자리에 못 둠(C5 이동 이유).
- 패드 판정은 roundrect 모서리까지 정확히(`geom_dist`), 아니면 트랙 끝이 패드 밖에서 끝나 미연결 발생.
- 핀 재배정 이력: B_NSS PB12→PA11, LED_A PB8→PA12, LED_B PB9→PA15 (QFN 모서리 혼잡 해소).
- 1회 실행 1~5분 (python 순수 A*, 0.05 mm 그리드). 무작위 넷 순서로 최대 10회 재시도.

### 남은 일 / 아이디어
- 실제 NiceRF 데모보드 MCU 품번 확인(데모코드 rar 또는 판매처) → 다르면 design.py 의 U3 교체.
- LoRa1280 데이터시트 기구도면으로 풋프린트 패드 치수 재확인.
- 장거리용 LoRa1280F27(31.5×15.8 mm, TXEN/RXEN 필요) 변형은 미설계.
- 펌웨어(듀얼 SX1280 MAVLink 링크)는 미작성. 핀맵은 firmware/board_pins.h.
