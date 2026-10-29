# 로봇 레이더 · Robotics Radar

휴머노이드·피지컬 AI **27개사의 양산·자금·IPO·부품 기회**를 **한국 제조·부품사 경영진**과 **투자(비용 대비 효율)** 관점에서 정리한 대시보드입니다.
https://dkwo284-max.github.io/Robotics_Radar/

| 화면 | 내용 |
|---|---|
| 개요 | 관점 토글(부품사/투자), 경보, KPI, 경영진 인사이트, 오늘의 소식(AI 분류), 검증 대기 수치, 핵심 이벤트, 정책 |
| 지형 | 버블 차트 — 경쟁력(양산×기술×자본) / 고객 매력도(규모×개방성·지정학×지불 능력), 순위와 점수 변화(▲▼) |
| 부품 | 부품 매출 기회 계산기, BOM 구성, 부품별 기존·국내 공급사 지도 |
| 양산 | 출하 점유율, 2026~2030 시나리오, 기업별 양산 현황, 다가오는 마일스톤 |
| 자본 | 관련 상장사 주가, IPO 파이프라인, 출하 1대당 밸류, 밸류에이션, 최근 조달 |
| 전략 | 진입 방식 5가지 비교, 투자 회수 계산기(NPV·회수 시점), 주시할 신호, 국가 경쟁력 레이더, 용도별 집중도, 기술·제품 로드맵 |
| 기업 상세 | 점수와 근거, 핵심 수치(공식/보도/추정 + 출처), 검증 대기, 주가, 최근 소식, 조달 구조, 로드맵, 리스크 |

## 점수

- **경쟁력(100)** = 기술 30 + 양산 30 + 자본 20 + 실행 신뢰도 20 → Tier 1 ≥ 70, Tier 2 ≥ 50, 나머지 Tier 3
- **고객 매력도(100, 하드웨어 기업만)** = 양산 30 + 조달 개방성 25 + 지정학 접근성(한국 부품사 기준) 25 + 지불 능력(자본) 20
- 점수가 바뀐 날마다 `data/history.json` 에 스냅숏을 남겨 점수 변화·Tier 이동을 경보로 보여줍니다.

## 데이터

| 파일 | 누가 바꾸나 | 내용 |
|---|---|---|
| `data/companies.json` | 사람(분기 리서치) | 27개사. 수치는 `{v, as_of, kind, src}` (official 공식 / reported 보도 / estimate 추정), 금액 USD 백만 |
| `data/market.json` | 사람 | 출하 통계, 시나리오, BOM, 정책, 이벤트, 인사이트 |
| `data/strategy.json` | 사람 | 국가 경쟁력, 용도, 기술 로드맵, 신호, 진입 옵션 |
| `config.json` | 사람 | 기업별 뉴스 검색어, 주가 심볼, Gemini 상한 |
| `web/data/news.json` | 봇(매일) | 뉴스 + AI 분류·요약 + 검증 대기 수치 |
| `web/data/prices.json` | 봇(매일) | 관련 상장사 3개월 종가 |
| `web/data/dashboard.json` | 봇 | 화면 데이터 (위 전부 + 점수·경보) |

AI 가 기사에서 뽑은 수치는 **큐레이션 값을 덮어쓰지 않습니다**. 10% 넘게 다르거나 기준값이 없으면 '검증 대기'로만 쌓이고, 사람이 확인해 `data/companies.json` 에 반영합니다.

## 동작 방식

- `.github/workflows/update.yml` 이 매일 UTC 19:10(뉴질랜드 오전) 실행 → `scripts/update.py`
  - **Google 뉴스 RSS**: 기업별 검색어(영어·한국어)로 최근 7일, 기업당 새 기사 3건
  - **Gemini 무료 등급**: 새 기사 최대 40건을 요청 1회로 분류(관련성·유형·중요도)·한국어 요약·수치 추출. 하루 상한 2회(`web/data/ai-usage.json`, 허브와 같은 키를 씀)
  - **Yahoo Finance**: 관련 상장사 11종목 3개월 종가(키 불필요)
  - `scripts/build.py` 가 점수·경보를 계산해 `dashboard.json` 생성 → 커밋 → GitHub Pages 배포
- data·scripts·web 을 푸시하면 수집 없이 빌드·배포만 합니다.

## 처음 설정

1. Settings → Pages → Source 를 **GitHub Actions** 로
2. Settings → Secrets and variables → Actions 에 `GEMINI_API_KEY` (Daily Brief·웨일 레이더와 같은 키 — 무료 한도를 함께 씀). 없으면 제목만 표시
3. Actions → Robotics Radar update → Run workflow

## 로컬 실행

```bash
pip install -r requirements.txt pytest
python -m pytest -q
python scripts/update.py          # 뉴스·주가 수집 + 빌드 (GEMINI_API_KEY 없으면 제목만)
python scripts/build.py           # 빌드만
python -m http.server -d web 8000
```

## 주의

점수·인사이트·국가 평가는 공개 정보를 바탕으로 한 분석이며 투자 권유가 아닙니다. 회사 발표 수치(특히 생산 목표)는 실제와 다를 수 있어 실행 신뢰도 점수로 따로 평가합니다. 뉴스 요약은 RSS 제목·짧은 설명을 근거로 한 AI 추정입니다.
