# 로봇 레이더 · Robotics Radar

휴머노이드·피지컬 AI **27개사의 양산·자금·IPO·부품 기회**를 **한국 제조·부품사 경영진**과 **투자(비용 대비 효율)** 관점에서 정리한 대시보드입니다.
https://dkwo284-max.github.io/Robotics_Radar/

| 화면 | 내용 |
|---|---|
| 개요 | 관점 토글(부품사/투자), KPI 4개, 경영진 인사이트(근거 기업·신뢰도·권고), 최근 변화, 정책 동향 |
| 지형 | 버블 차트 두 가지 — 경쟁력(양산×기술×자본)과 고객 매력도(규모×개방성·지정학×지불 능력), 순위 |
| 부품 | 부품 매출 기회 계산기(시나리오·수량·단가 하락·점유율·중국 외 시장), BOM 구성, 부품별 기존·국내 공급사 지도 |
| 양산 | 출하 점유율, 2026~2030 출하 시나리오, 기업별 누적 출하·목표·캐파·실행 신뢰도, 다가오는 마일스톤 |
| 자본 | IPO 파이프라인, 출하 1대당 밸류, 밸류에이션, 최근 12개월 조달 |
| 기업 상세 | 점수와 근거, 핵심 수치(공식/보도/추정 + 출처), 조달 구조, 고객·파트너, 로드맵, 리스크 |

## 점수

- **경쟁력(100)** = 기술 30 + 양산 30 + 자본 20 + 실행 신뢰도 20 → Tier 1 ≥ 70, Tier 2 ≥ 50, 나머지 Tier 3
- **고객 매력도(100, 하드웨어 기업만)** = 양산 30 + 조달 개방성 25 + 지정학 접근성(한국 부품사 기준) 25 + 지불 능력(자본) 20
- 점수마다 근거 한 줄을 `data/companies.json` 에 적습니다. 계산은 `scripts/build.py` 가 합니다.

## 데이터

- `data/companies.json` — 27개사. 수치는 `{v, as_of, kind, src}` (kind: official 공식 / reported 보도 / estimate 추정), 금액은 USD 백만
- `data/market.json` — 출하 통계, 2026~2030 시나리오(Bear/Base/Bull + 중국 외 비중), 부품 BOM, 정책, 이벤트, 인사이트
- 분기마다 웹 리서치로 갱신합니다. 출처끼리 다르면 note 에 범위를 적고 보수적인 값을 씁니다.

## 동작 방식

`main` 에 data·scripts·web 이 바뀌어 푸시되면 `.github/workflows/update.yml` 이 테스트 → 검증(`--check`) → 빌드 → GitHub Pages 배포를 합니다.
`web/data/dashboard.json`(화면 데이터)과 `web/data/ai-usage.json`(허브가 읽는 AI 사용량, 상한 2회)은 배포 산출물에만 들어갑니다.

## 처음 설정

1. GitHub 에 `Robotics_Radar` 저장소를 만들고 푸시
2. Settings → Pages → Source 를 **GitHub Actions** 로
3. Actions → Robotics Radar build → Run workflow

## 로컬 실행

```bash
pip install pytest
python -m pytest -q
python scripts/build.py
python -m http.server -d web 8000
```

## 다음 단계 (Phase 2·3)

- Phase 2: 기업별 뉴스(Google 뉴스 RSS)·공시(SEC·DART·HKEX)·주가 자동 수집, Gemini 하루 2회 이내로 이벤트 분류·추출, 큐레이션 값과 다르면 "검증 대기"로 표시
- Phase 3: 국가 경쟁력, 용도 분석, 기술·제품 로드맵, 의사결정 룸(진입 옵션 NPV·회수기간)

## 주의

점수·인사이트는 공개 정보를 바탕으로 한 분석이며 투자 권유가 아닙니다. 회사 발표 수치(특히 생산 목표)는 실제와 다를 수 있어 실행 신뢰도 점수로 따로 평가합니다.
