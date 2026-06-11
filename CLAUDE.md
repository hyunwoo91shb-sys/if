# CLAUDE.md — ETF vs 정기예금 비교 상담 도구

## 프로젝트 개요

### 목적
"그때 ETF를 했다면 지금 수익률은 얼마였을까?"

정기예금 가입 고객에게 ETF 포트폴리오 투자 시 예상 성과를 과거 데이터 기반으로 비교·시각화하는
**자산관리 전문 은행원용 Streamlit 상담 도구**입니다.

은행원이 고객 정보(가입일, 원금, 금리)를 입력하면 안정형/균형형/성장형 3가지 ETF 포트폴리오
시나리오의 현재 평가액과 누적 수익률을 즉시 계산하여 은행 제안서 수준으로 시각화합니다.

### 대상 사용자
- 시중은행 PB(Private Banker) 및 자산관리 상담원
- 고객 동석 상담 중 PC 또는 태블릿으로 즉시 사용

---

## 핵심 기능 목록

1. **고객 정보 입력 폼** — 고객명, 정기예금 가입일(date picker), 투자 원금(만원), 당시 연이율(%)
2. **정기예금 수익 계산** — 세전 이자, 세후 이자(이자소득세 15.4% 차감), 세후 총액, 세후 수익률
3. **ETF 포트폴리오 시나리오 비교** — 안정형/균형형/성장형 3개 시나리오 카드 (현재 평가액, 수익률, 정기예금 대비 차이)
4. **Plotly 누적 수익률 시계열 차트** — 정기예금 vs 3개 시나리오 인터랙티브 비교 그래프
5. **포트폴리오 구성 명세** — 시나리오별 ETF 목록, 비중, 매수가, 현재가, 개별 수익률 (expander)
6. **면책 고지문** — 화면 하단 항상 표시
7. **로딩 스피너** — yfinance 데이터 수집 중 진행 상태 표시

---

## 기술 스택

| 구분 | 라이브러리 | 용도 |
|---|---|---|
| UI 프레임워크 | `streamlit` | 앱 인터페이스 전체 |
| 데이터 수집 | `yfinance` | ETF 일별 종가 데이터 (Yahoo Finance API) |
| 시각화 | `plotly` | 인터랙티브 시계열 차트 |
| 데이터 처리 | `pandas`, `numpy` | 수익률 계산, 시계열 처리 |
| 기본 라이브러리 | `datetime`, `warnings` | 날짜 처리, 경고 억제 |

설치 명령:
```
pip install streamlit yfinance plotly pandas numpy
```

---

## 파일 구조

```
다면/
├── app.py                   # Streamlit 앱 메인 진입점
├── etf_vs_deposit.ipynb     # 핵심 계산 로직 프로토타입 노트북 (완성됨, 참고용)
├── CLAUDE.md                # 본 문서
└── requirements.txt         # (선택) pip 의존성 목록
```

### 권장 모듈 분리 구조 (리팩토링 시)

```
다면/
├── app.py                   # Streamlit UI 레이어만 담당
├── calculator.py            # 수익률 계산 함수 모음 (노트북에서 이전)
├── data_fetcher.py          # yfinance 데이터 수집 함수 (캐싱 포함)
├── config.py                # ETF_POOL, SCENARIOS 상수 정의
└── etf_vs_deposit.ipynb     # 원본 프로토타입 (참고용 유지)
```

---

## 주요 함수 및 모듈 설명

### 수익률 계산 함수 (노트북 → app.py 이전)

#### `calc_deposit_return(principal, annual_rate, start_date, end_date)`
정기예금 단리 수익을 계산합니다.
- `annual_rate`: 연이율 (예: `3.5` → 3.5%)
- 이자소득세 15.4%를 자동 차감하여 세후 수익 계산
- 반환값: `{'원금', '이자', '세후이자', '세후총액', '수익률(%)', '세후수익률(%)', '보유일수'}`

#### `calc_etf_return(symbol, principal, start_date, end_date)`
단일 ETF 투자 수익을 계산합니다.
- `symbol`: Yahoo Finance 종목 코드 (예: `'069500.KS'`)
- 매수가는 `get_price_on_date()`, 현재가는 `get_current_price()`로 조회
- 반환값: `{'매수가', '현재가', '매수좌수', '현재평가액', '손익', '수익률(%)'}`

#### `calc_portfolio_return(weights, principal, start_date, end_date)`
포트폴리오 수익을 계산합니다.
- `weights`: `{'ETF명': 비중(0~1), ...}` — 합계가 1이 아니면 자동 정규화
- 반환값: `{'상세': DataFrame, '총평가액', '총손익', '총수익률(%)'}`

