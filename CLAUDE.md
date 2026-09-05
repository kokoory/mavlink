# CLAUDE.md — 작업 기록 및 안내

이 저장소는 upstream [`mavlink/mavlink`](https://github.com/mavlink/mavlink)의 포크이며,
그 위에 **UAV MAVLink Studio** (`tools/mavstudio/`)를 추가한 것입니다.

---

## 1. 이 저장소에서 가장 중요한 규칙

> **`message_definitions/v1.0/` 의 upstream XML은 절대 수정하지 않는다.**

`common.xml`, `minimal.xml`, `standard.xml`, `ardupilotmega.xml` 등은 읽기 전용입니다.
사용자 정의 메시지는 별도 다이얼렉트(`my_uav.xml`)에 넣고, 표준 메시지를 안 쓸 때는
지우지 말고 프로파일에서 **비활성화**합니다. 그래야 upstream 업데이트가 fast-forward로 끝납니다.

`python3 -m mavstudio upstream` 의 `modified standard files` 는 항상 **0** 이어야 하며,
`validate` 가 0이 아니면 error로 잡습니다.

유일한 예외: `message_definitions/v1.0/my_uav.xml` (우리가 추가한 커스텀 다이얼렉트).

---

## 2. 무엇을 만들었나

`tools/mavstudio/` — MAVLink 메시지 카탈로그 브라우저 + 커스텀 다이얼렉트 편집기 +
UAV 프로파일 관리자 + MOSA 인터페이스 관리자. **5계층 구조**입니다.

```
1  Catalog            message_definitions/v1.0/*.xml  (읽기 전용, 19개 다이얼렉트, 397 메시지)
2  Custom dialect     message_definitions/v1.0/my_uav.xml  (추가만, 삭제는 커스텀만)
3  Capabilities       프로토콜 기능 단위 묶음 (39개). 끄면 소속 메시지가 전부 꺼짐
4  UAV profile        기체 + 형상별로 무엇을 켜고, 몇 Hz로, 어느 방향으로 보낼지
5  Interface contract 모듈 간 계약. 버전(SemVer) + provider/consumer + aspect
```

각 계층은 위 계층을 읽기만 합니다. 프로파일이 카탈로그를 오염시킬 수 없고,
계약이 몰래 메시지를 켤 수 없습니다.

### 프론트엔드 3종 (모두 같은 라이브러리를 호출 → 절대 갈라지지 않음)

| | 실행 | 의존성 |
| --- | --- | --- |
| 데스크톱 (Qt) | `python3 -m mavstudio qt` | PySide6 |
| 브라우저 | `python3 -m mavstudio web` | 없음 (stdlib http.server) |
| 터미널 | `python3 -m mavstudio <cmd>` | 없음 |

---

## 3. 모듈 지도

| 파일 | 역할 |
| --- | --- |
| `model.py` | Message/Field/Enum/EnumEntry/Param 데이터 모델, 타입 크기 |
| `parser.py` | XML 읽기/쓰기. 출력은 `xmllint --format` 과 동일한 포맷 |
| `catalog.py` | 계층 1. 전체 다이얼렉트 파싱, include 그래프, ID 인덱스, 충돌 검사 |
| `capabilities.py` | 계층 3. 39개 기능 정의(glob 기반) + 해석 |
| `project.py` | 프로젝트 설정(다이얼렉트, ID 대역, 기체 목록) |
| `profile.py` | 계층 4. 프로파일 + **해석 엔진**(무엇이 왜 켜졌는지) |
| `customdialect.py` | 계층 2. 커스텀 메시지/enum/command CRUD + 검증 + ID 관리 |
| `mosa.py` | 계층 5. 인터페이스 계약, 모듈 매니페스트, 호환성, SemVer |
| `bandwidth.py` | 텔레메트리 대역폭 예산 계산 |
| `validate.py` | 5계층 교차 검증 |
| `build.py` | 프루닝된 독립 다이얼렉트 XML 생성 + mavgen 호출 |
| `icd.py` | ICD 문서 생성 (Markdown/HTML/CSV) |
| `upstream.py` | upstream 대비 프로젝트 드리프트 비교 |
| `workspace.py` | 5계층을 묶는 파사드 (`open_studio()`) |
| `cli.py` / `web.py` / `qtapp.py` | 프론트엔드 3종 |
| `static/` | 웹 UI (index.html, app.js, style.css — 프레임워크·빌드 없음) |

**새 기능을 추가할 때는 라이브러리 계층에 넣고 3개 프론트엔드에서 호출하세요.**
프론트엔드에 로직을 넣으면 셋이 갈라집니다.

---

## 4. 활성/비활성 해석 우선순위

`profile.resolve()` — 낮은 것부터:

1. capability 기본값 (`capabilities.py` 의 `default`)
2. 프로파일의 capability 토글
3. 프로파일의 개별 메시지 override
4. 강제 규칙 — `required` capability 와 커스텀 메시지는 항상 ON

`MessageState.reason` 에 어느 규칙이 결정했는지 문자열로 남습니다.
`mavstudio show <MSG>` 로 확인 가능. **이 필드를 없애지 마세요** — 상태가 이상할 때 유일한 단서입니다.

---

## 5. 반드시 알아야 할 함정들 (실제로 다 밟았음)

1. **메시지 ID 42000/42001은 `icarous.xml` 이 이미 사용 중**입니다. 50000–52699는
   cubepilot/csAirLink/marsh/stemstudios. 기본 예약 대역은 **52700–52799**.
   `mavstudio ids --check <id>` 로 확인.

2. **XML 주석 안에 `--` 를 쓰면 문서가 깨집니다.** `parser.dialect_xml()` 이
   `--` → `-` 로 치환합니다. 테스트 있음.

3. **`<deprecated>` 는 `replaced_by` 가 비어 있어도 속성이 있어야 합니다.**
   mavschema.xsd 요구사항. upstream도 `replaced_by=""` 로 씁니다.
   빈 속성을 생략하면 mavgen 이 스키마 검증에서 실패합니다. 테스트 있음.

4. **빌드 산출물 파일명은 C 식별자여야 합니다.** mavgen 이 파일명으로 전처리기 매크로를
   만들기 때문에 `my_uav_swan-h200_flight.xml` 은
   `MAVLINK_MY_UAV_SWAN-H200_FLIGHT_XML_HASH` 라는 잘못된 매크로가 됩니다.
   `store.ident()` 사용. 테스트 있음.

5. **pymavlink 설치 형태가 3가지**입니다: 서브모듈(`pymavlink.tools.mavgen`),
   PyPI 휠(`tools` 패키지 없음, `/usr/local/bin/mavgen.py` 스크립트만),
   소스 체크아웃. `build.mavgen_command()` 가 셋 다 처리합니다.
   `importlib.util.find_spec("pymavlink.tools.mavgen")` 은 부모 패키지가 없으면
   `None` 을 반환하는 게 아니라 **예외를 던집니다** — try/except 필수.

6. **argparse `action="append"` 는 default 에 append 합니다.** `--transport` 를
   `default=["mavlink2"]` 로 두면 `mavlink2, mavlink2, rtp` 가 나옵니다.
   `default=None` 후 나중에 채웁니다.

7. **argparse 전역 옵션은 서브커맨드 앞에만 옵니다.** `_SubparsersWithCommon` 이
   `default=argparse.SUPPRESS` 로 모든 서브파서에 `--vehicle/--profile/--project` 를
   붙여서 양쪽 순서 모두 동작하게 합니다.

8. **`<superseded>` 요소를 놓치지 마세요.** upstream이 40곳에서 쓰는 "약한 deprecation"
   마커입니다(예: `SMART_BATTERY_INFO` → `BATTERY_INFO`). 모델·파서·검증에 반영되어 있고
   round-trip 테스트가 있습니다. **단, 빌드 산출물에서는 제거합니다** —
   구버전 `mavschema.xsd`(예: PyPI pymavlink 2.4.49)가 이 요소를 거부해서 mavgen이
   실패하기 때문입니다. 문서 가치는 ICD가 카탈로그에서 직접 읽어 유지합니다.
   `build._without_superseded()` / `_strip_enum_superseded()`.

9. **PyPI pymavlink 휠의 스키마가 이 저장소의 `common.xml` 보다 오래되었습니다.**
   손대지 않은 upstream `common.xml` 에 대해서도 41개 스키마 에러가 납니다.
   CI는 리포지토리와 동기화된 서브모듈을 쓰므로 문제없습니다.
   pip 휠로 테스트할 때 이 에러가 보이면 **우리 코드 문제가 아닙니다.**

10. **upstream에는 원래 ID 충돌이 있습니다** (paparazzi 180–184 ↔ ardupilotmega 180–184).
   같이 쓰이지 않는 다이얼렉트라 문제없음. 그래서 `catalog.conflicts()` (전역)와
   `catalog.conflicts_in(closure)` (실제 오류)를 구분합니다. 검사는 후자를 쓰세요.

---

## 6. MOSA / K-MOSA 관련 설계 근거

- MAVLink 메시지 = 데이터 패킷. **인터페이스 계약 = 모듈 간 약속**. 이 둘을 분리했습니다.
- **Transport-neutral**: 계약이 `dds:TargetTrack`, `uci:TargetStatus` 처럼 다른
  데이터 모델의 이름을 참조할 수 있습니다. `mavlink:` 접두사(또는 무접두사)만 카탈로그로
  검증하고, 나머지는 **unverified 로 보고**합니다 — 조용히 통과시키지 않습니다.
  `mosa.split_ref()` / `mavlink_refs()` / `external_refs()`.
- **Aspect**: 호환성은 메시지만의 문제가 아닙니다. 계약이 `mechanical`, `power`,
  `network`, `video`, `timing` 등을 선언하고 모듈이 충족 여부를 선언합니다.
  이것이 "메시지는 맞는데 못 끼움" 을 잡아내고 **교체 호환성 %** 를 만듭니다.
- **SemVer 의미**: major 는 breaking interface change. 따라서 1.5.0 은 2.0.0 요구를
  만족하지 않고 그 반대도 아닙니다 (`mosa.satisfies()`).
- **K-MOSA 규격 조항은 하드코딩하지 않았습니다.** 아직 표준·인증 체계가 구축 중이라,
  어떤 modular open-systems 접근에도 필요한 구조(명명된 인터페이스, 버전, provider/consumer,
  매니페스트, conformance 검사, 문서 생성)만 구현했습니다. 실제 요구 조항이 확보되면
  `mosa.py` 와 `validate.py` 에 추가하면 됩니다.

### 미국 MOSA 지형 (사용자와 합의된 정리)

FACE / SOSA / OMS / UCI / UCS 는 **일렬 계층이 아니라 서로 다른 문제**를 풉니다.
FACE=항공 SW 이식성, SOSA=센서·처리 HW 모듈화, OMS=미션 시스템 서비스 인터페이스,
UCI=machine-to-machine 미션 레벨 C2 메시지 셋, UCS(SAE AS6512)=무인체계 통제 세그먼트 아키텍처.
MAVLink 는 **vehicle/autopilot 레벨 C2** 이고 UCI 가 다루는 mission-level C2 보다 아래입니다.
`transport` 와 데이터 모델 필드는 계약이 이 계층들을 가로지를 수 있게 하려고 존재합니다.

> ⚠️ 세션 주의: UCS AS6512/AS6518 의 개별 조항, K-MOSA 규격서 세부 내용은
> 이 세션에서 원문으로 확인하지 못했습니다. QGC/PX4 기능을 UCS Service/Interface 에
> 1:1 대응시키는 작업은 **실제 표준 문서가 있어야** 신뢰성 있게 할 수 있습니다.
> 문서 없이 매핑표를 만들어 커밋하지 마세요.

---

## 7. 개발 워크플로

```bash
export PYTHONPATH=tools

# 테스트 (46개)
PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v

# 린트 (저장소 설정: ruff.toml, E4/E7/E9/F/UP03x)
ruff check tools/

# XML 포맷 검사 (CI가 message_definitions 전체에 대해 실행)
./scripts/format_xml.sh -c

# 전체 파이프라인 확인
python3 -m mavstudio validate
python3 -m mavstudio build --lang C --generated /tmp/gen_c
```

`my_uav.xml` 은 `message_definitions/` 안에 있으므로 CI 의 `format_xml.sh -c` 와
`xml_consistency_check.py`, 그리고 `test.sh py` 의 전 언어 mavgen 대상이 됩니다.
`parser.write_xml()` 이 xmllint 로 정규화하므로 포맷 검사는 통과합니다.

---

## 8. 검증된 것 / 안 된 것

**검증됨 (이 세션에서 실제로 실행)**
- 19개 다이얼렉트 397 메시지 파싱, include 그래프 해석, `<superseded>` round-trip
- 표준 235개 메시지 전부가 capability 로 분류됨 (미분류 0)
- 프로파일 해석: 기본 130 enabled / 269 disabled
- 커스텀 메시지 2개 + enum 1개 + command 1개 추가 → `my_uav.xml`
- 프루닝 빌드 → mavgen **C** → gcc 컴파일 → 실행: msgid 52700, wire 45 bytes
  (대역폭 계산기 예측과 정확히 일치)
- mavgen **Python** → import → pack 성공, 끈 기능(FTP)이 실제로 빠져 있음 확인
- ICD Markdown/HTML/CSV 생성
- 웹 UI: 전 엔드포인트 + 가드레일(표준 메시지 삭제 거부, required capability 끄기 거부,
  ID 충돌 탐지) — Playwright 로 콘솔 에러 0 확인
- Qt UI: 8개 섹션 렌더링, 폼 라이브 검증, 인스펙터, 필터 — offscreen 스모크 테스트
- 단위 테스트 **46개** 통과, ruff clean, `./scripts/format_xml.sh -c` 통과

**안 된 것 / 남은 것**
- `mavstudio profile add` (새 프로파일 CLI 생성) 없음 — `init --profiles` 로만 만듦
- 웹/Qt UI 에서 인터페이스·모듈 **생성/편집** 불가 (조회만). 생성은 CLI 전용
- Message Graph (메시지 경로 시각화) 미구현
- GCS Capability Discovery 미구현 (실기체 연결 기능 자체가 없음)
- PX4/QGC 소스 스캔해서 "실제 사용중/정의만 존재" 표시 미구현
- Conformance test 자동 실행(실제 링크에서 트래픽 검증) 미구현 — 현재는 정적 검사만

---

## 9. 예제 프로젝트 (`uav/`)

커밋된 예제는 실제로 동작하는 상태입니다 (`validate` → 0 errors).

- 기체 `SWAN-H200`, 프로파일 `flight` / `development`
- 커스텀 메시지 `UAV_MOTOR_VIBRATION`(52700), `UAV_MOTOR_STATUS`(52701)
- 커스텀 enum `UAV_MOTOR`, 커스텀 명령 `MAV_CMD_UAV_MOTOR_TEST`(52700)
- 인터페이스 `PROPULSION.MONITORING` 1.2.0, `CORE.TIMEBASE` 1.0.0,
  `PAYLOAD.EOIR` 2.0.0 (dds/uci 참조 포함 — transport-neutral 데모)
- 모듈 `Flight Controller`, `Motor Controller Module`,
  `XYZ ESC v4`(candidate — `swap` 데모용, 25% 호환)

`python3 -m mavstudio swap "Motor Controller Module" "XYZ ESC v4"` 로 교체 검증 데모.

---

## 10. 사용자 선호

- 답변은 **한국어**, Extended Thinking 으로 신중하게.
- **다른 세션이 이어받을 수 있도록 이 CLAUDE.md 를 항상 갱신할 것.**
- 작업 브랜치: `claude/mavlink-message-manager-57huxs`
