"""
ETF vs 정기예금 수익률 비교 시뮬레이터
자산관리 은행원용 Streamlit 앱
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

# SSL 인증서 검증 우회 (기업 네트워크/보안 프록시 환경 대응)
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# yfinance curl_cffi 세션 SSL 우회 패치
import yfinance._http as _yf_http
from yfinance._http import _backend, HAS_CURL_CFFI
import sys as _sys

def _patched_new_session():
    if HAS_CURL_CFFI:
        return _backend.Session(impersonate="chrome", verify=False)
    s = _backend.Session()
    s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    return s

_yf_http.new_session = _patched_new_session
for _mod_name, _mod in _sys.modules.items():
    if "yfinance" in _mod_name and hasattr(_mod, "new_session"):
        setattr(_mod, "new_session", _patched_new_session)

import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

# ─────────────────────────────────────────────
# 페이지 설정 (반드시 첫 번째 st 호출)
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="ETF vs 정기예금 시뮬레이터",
    page_icon="📊",
    layout="wide",
)

# ─────────────────────────────────────────────
# ETF 풀 정의
# ─────────────────────────────────────────────
ETF_POOL = {
    "국내주식": {
        "KODEX 200":         "069500.KS",
        "TIGER 200":         "102110.KS",
        "KODEX 코스닥150":    "229200.KQ",
        "TIGER 코스닥150":    "232080.KQ",
        "KODEX 삼성그룹":     "091160.KS",
        "TIGER 2차전지테마":  "305720.KS",
        "KODEX 반도체":       "091230.KS",
    },
    "해외주식": {
        "TIGER 미국S&P500":   "360750.KS",
        "TIGER 미국나스닥100": "133690.KS",
        "KODEX 미국S&P500TR": "379800.KS",
        "TIGER 차이나CSI300": "192090.KS",
    },
    "채권": {
        "KODEX 국채3년":    "114820.KS",
        "TIGER 국채3년":    "114260.KS",
        "KOSEF 국고채10년":  "148070.KS",
        "KODEX 단기채권":   "153130.KS",
    },
    "원자재·대안": {
        "KODEX 골드선물(H)":          "132030.KS",
        "TIGER 원유선물Enhanced(H)":  "261220.KS",
    },
}
ETF_FLAT = {name: sym for cat in ETF_POOL.values() for name, sym in cat.items()}

# ─────────────────────────────────────────────
# 포트폴리오 시나리오
# ─────────────────────────────────────────────
SCENARIOS = {
    "안정형": {
        "KODEX 200":         0.2,
        "TIGER 미국S&P500":   0.2,
        "KODEX 국채3년":      0.4,
        "KODEX 골드선물(H)":  0.2,
    },
    "균형형": {
        "KODEX 200":         0.3,
        "TIGER 미국S&P500":   0.3,
        "KODEX 국채3년":      0.3,
        "KODEX 골드선물(H)":  0.1,
    },
    "성장형": {
        "KODEX 200":          0.3,
        "TIGER 미국S&P500":    0.4,
        "TIGER 미국나스닥100": 0.2,
        "KODEX 국채3년":       0.1,
    },
}

SCENARIO_COLORS = {"안정형": "#3B82F6", "균형형": "#10B981", "성장형": "#EF4444"}

# ─────────────────────────────────────────────
# 데이터 / 계산 함수
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_price_on_date(symbol: str, target_date: str):
    start = pd.Timestamp(target_date)
    end = start + pd.Timedelta(days=10)
    df = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=False,
    )
    if df.empty:
        return None
    close = df["Close"].iloc[0]
    if hasattr(close, "values"):
        close = close.values[0]
    return float(close)


@st.cache_data(ttl=3600, show_spinner=False)
def get_price_series(symbol: str, start: str, end: str = None) -> pd.Series:
    if end is None:
        end = datetime.today().strftime("%Y-%m-%d")
    df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=False)
    if df.empty:
        return pd.Series(dtype=float)
    close = df["Close"]
    try:
        close = close.iloc[:, 0]
    except Exception:
        pass
    close.index = pd.to_datetime(close.index.date)
    close.index.name = "날짜"
    close.name = symbol
    return close


@st.cache_data(ttl=3600, show_spinner=False)
def get_current_price(symbol: str):
    df = yf.download(symbol, period="5d", progress=False, auto_adjust=False)
    if df.empty:
        return None
    close = df["Close"].iloc[-1]
    if hasattr(close, "values"):
        close = close.values[0]
    return float(close)


def calc_deposit_return(
    principal: float, annual_rate: float, start_date: str, end_date: str = None
) -> dict:
    if end_date is None:
        end_date = datetime.today().strftime("%Y-%m-%d")
    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    if principal <= 0 or days <= 0:
        return {
            "원금": principal, "이자": 0, "세후이자": 0,
            "세후총액": round(principal), "수익률(%)": 0.0,
            "세후수익률(%)": 0.0, "보유일수": max(days, 0),
        }
    interest = principal * (annual_rate / 100) * (days / 365)
    return {
        "원금": principal,
        "이자": round(interest),
        "세후이자": round(interest * 0.846),
        "세후총액": round(principal + interest * 0.846),
        "수익률(%)": round(interest / principal * 100, 2),
        "세후수익률(%)": round(interest * 0.846 / principal * 100, 2),
        "보유일수": days,
    }


def calc_etf_return(
    symbol: str, principal: float, start_date: str, end_date: str = None
) -> dict:
    if end_date is None:
        end_date = datetime.today().strftime("%Y-%m-%d")
    buy_price = get_price_on_date(symbol, start_date)
    sell_price = get_current_price(symbol)
    if buy_price is None or sell_price is None or buy_price == 0:
        return {"오류": f"{symbol} 가격 데이터 없음"}
    units = principal / buy_price
    curr_value = units * sell_price
    profit = curr_value - principal
    ret_pct = profit / principal * 100
    return {
        "매수가": round(buy_price, 0),
        "현재가": round(sell_price, 0),
        "매수좌수": round(units, 4),
        "현재평가액": round(curr_value),
        "손익": round(profit),
        "수익률(%)": round(ret_pct, 2),
    }


def calc_portfolio_return(
    weights: dict, principal: float, start_date: str, end_date: str = None
) -> dict:
    if end_date is None:
        end_date = datetime.today().strftime("%Y-%m-%d")
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 0.001:
        weights = {k: v / total_weight for k, v in weights.items()}
    results = []
    for name, weight in weights.items():
        symbol = ETF_FLAT.get(name)
        if symbol is None:
            continue
        alloc = principal * weight
        r = calc_etf_return(symbol, alloc, start_date, end_date)
        if "오류" in r:
            continue
        r.update({
            "종목명": name, "심볼": symbol,
            "배분금액": round(alloc), "비중": f"{weight * 100:.0f}%",
        })
        results.append(r)
    if not results:
        return {"오류": "계산 가능한 ETF 없음"}
    df = pd.DataFrame(results).set_index("종목명")
    total_value = df["현재평가액"].sum()
    total_profit = df["손익"].sum()
    total_ret = (total_profit / principal * 100) if principal > 0 else 0.0
    return {
        "상세": df,
        "총평가액": round(total_value),
        "총손익": round(total_profit),
        "총수익률(%)": round(total_ret, 2),
    }


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────

def fmt_krw(value: float) -> str:
    return f"₩{int(value):,}"


def build_detail_df(detail_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["비중", "배분금액", "매수가", "현재가", "현재평가액", "손익", "수익률(%)"]
    available = [c for c in cols if c in detail_df.columns]
    df = detail_df[available].copy()
    for col in ["배분금액", "현재평가액", "손익"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: fmt_krw(x))
    for col in ["매수가", "현재가"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: f"{int(x):,}원")
    return df


# ─────────────────────────────────────────────
# CSS — 외부 리소스 없는 단순 스타일
# ─────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* 앱 배경 */
    .stApp { background-color: #F0F4FA; }

    /* 사이드바 배경 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0D1B2A 0%, #1B3A6B 100%);
    }
    /* 사이드바 일반 텍스트 */
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] div,
    section[data-testid="stSidebar"] label {
        color: #D0DCF4 !important;
    }
    /* 사이드바 헤더 */
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #D4AF37 !important;
    }
    /* 사이드바 입력 필드 */
    section[data-testid="stSidebar"] input {
        background-color: rgba(255,255,255,0.12) !important;
        color: #F0F4FF !important;
        border: 1px solid rgba(212,175,55,0.45) !important;
        border-radius: 6px !important;
    }
    /* 사이드바 버튼 */
    section[data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #D4AF37 0%, #C49A20 100%) !important;
        color: #0D1B2A !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 6px !important;
    }
    /* 사이드바 caption */
    section[data-testid="stSidebar"] .stCaptionContainer,
    section[data-testid="stSidebar"] small {
        color: #7A9CC8 !important;
    }
    /* 탭 하단 선 */
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 2px solid #D4AF37;
        background-color: white;
        border-radius: 8px 8px 0 0;
    }
    .stTabs [aria-selected="true"] {
        color: #1B3A6B !important;
        border-bottom: 3px solid #D4AF37 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# 앱 헤더
# ─────────────────────────────────────────────
today_str = datetime.today().strftime("%Y년 %m월 %d일")
st.markdown(
    f'<div style="background:linear-gradient(135deg,#0D1B2A,#1B3A6B);'
    f'color:white;padding:24px 32px;border-radius:12px;margin-bottom:20px;">'
    f'<div style="font-size:0.7rem;letter-spacing:0.2em;color:#D4AF37;'
    f'text-transform:uppercase;margin-bottom:6px;">'
    f'Private Wealth Management · {today_str}</div>'
    f'<div style="font-size:1.75rem;font-weight:800;line-height:1.2;">'
    f'ETF 포트폴리오 vs 정기예금 수익률 비교</div>'
    f'<div style="font-size:0.88rem;color:#8AADDB;margin-top:6px;">'
    f'과거 시장 데이터 기반 시뮬레이션 제안서</div>'
    f'</div>',
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# 사이드바: 고객 정보 입력
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 고객 정보")
    customer_name = st.text_input("고객명 (선택)", placeholder="예: 홍길동")

    st.markdown("### 정기예금 조건")
    max_date = date.today() - timedelta(days=30)
    min_date = date(2015, 1, 1)
    default_date = date.today() - timedelta(days=365 * 2)

    deposit_date = st.date_input(
        "가입일",
        value=default_date,
        min_value=min_date,
        max_value=max_date,
        help="비교 시작 기준일 (최소 30일 이전)",
    )

    principal_man = st.number_input(
        "원금 (만원)",
        min_value=100,
        max_value=1_000_000,
        value=1_000,
        step=100,
    )
    principal = principal_man * 10_000

    annual_rate = st.number_input(
        "연이율 (%)",
        min_value=0.1,
        max_value=20.0,
        value=3.5,
        step=0.1,
        format="%.1f",
    )

    st.divider()
    run_btn = st.button("비교 분석 시작", type="primary", use_container_width=True)
    st.caption("본 자료는 참고용 시뮬레이션입니다. 과거 수익이 미래를 보장하지 않습니다.")


# ─────────────────────────────────────────────
# Session state — 탭 이동 시에도 결과 유지
# ─────────────────────────────────────────────
if "computed" not in st.session_state:
    st.session_state.computed = False
    st.session_state.dep = {}
    st.session_state.scenario_results = {}
    st.session_state.start_date_str = ""
    st.session_state.s_principal = 0
    st.session_state.s_annual_rate = 0.0
    st.session_state.s_customer = ""

if run_btn:
    _start = deposit_date.strftime("%Y-%m-%d")
    with st.spinner("ETF 시장 데이터를 조회하는 중..."):
        _dep = calc_deposit_return(principal, annual_rate, _start)
        _scenario_results: dict = {}
        for sname, weights in SCENARIOS.items():
            result = calc_portfolio_return(weights, principal, _start)
            if "오류" not in result:
                _scenario_results[sname] = result

    st.session_state.computed = True
    st.session_state.dep = _dep
    st.session_state.scenario_results = _scenario_results
    st.session_state.start_date_str = _start
    st.session_state.s_principal = principal
    st.session_state.s_annual_rate = annual_rate
    st.session_state.s_customer = customer_name

# 세션에서 읽기
computed = st.session_state.computed
dep = st.session_state.dep
scenario_results = st.session_state.scenario_results
start_date_str = st.session_state.start_date_str
s_principal = st.session_state.s_principal
s_annual_rate = st.session_state.s_annual_rate
s_customer = st.session_state.s_customer


# ─────────────────────────────────────────────
# 탭 구성
# ─────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(
    ["📊 수익 비교 시뮬레이터", "📈 누적 수익률 차트", "💼 사용자 정의 포트폴리오"]
)


# ═══════════════════════════════════════════════════════════
# Tab 1: 수익 비교 시뮬레이터
# ═══════════════════════════════════════════════════════════
with tab1:
    if not computed:
        st.info("사이드바에서 고객 정보를 입력하고 **'비교 분석 시작'** 버튼을 클릭하세요.")
    else:
        title_name = f"{s_customer} 고객님" if s_customer else "고객님"
        st.subheader(f"{title_name} 분석 결과")
        st.caption(
            f"기준일: {start_date_str}  |  원금: {fmt_krw(s_principal)}  |  연이율: {s_annual_rate}%"
        )

        # ── 정기예금 결과 ──────────────────────────────────
        st.markdown("#### 정기예금 결과 요약")
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("원금", fmt_krw(dep["원금"]))
        d2.metric("세전 이자", fmt_krw(dep["이자"]))
        d3.metric("세후 이자 (15.4%)", fmt_krw(dep["세후이자"]))
        d4.metric("세후 총액", fmt_krw(dep["세후총액"]))
        d5.metric("세후 수익률", f"{dep['세후수익률(%)']:.2f}%", f"보유 {dep['보유일수']:,}일")

        st.divider()

        # ── 시나리오 비교 ──────────────────────────────────
        if scenario_results:
            st.markdown("#### ETF 포트폴리오 시나리오 비교")

            # 카드형 지표
            scols = st.columns(len(scenario_results))
            for i, (sname, r) in enumerate(scenario_results.items()):
                diff = r["총평가액"] - dep["세후총액"]
                diff_str = f"예금 대비 {'+' if diff >= 0 else ''}{int(diff):,}원"
                scols[i].metric(
                    label=sname,
                    value=fmt_krw(r["총평가액"]),
                    delta=f"{r['총수익률(%)']:+.2f}%  ({diff_str})",
                )

            # 비교 테이블
            st.markdown("#### 시나리오 비교 요약표")
            summary_rows = []
            for sname, r in scenario_results.items():
                diff = r["총평가액"] - dep["세후총액"]
                summary_rows.append({
                    "시나리오": sname,
                    "총 평가액": fmt_krw(r["총평가액"]),
                    "수익률": f"{r['총수익률(%)']:+.2f}%",
                    "정기예금 세후 대비": f"{'+' if diff >= 0 else ''}{int(diff):,}원",
                    "우위": "ETF" if diff > 0 else "예금",
                })
            summary_rows.append({
                "시나리오": "정기예금 (세후)",
                "총 평가액": fmt_krw(dep["세후총액"]),
                "수익률": f"{dep['세후수익률(%)']:.2f}%",
                "정기예금 세후 대비": "기준",
                "우위": "기준",
            })
            st.dataframe(
                pd.DataFrame(summary_rows).set_index("시나리오"),
                use_container_width=True,
            )

            # 시나리오별 ETF 구성 상세
            st.markdown("#### 시나리오별 ETF 구성 상세")
            for sname, r in scenario_results.items():
                with st.expander(
                    f"{sname}  |  {fmt_krw(r['총평가액'])}  |  {r['총수익률(%)']:+.2f}%"
                ):
                    st.dataframe(build_detail_df(r["상세"]), use_container_width=True)
                    detail = r["상세"]
                    ret_vals = detail["수익률(%)"].tolist()
                    fig_bar = go.Figure(go.Bar(
                        x=detail.index.tolist(),
                        y=ret_vals,
                        marker_color=["#1B6B3A" if v >= 0 else "#C62828" for v in ret_vals],
                        text=[f"{v:+.1f}%" for v in ret_vals],
                        textposition="outside",
                    ))
                    fig_bar.update_layout(
                        height=260,
                        margin=dict(l=0, r=0, t=16, b=0),
                        showlegend=False,
                        plot_bgcolor="white",
                        paper_bgcolor="white",
                        yaxis=dict(ticksuffix="%"),
                    )
                    fig_bar.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
                    st.plotly_chart(fig_bar, use_container_width=True, key=f"bar_{sname}")

        st.divider()

        # ── 추천 ETF 목록 ──────────────────────────────────
        st.markdown("#### 추천 ETF 종목 목록")
        st.caption("아래 ETF들은 '사용자 정의 포트폴리오' 탭에서 직접 선택하여 시뮬레이션할 수 있습니다.")
        cat_icons = {"국내주식": "🇰🇷", "해외주식": "🌐", "채권": "🏦", "원자재·대안": "🥇"}
        for cat, etfs in ETF_POOL.items():
            icon = cat_icons.get(cat, "")
            with st.expander(f"{icon} {cat} — {len(etfs)}종목"):
                etf_rows = [{"ETF명": name, "티커": sym} for name, sym in etfs.items()]
                st.dataframe(
                    pd.DataFrame(etf_rows),
                    use_container_width=True,
                    hide_index=True,
                )

    st.caption(
        "※ 본 자료는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다. "
        "ETF 수익률은 운용보수 및 매매비용 미반영 기준입니다."
    )


# ═══════════════════════════════════════════════════════════
# Tab 2: 누적 수익률 차트
# ═══════════════════════════════════════════════════════════
with tab2:
    if not computed or not scenario_results:
        st.info("수익 비교 시뮬레이터 탭에서 먼저 **'비교 분석 시작'** 버튼을 실행해주세요.")
    else:
        st.subheader("누적 수익률 추이")
        st.caption(f"{start_date_str} ~ 현재 | 일별 시계열")

        # 인사이트 요약
        best_s = max(scenario_results, key=lambda s: scenario_results[s]["총수익률(%)"])
        best_r = scenario_results[best_s]["총수익률(%)"]
        dep_r = dep.get("세후수익률(%)", 0.0)
        gap = best_r - dep_r
        st.success(
            f"**{best_s} 포트폴리오**가 {best_r:+.2f}%로 최고 수익률. "
            f"정기예금({dep_r:.2f}%) 대비 **{gap:+.2f}%p** 차이."
        )

        with st.spinner("시계열 데이터 불러오는 중..."):
            end_str = datetime.today().strftime("%Y-%m-%d")
            date_range = pd.bdate_range(start=start_date_str, end=end_str)

            total_days = max(dep.get("보유일수", 1), 1)
            dep_daily = dep.get("세후수익률(%)", 0.0) / total_days
            dep_cum = [i * dep_daily for i in range(len(date_range))]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=date_range,
                y=dep_cum,
                name=f"정기예금 (세후 {dep.get('세후수익률(%)', 0):.2f}%)",
                line=dict(color="#9AABC2", width=2, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br><b>%{y:.2f}%</b><extra>정기예금</extra>",
            ))

            chart_colors = {"안정형": "#3B82F6", "균형형": "#10B981", "성장형": "#EF4444"}
            for sname, r in scenario_results.items():
                all_series = []
                for etf_name in r["상세"].index:
                    row = r["상세"].loc[etf_name]
                    symbol = row["심볼"]
                    weight = float(row["비중"].replace("%", "")) / 100
                    price_s = get_price_series(symbol, start_date_str, end_str)
                    if not price_s.empty and len(price_s) >= 2:
                        all_series.append((price_s / price_s.iloc[0] - 1) * weight * 100)
                if all_series:
                    combined = pd.concat(all_series, axis=1).sum(axis=1).dropna()
                    fig.add_trace(go.Scatter(
                        x=combined.index,
                        y=combined.values,
                        name=f"{sname} ({r['총수익률(%)']:+.2f}%)",
                        line=dict(color=chart_colors.get(sname, "#888"), width=2.5),
                        hovertemplate=f"%{{x|%Y-%m-%d}}<br><b>%{{y:.2f}}%</b><extra>{sname}</extra>",
                    ))

            fig.add_hline(y=0, line_dash="dot", line_color="rgba(0,0,0,0.2)", line_width=1)
            fig.update_layout(
                height=500,
                hovermode="x unified",
                xaxis_title="날짜",
                yaxis_title="누적 수익률 (%)",
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1,
                    bgcolor="rgba(255,255,255,0.85)",
                    bordercolor="rgba(0,0,0,0.1)", borderwidth=1,
                ),
                plot_bgcolor="white",
                paper_bgcolor="white",
                yaxis=dict(ticksuffix="%", gridcolor="rgba(0,0,0,0.05)", zeroline=False),
                xaxis=dict(gridcolor="rgba(0,0,0,0.03)"),
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig, use_container_width=True, key="line_chart")

        # 요약 테이블
        st.markdown("#### 최종 수익률 요약")
        rows = [{
            "구분": "정기예금 (세후)",
            "최종 평가액": fmt_krw(dep["세후총액"]),
            "수익률": f"{dep['세후수익률(%)']:.2f}%",
            "보유일수": f"{dep['보유일수']:,}일",
        }]
        for sname, r in scenario_results.items():
            rows.append({
                "구분": sname,
                "최종 평가액": fmt_krw(r["총평가액"]),
                "수익률": f"{r['총수익률(%)']:+.2f}%",
                "보유일수": f"{dep['보유일수']:,}일",
            })
        st.dataframe(pd.DataFrame(rows).set_index("구분"), use_container_width=True)

    st.caption(
        "※ 본 자료는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다."
    )


# ═══════════════════════════════════════════════════════════
# Tab 3: 사용자 정의 포트폴리오
# ═══════════════════════════════════════════════════════════
with tab3:
    st.subheader("사용자 정의 포트폴리오")
    st.caption("ETF를 직접 선택하고 비중을 설정하여 수익률을 계산합니다.")

    # ── ETF 선택 ──────────────────────────────────────────
    st.markdown("#### ETF 선택")
    cat_icons_t3 = {"국내주식": "🇰🇷", "해외주식": "🌐", "채권": "🏦", "원자재·대안": "🥇"}

    selected_etfs: list = []
    global_idx = 0
    for cat, etfs in ETF_POOL.items():
        icon = cat_icons_t3.get(cat, "")
        with st.expander(f"{icon} {cat} ({len(etfs)}종목)"):
            cols_chk = st.columns(3)
            for local_idx, etf_name in enumerate(etfs):
                with cols_chk[local_idx % 3]:
                    if st.checkbox(etf_name, key=f"chk_{global_idx}"):
                        selected_etfs.append(etf_name)
                global_idx += 1

    if not selected_etfs:
        st.info("위 카테고리를 펼쳐 ETF를 선택하세요.")
    else:
        # ── 비중 설정 ──────────────────────────────────────
        st.markdown(f"#### 비중 설정 ({len(selected_etfs)}종목 선택됨)")

        custom_weights: dict = {}
        default_w = max(1, 100 // len(selected_etfs))
        slider_cols = st.columns(min(len(selected_etfs), 3))

        for i, etf_name in enumerate(selected_etfs):
            with slider_cols[i % 3]:
                w = st.slider(
                    etf_name,
                    min_value=1,
                    max_value=100,
                    value=default_w,
                    key=f"sw_{i}",
                )
                custom_weights[etf_name] = w / 100.0

        total_pct = sum(custom_weights.values()) * 100
        if 95 <= total_pct <= 105:
            st.success(f"비중 합계: {total_pct:.1f}%  (자동 정규화 적용)")
        elif total_pct < 95:
            st.warning(f"비중 합계: {total_pct:.1f}%  — 100% 미만입니다. 자동 정규화됩니다.")
        else:
            st.warning(f"비중 합계: {total_pct:.1f}%  — 100% 초과입니다. 자동 정규화됩니다.")

        # ── 분석 기간 / 원금 설정 ──────────────────────────
        st.markdown("#### 분석 기간 및 원금 설정")
        use_sidebar_vals = st.checkbox("사이드바 입력값(가입일/원금) 사용", value=True)

        if use_sidebar_vals:
            if not computed:
                st.warning("먼저 사이드바에서 **'비교 분석 시작'** 버튼을 눌러주세요.")
                c_start = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
                c_principal = 10_000_000
            else:
                c_start = start_date_str
                c_principal = s_principal
                st.caption(f"가입일: {c_start}  |  원금: {fmt_krw(c_principal)}")
        else:
            c_date = st.date_input(
                "투자 시작일",
                value=date.today() - timedelta(days=365),
                key="c_date",
            )
            c_man = st.number_input("원금 (만원)", value=1_000, step=100, key="c_man")
            c_start = c_date.strftime("%Y-%m-%d")
            c_principal = c_man * 10_000

        # ── 계산 버튼 ──────────────────────────────────────
        if st.button("커스텀 포트폴리오 계산", type="primary", key="calc_custom"):
            with st.spinner("계산 중..."):
                custom_result = calc_portfolio_return(custom_weights, c_principal, c_start)

            if "오류" in custom_result:
                st.error(f"계산 오류: {custom_result['오류']}")
            else:
                ret = custom_result["총수익률(%)"]
                ret_sign = "+" if ret >= 0 else ""

                st.divider()
                st.markdown("#### 커스텀 포트폴리오 결과")
                c1, c2, c3 = st.columns(3)
                c1.metric("총 평가액", fmt_krw(custom_result["총평가액"]))
                c2.metric("총 손익", fmt_krw(custom_result["총손익"]))
                c3.metric("총 수익률", f"{ret_sign}{ret:.2f}%")

                # 정기예금 대비
                if computed and use_sidebar_vals:
                    dep_c = calc_deposit_return(c_principal, s_annual_rate, c_start)
                    diff = custom_result["총평가액"] - dep_c["세후총액"]
                    diff_sign = "+" if diff >= 0 else ""
                    winner = "ETF 포트폴리오 우위" if diff > 0 else "정기예금 우위"
                    st.info(
                        f"정기예금 세후 {fmt_krw(dep_c['세후총액'])} 대비: "
                        f"**{diff_sign}{int(diff):,}원** ({winner})"
                    )

                # ETF 상세
                st.markdown("#### ETF별 상세 결과")
                st.dataframe(build_detail_df(custom_result["상세"]), use_container_width=True)

                # 파이 차트
                detail = custom_result["상세"]
                pie_colors = [
                    "#1B3A6B", "#2E5BA8", "#3B82F6", "#60A5FA",
                    "#D4AF37", "#10B981", "#EF4444", "#F97316",
                    "#8B5CF6", "#06B6D4",
                ]
                fig_pie = go.Figure(go.Pie(
                    labels=detail.index.tolist(),
                    values=[float(w.replace("%", "")) for w in detail["비중"].tolist()],
                    hole=0.4,
                    textinfo="label+percent",
                    marker=dict(
                        colors=pie_colors[: len(detail)],
                        line=dict(color="#ffffff", width=2),
                    ),
                    hovertemplate="<b>%{label}</b><br>비중: %{percent}<extra></extra>",
                ))
                fig_pie.update_layout(
                    height=350,
                    margin=dict(l=0, r=0, t=16, b=0),
                    showlegend=True,
                    paper_bgcolor="white",
                    legend=dict(
                        font=dict(size=11),
                        bgcolor="rgba(255,255,255,0.9)",
                        bordercolor="rgba(0,0,0,0.1)",
                        borderwidth=1,
                    ),
                )
                st.plotly_chart(fig_pie, use_container_width=True, key="pie_custom")

    st.caption(
        "※ 본 자료는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다. "
        "투자는 원금 손실 위험이 있습니다."
    )