### 데이터 수집 함수

#### `get_price_on_date(symbol, target_date)`
특정 날짜 종가를 반환합니다.
- 해당일이 휴장일이면 최대 7일 앞까지 탐색하여 가장 가까운 거래일 종가 반환
- 반환값: `float | None`

#### `get_price_series(symbol, start, end)`
기간별 종가 시계열을 반환합니다.
- 반환값: `pd.Series` (인덱스: 날짜, 값: 종가)
- MultiIndex 반환 시 `iloc[:, 0]`으로 자동 처리

#### `get_current_price(symbol)`
최근 5거래일 중 가장 마지막 종가를 반환합니다.

### Streamlit UI 구조 (app.py)

```python
# 사이드바: 고객 정보 입력
with st.sidebar:
    고객명, 가입일, 원금, 연이율 입력 폼
    [조회] 버튼

# 메인 영역
if 조회 버튼 클릭:
    # 1. 정기예금 수익 요약 섹션
    st.metric() 또는 st.table()로 세후 수익 표시

    # 2. ETF 시나리오 비교 카드 (3열)
    col1, col2, col3 = st.columns(3)
    각 col에 시나리오 카드 표시

    # 3. 누적 수익률 Plotly 차트
    st.plotly_chart()

    # 4. 포트폴리오 구성 상세 (expander)
    with st.expander():
        st.dataframe()

# 하단 고정: 면책 고지문
st.caption("본 자료는 과거 데이터 기반 시뮬레이션...")
```

---

## ETF 풀 (ETF_POOL) 및 시나리오 (SCENARIOS)

### 현재 정의된 ETF 풀

| 카테고리 | ETF명 | 심볼 |
|---|---|---|
| 국내주식 | KODEX 200 | 069500.KS |
| 국내주식 | TIGER 200 | 102110.KS |
| 국내주식 | KODEX 코스닥150 | 229200.KQ |
| 국내주식 | TIGER 코스닥150 | 232080.KQ |
| 국내주식 | KODEX 삼성그룹 | 091160.KS |
| 국내주식 | TIGER 2차전지테마 | 305720.KS |
| 국내주식 | KODEX 반도체 | 091230.KS |
| 해외주식 | TIGER 미국S&P500 | 360750.KS |
| 해외주식 | TIGER 미국나스닥100 | 133690.KS |
| 해외주식 | KODEX 미국S&P500TR | 379800.KS |
| 해외주식 | TIGER 차이나CSI300 | 192090.KS |
| 채권 | KODEX 국채3년 | 114820.KS |
| 채권 | TIGER 국채3년 | 114260.KS |
| 채권 | KOSEF 국고채10년 | 148070.KS |
| 채권 | KODEX 단기채권 | 153130.KS |
| 원자재·대안 | KODEX 골드선물(H) | 132030.KS |
| 원자재·대안 | TIGER 원유선물Enhanced(H) | 261220.KS |

### 시나리오 구성 비중

| 시나리오 | KODEX 200 | TIGER 미국S&P500 | KODEX 국채3년 | KODEX 골드선물(H) | TIGER 미국나스닥100 |
|---|---|---|---|---|---|
| 안정형 | 20% | 20% | 40% | 20% | — |
| 균형형 | 30% | 30% | 30% | 10% | — |
| 성장형 | 30% | 40% | 10% | — | 20% |

---

## 개발 지침

### 코드 스타일

- 함수명: `snake_case` (기존 노트북 함수명 유지)
- 상수: `UPPER_SNAKE_CASE` (ETF_POOL, SCENARIOS 등)
- 숫자 포맷: 금액은 `f"{value:,}원"`, 수익률은 `f"{value:.2f}%"`
- 오류 처리: yfinance 데이터 취득 실패 시 `None` 반환 후 UI에서 오류 카드 표시 (앱 전체 중단 방지)
- 타입 힌트: 함수 시그니처에 타입 힌트 작성 권장

### yfinance 캐싱 전략

Streamlit 재실행마다 불필요한 API 호출이 발생하지 않도록 캐시 데코레이터를 반드시 적용합니다.

```python
@st.cache_data(ttl=3600)   # 1시간 캐시
def get_price_series(symbol: str, start: str, end: str) -> pd.Series:
    ...

@st.cache_data(ttl=3600)
def get_price_on_date(symbol: str, target_date: str) -> float | None:
    ...
```

- `ttl=3600`: 장중 갱신 주기를 1시간으로 설정. 장 마감 후 재조회 시 캐시 무효화 불필요
- `get_current_price()`는 캐시 적용 금지 (항상 최신 현재가 필요)

### 한글 폰트 처리

Streamlit의 HTML/CSS 기반 렌더링은 별도 폰트 설정 없이 한글을 표시합니다.

Plotly 차트 내 한글 레이블이 깨질 경우 아래와 같이 처리합니다:

```python
import plotly.graph_objects as go

fig.update_layout(
    font=dict(family="Malgun Gothic, Apple Gothic, NanumGothic, sans-serif")
)
```

matplotlib은 본 앱에서 사용하지 않습니다. 노트북의 matplotlib 시각화는 Plotly로 대체합니다.

### MultiIndex 대응 (yfinance)

yfinance 최신 버전은 단일 심볼 조회 시에도 MultiIndex DataFrame을 반환할 수 있습니다.
아래 패턴으로 일관성 있게 처리합니다:

```python
close = df['Close']
if isinstance(close, pd.DataFrame):
    close = close.iloc[:, 0]  # 첫 번째 컬럼 추출
```

스칼라 값 추출 시:

```python
value = df['Close'].iloc[0]
if hasattr(value, 'values'):
    value = float(value.values[0])
else:
    value = float(value)
```

---

## 실행 방법

```bash
streamlit run app.py
```

기본 접속 URL: http://localhost:8501

로컬 네트워크 공유 시 (태블릿 등):

```bash
streamlit run app.py --server.address 0.0.0.0
```

---

## 주의사항

### 1. 한국 ETF 심볼 규칙

| 거래소 | 접미사 | 예시 |
|---|---|---|
| KRX (유가증권시장) | `.KS` | `069500.KS` (KODEX 200) |
| KOSDAQ | `.KQ` | `229200.KQ` (KODEX 코스닥150) |

심볼 오입력 시 yfinance가 빈 DataFrame을 반환합니다. `get_price_on_date()`에서 `None`을 반환하면
해당 ETF를 포트폴리오 계산에서 제외하고 경고 메시지를 출력합니다.

### 2. 이자소득세 15.4%

정기예금 이자에 적용되는 세율입니다.
- 세후 이자 = 세전 이자 × (1 - 0.154)
- 세후 이자 = 세전 이자 × **0.846**
- 코드 내 하드코딩 값: `interest * 0.846`
- 세금 비과세 상품(ISA 등)은 별도 처리 필요 (현재 미구현)

### 3. 휴장일 및 주말 처리

`get_price_on_date()`는 입력 날짜부터 최대 7일 이후까지 탐색하여 첫 번째 유효 거래일 종가를 반환합니다.
연휴가 7일을 초과하는 경우(설 연휴 등) 탐색 범위를 늘려야 합니다.

```python
end = start + pd.Timedelta(days=10)  # 설 연휴 등 장기 휴장 대비
```

### 4. yfinance 데이터 가용성

- 상장 전 날짜 입력 시 빈 DataFrame 반환 → `None` 처리
- 특정 ETF는 Yahoo Finance에서 데이터 제공이 불규칙할 수 있음 (TIGER 원유선물Enhanced 등)
- 네트워크 오류 시 `yf.download()`가 예외를 발생시킬 수 있으므로 `try-except` 처리 권장

### 5. 시계열 차트 수익률 계산 방식

Plotly 시계열 차트에서 포트폴리오 누적 수익률은 아래 방식으로 계산합니다:
1. 각 ETF의 가입일 대비 누적 수익률 시계열을 구한다 (`price / price.iloc[0] - 1`)
2. 비중(weight)을 곱하여 포트폴리오 기여 수익률로 변환한다
3. 전 종목 합산하여 포트폴리오 전체 누적 수익률을 산출한다

이 방식은 일별 리밸런싱 없이 초기 비중 고정을 가정합니다.

### 6. 면책 고지문

아래 문구를 화면 하단에 항상 표시해야 합니다:

> 본 자료는 과거 데이터 기반 시뮬레이션이며, 미래 수익을 보장하지 않습니다.
> 투자는 원금 손실의 위험이 있으며, 투자 결정에 대한 책임은 투자자 본인에게 있습니다.

---

## 변경 이력

| 버전 | 날짜 | 내용 |
|---|---|---|
| v1.0 | 2026-06-11 | 최초 작성 (PRD 기반 CLAUDE.md 생성) |
