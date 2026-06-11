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
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

# ─────────────────────────────────────────────
# 페이지 설정
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
        "KODEX 200":        "069500.KS",
        "TIGER 200":        "102110.KS",
        "KODEX 코스닥150":   "229200.KQ",
        "TIGER 코스닥150":   "232080.KQ",
        "KODEX 삼성그룹":    "091160.KS",
        "TIGER 2차전지테마": "305720.KS",
        "KODEX 반도체":      "091230.KS",
    },
    "해외주식": {
        "TIGER 미국S&P500":    "360750.KS",
        "TIGER 미국나스닥100":  "133690.KS",
        "KODEX 미국S&P500TR":  "379800.KS",
        "TIGER 차이나CSI300":  "192090.KS",
    },
    "채권": {
        "KODEX 국채3년":   "114820.KS",
        "TIGER 국채3년":   "114260.KS",
        "KOSEF 국고채10년": "148070.KS",
        "KODEX 단기채권":  "153130.KS",
    },
    "원자재·대안": {
        "KODEX 골드선물(H)":            "132030.KS",
        "TIGER 원유선물Enhanced(H)":    "261220.KS",
    },
}

ETF_FLAT = {name: sym for cat in ETF_POOL.values() for name, sym in cat.items()}

# ─────────────────────────────────────────────
# 포트폴리오 시나리오
# ─────────────────────────────────────────────
SCENARIOS = {
    "안정형": {
        "KODEX 200":        0.2,
        "TIGER 미국S&P500":  0.2,
        "KODEX 국채3년":     0.4,
        "KODEX 골드선물(H)": 0.2,
    },
    "균형형": {
        "KODEX 200":        0.3,
        "TIGER 미국S&P500":  0.3,
        "KODEX 국채3년":     0.3,
        "KODEX 골드선물(H)": 0.1,
    },
    "성장형": {
        "KODEX 200":          0.3,
        "TIGER 미국S&P500":    0.4,
        "TIGER 미국나스닥100": 0.2,
        "KODEX 국채3년":       0.1,
    },
}

# 시나리오별 색상
SCENARIO_COLORS = {
    "안정형": "#42A5F5",
    "균형형": "#26A69A",
    "성장형": "#EF5350",
}

# ─────────────────────────────────────────────
# 핵심 계산 함수
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_price_on_date(symbol: str, target_date: str) -> float | None:
    """특정 날짜(또는 가장 가까운 다음 거래일)의 종가를 반환합니다."""
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
    """기간별 종가 시계열을 반환합니다."""
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
def get_current_price(symbol: str) -> float | None:
    """현재(가장 최근 거래일) 종가를 반환합니다."""
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
    """정기예금 단리 수익을 계산합니다. annual_rate: 연이율(%) 예: 3.5"""
    if end_date is None:
        end_date = datetime.today().strftime("%Y-%m-%d")
    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
    if principal <= 0:
        return {
            "원금": principal, "이자": 0, "세후이자": 0,
            "세후총액": round(principal), "수익률(%)": 0.0,
            "세후수익률(%)": 0.0, "보유일수": days,
        }
    if days <= 0:
        return {
            "원금": principal, "이자": 0, "세후이자": 0,
            "세후총액": round(principal), "수익률(%)": 0.0,
            "세후수익률(%)": 0.0, "보유일수": max(days, 0),
        }
    interest = principal * (annual_rate / 100) * (days / 365)
    return {
        "원금": principal,
        "이자": round(interest),
        "세후이자": round(interest * 0.846),   # 이자소득세 15.4% 차감
        "세후총액": round(principal + interest * 0.846),
        "수익률(%)": round(interest / principal * 100, 2),
        "세후수익률(%)": round(interest * 0.846 / principal * 100, 2),
        "보유일수": days,
    }


def calc_etf_return(
    symbol: str, principal: float, start_date: str, end_date: str = None
) -> dict:
    """단일 ETF 투자 수익을 계산합니다."""
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
    """포트폴리오 수익을 계산합니다. weights: {'ETF명': 비중(0~1), ...}"""
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
        r.update(
            {
                "종목명": name,
                "심볼": symbol,
                "배분금액": round(alloc),
                "비중": f"{weight * 100:.0f}%",
            }
        )
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
# 유틸리티 함수
# ─────────────────────────────────────────────

def fmt_krw(value: float) -> str:
    """원화 형식으로 포맷합니다."""
    return f"₩{int(value):,}"


def fmt_pct(value: float, color: bool = True) -> str:
    """수익률을 포맷합니다."""
    return f"{value:+.2f}%" if color else f"{value:.2f}%"


def color_metric(value: float) -> str:
    """수익률 부호에 따라 색상 hex를 반환합니다."""
    return "#2ECC71" if value >= 0 else "#E74C3C"


def build_detail_df(detail_df: pd.DataFrame) -> pd.DataFrame:
    """상세 DataFrame을 표시용으로 재구성합니다."""
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
# Custom CSS — Private Banking Terminal
# ─────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

/* ── 전역 폰트 & 배경 ── */
html, body, [class*="css"], .stApp {
    font-family: 'Pretendard', 'Apple SD Gothic Neo', sans-serif !important;
    background-color: #EEF1F6 !important;
}

/* ── 사이드바 ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0D1B2A 0%, #1B3A6B 60%, #0D2444 100%) !important;
    border-right: 1px solid rgba(212,175,55,0.25) !important;
}
[data-testid="stSidebar"] * {
    color: #E8EDF5 !important;
}
[data-testid="stSidebar"] .stTextInput input,
[data-testid="stSidebar"] .stNumberInput input,
[data-testid="stSidebar"] .stDateInput input {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(212,175,55,0.35) !important;
    border-radius: 6px !important;
    color: #F0F4FF !important;
    font-family: 'Pretendard', sans-serif !important;
}
[data-testid="stSidebar"] .stTextInput input:focus,
[data-testid="stSidebar"] .stNumberInput input:focus {
    border-color: #D4AF37 !important;
    box-shadow: 0 0 0 2px rgba(212,175,55,0.2) !important;
}
[data-testid="stSidebar"] label {
    color: #A8BBDB !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(212,175,55,0.2) !important;
    margin: 16px 0 !important;
}
[data-testid="stSidebar"] .stButton > button {
    background: linear-gradient(135deg, #D4AF37 0%, #F0D060 50%, #C49A20 100%) !important;
    color: #0D1B2A !important;
    font-weight: 700 !important;
    font-size: 0.9rem !important;
    letter-spacing: 0.05em !important;
    border: none !important;
    border-radius: 6px !important;
    padding: 12px 0 !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 2px 12px rgba(212,175,55,0.4) !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 20px rgba(212,175,55,0.55) !important;
}

/* ── 탭 스타일 ── */
.stTabs [data-baseweb="tab-list"] {
    background: #fff !important;
    border-radius: 10px 10px 0 0 !important;
    padding: 6px 8px 0 !important;
    gap: 4px !important;
    border-bottom: 2px solid #D4AF37 !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Pretendard', sans-serif !important;
    font-size: 0.88rem !important;
    font-weight: 600 !important;
    color: #6B7A99 !important;
    padding: 10px 20px !important;
    border-radius: 6px 6px 0 0 !important;
    transition: all 0.2s ease !important;
    letter-spacing: 0.02em !important;
}
.stTabs [aria-selected="true"] {
    color: #1B3A6B !important;
    background: rgba(27,58,107,0.07) !important;
    border-bottom: 3px solid #D4AF37 !important;
}
.stTabs [data-baseweb="tab-panel"] {
    background: transparent !important;
    padding: 24px 0 0 0 !important;
}

/* ── 공통 카드 ── */
.pb-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 24px 28px;
    box-shadow: 0 2px 12px rgba(13,27,42,0.07), 0 0 0 1px rgba(13,27,42,0.04);
    margin-bottom: 20px;
    position: relative;
    overflow: hidden;
}
.pb-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 4px; height: 100%;
    background: linear-gradient(180deg, #D4AF37, #C49A20);
    border-radius: 12px 0 0 12px;
}

/* ── 헤더 ── */
.app-header {
    background: linear-gradient(135deg, #0D1B2A 0%, #1B3A6B 55%, #14305A 100%);
    border-radius: 14px;
    padding: 28px 36px;
    margin-bottom: 28px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 4px 24px rgba(13,27,42,0.22);
}
.app-header::after {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 220px; height: 220px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(212,175,55,0.18) 0%, transparent 70%);
    pointer-events: none;
}
.header-eyebrow {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #D4AF37;
    margin-bottom: 8px;
}
.header-title {
    font-size: 1.85rem;
    font-weight: 800;
    color: #F0F4FF;
    line-height: 1.15;
    margin-bottom: 6px;
    letter-spacing: -0.02em;
}
.header-sub {
    font-size: 0.88rem;
    color: #7A9CC8;
    font-weight: 400;
    margin-bottom: 0;
}
.header-date {
    position: absolute;
    top: 28px; right: 36px;
    font-size: 0.78rem;
    color: rgba(212,175,55,0.85);
    font-weight: 500;
    letter-spacing: 0.04em;
    font-variant-numeric: tabular-nums;
}

/* ── 섹션 제목 ── */
.section-title {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #1B3A6B;
    border-left: 3px solid #D4AF37;
    padding-left: 10px;
    margin: 28px 0 16px 0;
    line-height: 1.4;
}

/* ── 정기예금 KPI 카드 ── */
.deposit-kpi-row {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 14px;
    margin-bottom: 8px;
}
.deposit-kpi {
    background: #fff;
    border-radius: 10px;
    padding: 18px 16px 14px;
    box-shadow: 0 1px 8px rgba(13,27,42,0.07);
    border: 1px solid rgba(13,27,42,0.06);
    text-align: center;
    position: relative;
}
.deposit-kpi::after {
    content: '';
    position: absolute;
    bottom: 0; left: 20%; right: 20%;
    height: 3px;
    background: linear-gradient(90deg, #D4AF37, #F0D060);
    border-radius: 2px;
}
.kpi-label {
    font-size: 0.72rem;
    font-weight: 600;
    color: #8895B3;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 8px;
}
.kpi-value {
    font-size: 1.1rem;
    font-weight: 700;
    color: #1B3A6B;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
}
.kpi-value.highlight {
    font-size: 1.2rem;
    color: #0D1B2A;
}

/* ── 시나리오 카드 ── */
.scenario-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 18px;
    margin-bottom: 8px;
}
.scenario-card {
    background: #fff;
    border-radius: 12px;
    padding: 22px 20px 18px;
    box-shadow: 0 2px 14px rgba(13,27,42,0.08);
    border: 1px solid rgba(13,27,42,0.05);
    position: relative;
    overflow: hidden;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.scenario-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 6px 24px rgba(13,27,42,0.13);
}
.scenario-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.73rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    margin-bottom: 14px;
}
.scenario-total {
    font-size: 1.7rem;
    font-weight: 800;
    line-height: 1.1;
    letter-spacing: -0.03em;
    margin-bottom: 6px;
    font-variant-numeric: tabular-nums;
}
.scenario-ret {
    font-size: 1.05rem;
    font-weight: 700;
    margin-bottom: 10px;
    font-variant-numeric: tabular-nums;
}
.scenario-vs {
    font-size: 0.8rem;
    font-weight: 500;
    padding: 6px 10px;
    border-radius: 6px;
    display: inline-block;
}
.scenario-stripe {
    position: absolute;
    top: 0; right: 0;
    width: 90px; height: 90px;
    border-radius: 0 12px 0 90px;
    opacity: 0.08;
}

/* ── 인사이트 배너 ── */
.insight-banner {
    background: linear-gradient(135deg, #0D1B2A 0%, #1B3A6B 100%);
    border-radius: 10px;
    padding: 16px 22px;
    margin-bottom: 22px;
    display: flex;
    align-items: flex-start;
    gap: 14px;
}
.insight-icon {
    font-size: 1.3rem;
    line-height: 1;
    margin-top: 1px;
}
.insight-text {
    color: #D0DCF0;
    font-size: 0.88rem;
    line-height: 1.6;
    margin: 0;
}
.insight-accent {
    color: #D4AF37;
    font-weight: 700;
}

/* ── 비교 테이블 래퍼 ── */
.stDataFrame {
    border-radius: 10px !important;
    overflow: hidden !important;
    border: 1px solid rgba(13,27,42,0.08) !important;
    box-shadow: 0 1px 8px rgba(13,27,42,0.05) !important;
}

/* ── expander 스타일 ── */
.streamlit-expanderHeader {
    background: #fff !important;
    border: 1px solid rgba(13,27,42,0.08) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    color: #1B3A6B !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.01em !important;
}
.streamlit-expanderContent {
    background: #FAFBFD !important;
    border: 1px solid rgba(13,27,42,0.06) !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
}

/* ── 사이드바 요약 카드 ── */
.sb-summary {
    background: rgba(212,175,55,0.1);
    border: 1px solid rgba(212,175,55,0.3);
    border-radius: 8px;
    padding: 14px 16px;
    margin-top: 8px;
}
.sb-summary-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
    font-size: 0.82rem;
}
.sb-summary-row:last-child { margin-bottom: 0; }
.sb-label { color: #8AADDB; }
.sb-value { color: #F0E8C0; font-weight: 600; font-variant-numeric: tabular-nums; }

/* ── 면책 고지 ── */
.disclaimer {
    text-align: center;
    font-size: 0.72rem;
    color: #9AABC2;
    padding: 16px 0 8px;
    border-top: 1px solid rgba(13,27,42,0.1);
    margin-top: 32px;
    line-height: 1.7;
    letter-spacing: 0.02em;
}

/* ── 진행 바 ── */
.weight-bar-wrap {
    background: #E8EDF6;
    border-radius: 4px;
    height: 6px;
    margin-top: 6px;
    overflow: hidden;
}
.weight-bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s ease;
}

/* ── 사이드바 섹션 헤더 ── */
.sb-section-head {
    font-size: 0.65rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: #D4AF37 !important;
    margin: 16px 0 10px !important;
}

/* ── info / warning 박스 커스텀 ── */
.stAlert {
    border-radius: 8px !important;
    font-size: 0.86rem !important;
}

/* ── metric 커스텀 ── */
[data-testid="stMetric"] {
    background: #fff;
    border-radius: 10px;
    padding: 14px 16px !important;
    box-shadow: 0 1px 6px rgba(13,27,42,0.06);
    border: 1px solid rgba(13,27,42,0.05);
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    color: #7A8EAD !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.15rem !important;
    font-weight: 700 !important;
    color: #1B3A6B !important;
    font-variant-numeric: tabular-nums !important;
}

/* ── 탭 콘텐츠 배경 ── */
.main .block-container {
    padding-top: 0 !important;
    max-width: 1200px !important;
}

/* ── 카테고리 라벨 ── */
.cat-header {
    background: linear-gradient(90deg, #1B3A6B, #2E5BA8);
    color: white !important;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 6px 14px;
    border-radius: 6px;
    display: inline-block;
    margin-bottom: 10px;
}

/* ── 커스텀 포트폴리오 weight 라인 ── */
.weight-item {
    background: #fff;
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 10px;
    box-shadow: 0 1px 6px rgba(13,27,42,0.06);
    border-left: 3px solid #1B3A6B;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 앱 헤더
# ─────────────────────────────────────────────

today_str = datetime.today().strftime("%Y년 %m월 %d일")

st.markdown(f"""
<div class="app-header">
    <div class="header-date">{today_str}</div>
    <div class="header-eyebrow">Private Wealth Management</div>
    <div class="header-title">ETF 포트폴리오 vs 정기예금<br>수익률 비교 제안서</div>
    <div class="header-sub">과거 실제 시장 데이터 기반 시뮬레이션 — 자산관리 솔루션</div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 사이드바: 고객 정보 입력
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown('<div class="sb-section-head">고객 정보</div>', unsafe_allow_html=True)

    customer_name = st.text_input("고객명 (선택사항)", placeholder="예: 홍길동")

    st.markdown('<div class="sb-section-head" style="margin-top:18px;">분석 조건 설정</div>', unsafe_allow_html=True)

    max_date = date.today() - timedelta(days=30)
    min_date = date(2015, 1, 1)
    default_date = date.today() - timedelta(days=365 * 2)

    deposit_date = st.date_input(
        "정기예금 가입일",
        value=default_date,
        min_value=min_date,
        max_value=max_date,
        help="비교 시작 기준일입니다. 최소 30일 이전 날짜를 선택하세요.",
    )

    principal_man = st.number_input(
        "투자 원금 (만원)",
        min_value=100,
        max_value=1_000_000,
        value=1_000,
        step=100,
        help="만원 단위로 입력하세요.",
    )
    principal = principal_man * 10_000

    annual_rate = st.number_input(
        "당시 연이율 (%)",
        min_value=0.1,
        max_value=20.0,
        value=3.5,
        step=0.1,
        format="%.1f",
    )

    # 입력 요약 카드
    hold_days = (date.today() - deposit_date).days
    st.markdown(f"""
    <div class="sb-summary">
        <div class="sb-summary-row">
            <span class="sb-label">고객명</span>
            <span class="sb-value">{customer_name if customer_name else '—'}</span>
        </div>
        <div class="sb-summary-row">
            <span class="sb-label">가입일</span>
            <span class="sb-value">{deposit_date.strftime('%Y.%m.%d')}</span>
        </div>
        <div class="sb-summary-row">
            <span class="sb-label">보유기간</span>
            <span class="sb-value">{hold_days:,}일</span>
        </div>
        <div class="sb-summary-row">
            <span class="sb-label">원금</span>
            <span class="sb-value">{fmt_krw(principal)}</span>
        </div>
        <div class="sb-summary-row">
            <span class="sb-label">연이율</span>
            <span class="sb-value">{annual_rate:.1f}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    run_btn = st.button("비교 분석 시작", type="primary", use_container_width=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(
        "<span style='font-size:0.72rem; color:#5A7AAA; line-height:1.6; display:block;'>"
        "본 자료는 참고용 시뮬레이션입니다.<br>"
        "과거 수익이 미래를 보장하지 않습니다."
        "</span>",
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────
# 탭 구성
# ─────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(
    ["  수익 비교 시뮬레이터  ", "  누적 수익률 차트  ", "  사용자 정의 포트폴리오  "]
)

# 탭 간 공유 변수 사전 초기화 — run_btn=False 상태에서 Tab 2/3가 NameError 없이 렌더링되도록 보장
start_date_str: str = deposit_date.strftime("%Y-%m-%d")
scenario_results: dict = {}
dep: dict = {}
errors: list = []

# ═══════════════════════════════════════════════════════════════
# Tab 1: 수익 비교 시뮬레이터
# ═══════════════════════════════════════════════════════════════

with tab1:
    if not run_btn:
        st.markdown("""
        <div class="pb-card" style="text-align:center; padding: 40px 28px;">
            <div style="font-size:2.5rem; margin-bottom:16px; opacity:0.4;">📋</div>
            <div style="font-size:1.05rem; font-weight:600; color:#1B3A6B; margin-bottom:8px;">
                분석 준비 완료
            </div>
            <div style="font-size:0.88rem; color:#7A8EAD; line-height:1.6;">
                좌측 사이드바에서 고객 정보와 투자 조건을 입력한 후<br>
                <strong style="color:#D4AF37;">'비교 분석 시작'</strong> 버튼을 클릭하세요.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # start_date_str은 탭 바깥에서 이미 초기화됨 — 여기서 재할당하여 최신 상태 유지
        start_date_str = deposit_date.strftime("%Y-%m-%d")
        title_name = f"{customer_name} 고객님" if customer_name else "고객님"

        # 분석 대상 타이틀
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:20px;">
            <div style="width:3px; height:28px; background:linear-gradient(180deg,#D4AF37,#C49A20); border-radius:2px;"></div>
            <div>
                <div style="font-size:1.25rem; font-weight:800; color:#0D1B2A; letter-spacing:-0.02em;">
                    {title_name} 포트폴리오 분석 결과
                </div>
                <div style="font-size:0.8rem; color:#8895B3; margin-top:2px;">
                    기준일: {start_date_str} &nbsp;|&nbsp; 원금: {fmt_krw(principal)} &nbsp;|&nbsp; 연이율: {annual_rate}%
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── 정기예금 계산 ──────────────────────────────────────────
        dep = calc_deposit_return(principal, annual_rate, start_date_str)

        # ── ETF 시나리오 계산 ─────────────────────────────────────
        errors = []

        with st.spinner("ETF 시장 데이터를 조회하는 중..."):
            for sname, weights in SCENARIOS.items():
                result = calc_portfolio_return(weights, principal, start_date_str)
                if "오류" in result:
                    errors.append(f"{sname}: {result['오류']}")
                else:
                    scenario_results[sname] = result

        if errors:
            for err in errors:
                st.warning(f"일부 데이터 로드 실패: {err}")

        # ── 정기예금 결과 카드 ────────────────────────────────────
        st.markdown('<div class="section-title">정기예금 결과 요약</div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div class="deposit-kpi-row">
            <div class="deposit-kpi">
                <div class="kpi-label">원금</div>
                <div class="kpi-value">{fmt_krw(dep['원금'])}</div>
            </div>
            <div class="deposit-kpi">
                <div class="kpi-label">세전 이자</div>
                <div class="kpi-value">{fmt_krw(dep['이자'])}</div>
            </div>
            <div class="deposit-kpi">
                <div class="kpi-label">세후 이자 (15.4% 과세)</div>
                <div class="kpi-value">{fmt_krw(dep['세후이자'])}</div>
            </div>
            <div class="deposit-kpi">
                <div class="kpi-label">세후 총액</div>
                <div class="kpi-value highlight">{fmt_krw(dep['세후총액'])}</div>
            </div>
            <div class="deposit-kpi">
                <div class="kpi-label">세후 수익률</div>
                <div class="kpi-value highlight" style="color:#1B6B3A;">{dep['세후수익률(%)']:.2f}%</div>
            </div>
        </div>
        <div style="font-size:0.73rem; color:#9AABC2; margin-bottom:4px; text-align:right;">
            보유일수: {dep['보유일수']:,}일
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── 시나리오 카드 ─────────────────────────────────────────
        if scenario_results:
            st.markdown('<div class="section-title">ETF 포트폴리오 시나리오 비교</div>', unsafe_allow_html=True)

            # 스토리텔링 인사이트 배너
            best_scenario = max(scenario_results, key=lambda s: scenario_results[s]["총수익률(%)"])
            best_ret = scenario_results[best_scenario]["총수익률(%)"]
            dep_ret = dep["세후수익률(%)"]
            outperform = best_ret - dep_ret

            if outperform >= 0:
                insight_msg = (
                    f"<strong class='insight-accent'>{best_scenario} 포트폴리오</strong>의 경우 정기예금 대비 "
                    f"<strong class='insight-accent'>+{outperform:.2f}%p</strong> 높은 수익률을 기록했습니다. "
                    f"같은 원금으로 <strong class='insight-accent'>{fmt_krw(scenario_results[best_scenario]['총평가액'] - dep['세후총액'])}</strong> 더 벌 수 있었습니다."
                )
            else:
                insight_msg = (
                    f"이 기간에는 모든 ETF 시나리오가 정기예금 대비 저조했습니다. "
                    f"시장 상황에 따라 ETF 수익률은 변동될 수 있습니다."
                )

            st.markdown(f"""
            <div class="insight-banner">
                <div class="insight-icon">💡</div>
                <p class="insight-text">{insight_msg}</p>
            </div>
            """, unsafe_allow_html=True)

            # 시나리오 색상 설정
            scenario_card_styles = {
                "안정형": {
                    "color": "#1565C0",
                    "bg": "#EEF4FF",
                    "badge_bg": "#DBEAFE",
                    "badge_color": "#1565C0",
                    "stripe": "#1565C0",
                },
                "균형형": {
                    "color": "#00695C",
                    "bg": "#EDFAF7",
                    "badge_bg": "#CCFBF1",
                    "badge_color": "#00695C",
                    "stripe": "#00695C",
                },
                "성장형": {
                    "color": "#C62828",
                    "bg": "#FFF1F1",
                    "badge_bg": "#FFE2E2",
                    "badge_color": "#C62828",
                    "stripe": "#C62828",
                },
            }

            cards_html = '<div class="scenario-grid">'
            for sname, r in scenario_results.items():
                diff = r["총평가액"] - dep["세후총액"]
                ret = r["총수익률(%)"]
                style = scenario_card_styles.get(sname, {"color": "#333", "bg": "#f5f5f5", "badge_bg": "#eee", "badge_color": "#333", "stripe": "#888"})
                diff_sign = "+" if diff >= 0 else ""
                diff_color = "#1B6B3A" if diff >= 0 else "#C62828"
                diff_bg = "#E8F5E9" if diff >= 0 else "#FFEBEE"
                ret_sign = "+" if ret >= 0 else ""
                scenario_desc = {"안정형": "채권·금 중심 방어형", "균형형": "주식·채권 균형 배분", "성장형": "주식·나스닥 집중형"}

                cards_html += f"""
                <div class="scenario-card">
                    <div class="scenario-stripe" style="background:{style['stripe']};"></div>
                    <div>
                        <span class="scenario-badge" style="background:{style['badge_bg']}; color:{style['badge_color']};">
                            {sname}
                        </span>
                        <div style="font-size:0.73rem; color:#9AABC2; margin-bottom:12px;">{scenario_desc.get(sname, '')}</div>
                    </div>
                    <div class="scenario-total" style="color:{style['color']};">{fmt_krw(r['총평가액'])}</div>
                    <div class="scenario-ret" style="color:{style['color']};">{ret_sign}{ret:.2f}%</div>
                    <span class="scenario-vs" style="background:{diff_bg}; color:{diff_color};">
                        정기예금 대비 {diff_sign}{int(diff):,}원
                    </span>
                </div>
                """
            # 정기예금 기준 카드 추가
            cards_html += f"""
                <div class="scenario-card" style="grid-column: 1 / -1; display:flex; align-items:center; justify-content:space-between; padding: 16px 24px; background:#F8F9FC; border: 1px solid #E0E5EF;">
                    <div>
                        <span class="scenario-badge" style="background:#E8EDF6; color:#4A5A78;">정기예금 (기준)</span>
                        <div style="font-size:0.73rem; color:#9AABC2;">이자소득세 15.4% 차감 후 세후 기준</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:1.35rem; font-weight:800; color:#4A5A78; font-variant-numeric:tabular-nums;">{fmt_krw(dep['세후총액'])}</div>
                        <div style="font-size:0.95rem; font-weight:600; color:#6B7A99;">{dep['세후수익률(%)']:.2f}%</div>
                    </div>
                </div>
            """
            cards_html += '</div>'
            st.markdown(cards_html, unsafe_allow_html=True)

            # ── 시나리오 비교 테이블 ──────────────────────────────
            st.markdown('<div class="section-title">시나리오별 최종 수치 비교</div>', unsafe_allow_html=True)

            summary_data = []
            for sname, r in scenario_results.items():
                diff = r["총평가액"] - dep["세후총액"]
                summary_data.append({
                    "시나리오": sname,
                    "총 평가액": fmt_krw(r["총평가액"]),
                    "총 손익": fmt_krw(r["총손익"]),
                    "총 수익률": f"{r['총수익률(%)']:+.2f}%",
                    "정기예금 세후 대비": f"{'+' if diff >= 0 else ''}{int(diff):,}원",
                    "우위": "ETF 우위" if diff > 0 else "예금 우위",
                })
            summary_data.append({
                "시나리오": "정기예금 (세후)",
                "총 평가액": fmt_krw(dep["세후총액"]),
                "총 손익": fmt_krw(dep["세후이자"]),
                "총 수익률": f"{dep['세후수익률(%)']:.2f}%",
                "정기예금 세후 대비": "기준",
                "우위": "기준",
            })

            summary_df = pd.DataFrame(summary_data).set_index("시나리오")
            st.dataframe(summary_df, use_container_width=True)

        # ── 시나리오별 상세 구성 ──────────────────────────────────
        if scenario_results:
            st.markdown('<div class="section-title">시나리오별 ETF 구성 상세</div>', unsafe_allow_html=True)

            for sname, r in scenario_results.items():
                color = SCENARIO_COLORS.get(sname, "#888")
                with st.expander(
                    f"{sname}  |  총 평가액: {fmt_krw(r['총평가액'])}  |  수익률: {r['총수익률(%)']:+.2f}%",
                    expanded=False,
                ):
                    display_df = build_detail_df(r["상세"])
                    st.dataframe(display_df, use_container_width=True)

                    detail = r["상세"]
                    fig_mini = go.Figure(
                        go.Bar(
                            x=detail.index.tolist(),
                            y=detail["수익률(%)"].tolist(),
                            marker_color=[
                                "#1B6B3A" if v >= 0 else "#C62828"
                                for v in detail["수익률(%)"].tolist()
                            ],
                            marker_line_width=0,
                            text=[f"{v:+.1f}%" for v in detail["수익률(%)"].tolist()],
                            textposition="outside",
                            textfont=dict(size=11, color="#333"),
                        )
                    )
                    fig_mini.update_layout(
                        height=260,
                        margin=dict(l=0, r=0, t=16, b=0),
                        yaxis_title="수익률 (%)",
                        showlegend=False,
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="Pretendard, sans-serif", size=12),
                        yaxis=dict(
                            ticksuffix="%",
                            gridcolor="rgba(13,27,42,0.07)",
                            zeroline=False,
                        ),
                        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
                    )
                    fig_mini.add_hline(y=0, line_dash="dash", line_color="#C0CAD8", line_width=1.5)
                    st.plotly_chart(fig_mini, use_container_width=True)

        # 면책 고지
        st.markdown("""
        <div class="disclaimer">
            본 자료는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.
            투자는 원금 손실 위험이 있으며, 투자 결정은 고객 본인의 판단과 책임 하에 이루어집니다.<br>
            ETF 수익률은 운용보수 및 매매비용이 반영되지 않은 단순 가격 수익률 기준입니다.
        </div>
        """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# Tab 2: 누적 수익률 차트
# ═══════════════════════════════════════════════════════════════

with tab2:
    if not run_btn:
        st.markdown("""
        <div class="pb-card" style="text-align:center; padding: 40px 28px;">
            <div style="font-size:2.5rem; margin-bottom:16px; opacity:0.4;">📈</div>
            <div style="font-size:1.05rem; font-weight:600; color:#1B3A6B; margin-bottom:8px;">
                차트 데이터 준비 중
            </div>
            <div style="font-size:0.88rem; color:#7A8EAD; line-height:1.6;">
                좌측 사이드바에서 <strong style="color:#D4AF37;">'비교 분석 시작'</strong>을 먼저 실행해주세요.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:20px;">
            <div style="width:3px; height:28px; background:linear-gradient(180deg,#D4AF37,#C49A20); border-radius:2px;"></div>
            <div>
                <div style="font-size:1.25rem; font-weight:800; color:#0D1B2A; letter-spacing:-0.02em;">누적 수익률 추이</div>
                <div style="font-size:0.8rem; color:#8895B3; margin-top:2px;">{start_date_str} ~ 현재 기준 일별 시계열</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.spinner("시계열 데이터를 불러오는 중..."):
            end_str = datetime.today().strftime("%Y-%m-%d")

            date_range = pd.bdate_range(start=start_date_str, end=end_str)
            total_days = dep.get("보유일수", 0)
            if total_days > 0:
                dep_daily_rate = dep["세후수익률(%)"] / total_days
                dep_cum = [i * dep_daily_rate for i in range(len(date_range))]
            else:
                dep_cum = [0.0] * len(date_range)

            # 인사이트 배너 (차트 위)
            if scenario_results:
                best_s = max(scenario_results, key=lambda s: scenario_results[s]["총수익률(%)"])
                worst_s = min(scenario_results, key=lambda s: scenario_results[s]["총수익률(%)"])
                best_r = scenario_results[best_s]["총수익률(%)"]
                dep_r = dep.get("세후수익률(%)", 0.0)
                gap = best_r - dep_r
                gap_sign = "+" if gap >= 0 else ""

                st.markdown(f"""
                <div class="insight-banner">
                    <div class="insight-icon">📊</div>
                    <p class="insight-text">
                        <strong class='insight-accent'>{best_s} 포트폴리오</strong>가
                        <strong class='insight-accent'>{best_r:+.2f}%</strong>로 최고 수익률을 기록했으며,
                        정기예금({dep_r:.2f}%) 대비
                        <strong class='insight-accent'>{gap_sign}{gap:.2f}%p</strong> 차이를 보였습니다.
                        동일 기간 {worst_s} 포트폴리오는 {scenario_results[worst_s]['총수익률(%)']:+.2f}%를 기록했습니다.
                    </p>
                </div>
                """, unsafe_allow_html=True)

            fig = go.Figure()

            # 정기예금 라인
            fig.add_trace(
                go.Scatter(
                    x=date_range,
                    y=dep_cum,
                    name=f"정기예금 (세후 {dep.get('세후수익률(%)', 0.0):.2f}%)",
                    line=dict(color="#9AABC2", width=2, dash="dash"),
                    hovertemplate="%{x|%Y-%m-%d}<br><b>%{y:.2f}%</b><extra>정기예금</extra>",
                )
            )

            # 시나리오 색상 — 차트용
            chart_colors = {
                "안정형": "#3B82F6",
                "균형형": "#10B981",
                "성장형": "#EF4444",
            }

            for sname, r in scenario_results.items():
                color = chart_colors.get(sname, "#888888")
                all_series = []
                detail_df = r["상세"]

                for etf_name in detail_df.index:
                    row = detail_df.loc[etf_name]
                    symbol = row["심볼"]
                    weight_str = row["비중"]
                    weight = float(weight_str.replace("%", "")) / 100

                    price_s = get_price_series(symbol, start_date_str, end_str)
                    if price_s.empty or len(price_s) < 2:
                        continue
                    ret_series = (price_s / price_s.iloc[0] - 1) * weight * 100
                    all_series.append(ret_series)

                if not all_series:
                    continue

                combined = pd.concat(all_series, axis=1).sum(axis=1).dropna()

                fig.add_trace(
                    go.Scatter(
                        x=combined.index,
                        y=combined.values,
                        name=f"{sname} ({r['총수익률(%)']:+.2f}%)",
                        line=dict(color=color, width=2.5),
                        hovertemplate=f"%{{x|%Y-%m-%d}}<br><b>%{{y:.2f}}%</b><extra>{sname}</extra>",
                    )
                )

            fig.add_hline(y=0, line_dash="dot", line_color="rgba(13,27,42,0.2)", line_width=1)

            fig.update_layout(
                height=520,
                xaxis_title=None,
                yaxis_title="누적 수익률 (%)",
                hovermode="x unified",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                    font=dict(size=12, family="Pretendard, sans-serif"),
                    bgcolor="rgba(255,255,255,0.85)",
                    bordercolor="rgba(13,27,42,0.1)",
                    borderwidth=1,
                ),
                margin=dict(l=0, r=0, t=16, b=0),
                plot_bgcolor="rgba(255,255,255,1)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Pretendard, sans-serif", size=12, color="#4A5A78"),
                yaxis=dict(
                    ticksuffix="%",
                    gridcolor="rgba(13,27,42,0.06)",
                    zeroline=False,
                    tickfont=dict(size=11),
                ),
                xaxis=dict(
                    gridcolor="rgba(13,27,42,0.04)",
                    tickfont=dict(size=11),
                    showline=True,
                    linecolor="rgba(13,27,42,0.1)",
                ),
            )

            st.plotly_chart(fig, use_container_width=True)

        # 최종 수익률 요약 테이블
        if scenario_results:
            st.markdown('<div class="section-title">최종 수익률 요약</div>', unsafe_allow_html=True)
            end_str_summary = datetime.today().strftime("%Y-%m-%d")
            summary_rows = [
                {
                    "구분": "정기예금 (세후)",
                    "최종 평가액": fmt_krw(dep.get("세후총액", 0)),
                    "최종 수익률": f"{dep.get('세후수익률(%)', 0.0):.2f}%",
                    "보유일수": f"{dep.get('보유일수', 0):,}일",
                }
            ]
            for sname, r in scenario_results.items():
                days_held = (pd.Timestamp(end_str_summary) - pd.Timestamp(start_date_str)).days
                summary_rows.append({
                    "구분": sname,
                    "최종 평가액": fmt_krw(r["총평가액"]),
                    "최종 수익률": f"{r['총수익률(%)']:+.2f}%",
                    "보유일수": f"{days_held:,}일",
                })
            st.dataframe(
                pd.DataFrame(summary_rows).set_index("구분"),
                use_container_width=True,
            )

        st.markdown("""
        <div class="disclaimer">
            본 자료는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.
            투자는 원금 손실 위험이 있으며, 투자 결정은 고객 본인의 판단과 책임 하에 이루어집니다.
        </div>
        """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# Tab 3: 사용자 정의 포트폴리오
# ═══════════════════════════════════════════════════════════════

with tab3:
    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:12px; margin-bottom:20px;">
        <div style="width:3px; height:28px; background:linear-gradient(180deg,#D4AF37,#C49A20); border-radius:2px;"></div>
        <div>
            <div style="font-size:1.25rem; font-weight:800; color:#0D1B2A; letter-spacing:-0.02em;">사용자 정의 포트폴리오</div>
            <div style="font-size:0.8rem; color:#8895B3; margin-top:2px;">ETF 풀에서 직접 종목을 선택하고 비중을 설정하세요</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ETF 선택
    st.markdown('<div class="section-title">카테고리별 ETF 선택</div>', unsafe_allow_html=True)

    # 카테고리 아이콘
    cat_icons = {"국내주식": "🇰🇷", "해외주식": "🌐", "채권": "🏦", "원자재·대안": "🥇"}

    selected_etfs = []
    # 전체 ETF 목록에 대해 전역 인덱스를 부여하여 key 특수문자 충돌 방지
    _global_etf_idx = 0
    for cat, etfs in ETF_POOL.items():
        icon = cat_icons.get(cat, "")
        with st.expander(f"{icon}  {cat} — {len(etfs)}종목", expanded=False):
            st.markdown(f'<div class="cat-header">{icon} {cat}</div>', unsafe_allow_html=True)
            cat_cols = st.columns(min(len(etfs), 3))
            for idx, etf_name in enumerate(etfs):
                with cat_cols[idx % 3]:
                    if st.checkbox(etf_name, key=f"chk_etf_{_global_etf_idx}"):
                        selected_etfs.append(etf_name)
                _global_etf_idx += 1

    if selected_etfs:
        st.markdown(f'<div class="section-title">비중 설정 — {len(selected_etfs)}종목 선택됨</div>', unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:0.82rem; color:#7A8EAD; margin-bottom:16px;'>"
            "비중 합계가 100%가 아니면 자동으로 정규화됩니다."
            "</div>",
            unsafe_allow_html=True,
        )

        custom_weights = {}
        # 슬라이더 기본값: 최솟값(1)을 보장하여 min_value=1 위반 방지
        default_w = max(1, int(100 // len(selected_etfs)))

        # 슬라이더 3열 배치
        # key에 특수문자((H), ·, &, 공백 등)가 포함될 수 있으므로 인덱스 기반 key 사용
        weight_cols = st.columns(min(len(selected_etfs), 3))
        for i, etf_name in enumerate(selected_etfs):
            col_idx = i % 3
            with weight_cols[col_idx]:
                w = st.slider(
                    etf_name,
                    min_value=1,
                    max_value=100,
                    value=default_w,
                    step=1,
                    key=f"w_etf_{i}",
                    help=f"{etf_name} 포트폴리오 비중 (%)",
                )
                custom_weights[etf_name] = w / 100.0

        total_w = sum(custom_weights.values()) * 100
        bar_color = "#1B6B3A" if 95 <= total_w <= 105 else "#D4AF37" if total_w < 95 else "#C62828"
        bar_pct = min(total_w, 100)

        st.markdown(f"""
        <div style="background:#fff; border-radius:10px; padding:16px 20px; margin:16px 0; box-shadow:0 1px 6px rgba(13,27,42,0.07); border: 1px solid rgba(13,27,42,0.06);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <span style="font-size:0.8rem; font-weight:600; color:#4A5A78; letter-spacing:0.04em; text-transform:uppercase;">현재 비중 합계</span>
                <span style="font-size:1.1rem; font-weight:800; color:{bar_color}; font-variant-numeric:tabular-nums;">{total_w:.1f}%</span>
            </div>
            <div class="weight-bar-wrap">
                <div class="weight-bar-fill" style="width:{bar_pct}%; background:{bar_color};"></div>
            </div>
            <div style="font-size:0.73rem; color:#9AABC2; margin-top:6px;">
                {"합계가 100%에 근접합니다. 계산 시 자동 정규화됩니다." if 95 <= total_w <= 105 else
                 "합계가 100% 미만입니다. 나머지 비중을 배분하세요." if total_w < 95 else
                 "합계가 100%를 초과했습니다. 자동 정규화됩니다."}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 날짜/원금 설정
        st.markdown('<div class="section-title">분석 기간 및 원금 설정</div>', unsafe_allow_html=True)
        use_sidebar = st.checkbox("사이드바 입력값(가입일/원금) 사용", value=True)
        if not use_sidebar:
            c_date = st.date_input(
                "투자 시작일",
                value=date.today() - timedelta(days=365),
                key="custom_date",
            )
            c_principal_man = st.number_input(
                "원금 (만원)", value=1_000, step=100, key="custom_principal"
            )
            c_start = c_date.strftime("%Y-%m-%d")
            c_principal = c_principal_man * 10_000
        else:
            if not run_btn:
                st.markdown("""
                <div style="background:#FFF8E1; border-radius:8px; padding:12px 16px; border-left:3px solid #D4AF37; font-size:0.83rem; color:#7A6010;">
                    사이드바에서 먼저 '비교 분석 시작'을 눌러 기본값을 설정하세요.
                </div>
                """, unsafe_allow_html=True)
                c_start = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
                c_principal = 10_000_000
            else:
                c_start = start_date_str
                c_principal = principal

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        calc_custom = st.button(
            "커스텀 포트폴리오 계산", type="primary", key="calc_custom"
        )

        if calc_custom:
            with st.spinner("커스텀 포트폴리오 계산 중..."):
                custom_result = calc_portfolio_return(custom_weights, c_principal, c_start)

            if "오류" in custom_result:
                st.error(f"계산 오류: {custom_result['오류']}")
            else:
                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                ret = custom_result["총수익률(%)"]
                ret_color = "#1B6B3A" if ret >= 0 else "#C62828"

                # 결과 KPI
                st.markdown(f"""
                <div class="pb-card">
                    <div style="font-size:0.72rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:#8895B3; margin-bottom:16px;">커스텀 포트폴리오 결과</div>
                    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:16px;">
                        <div style="text-align:center;">
                            <div class="kpi-label">총 평가액</div>
                            <div class="kpi-value highlight">{fmt_krw(custom_result['총평가액'])}</div>
                        </div>
                        <div style="text-align:center;">
                            <div class="kpi-label">총 손익</div>
                            <div class="kpi-value" style="color:{ret_color};">{fmt_krw(custom_result['총손익'])}</div>
                        </div>
                        <div style="text-align:center;">
                            <div class="kpi-label">총 수익률</div>
                            <div class="kpi-value" style="color:{ret_color}; font-size:1.3rem;">{ret:+.2f}%</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # 정기예금 비교
                if run_btn and use_sidebar:
                    dep_custom = calc_deposit_return(c_principal, annual_rate, c_start)
                    diff = custom_result["총평가액"] - dep_custom["세후총액"]
                    diff_color = "#1B6B3A" if diff >= 0 else "#C62828"
                    diff_bg = "#E8F5E9" if diff >= 0 else "#FFEBEE"
                    winner = "ETF 포트폴리오 우위" if diff > 0 else "정기예금 우위"

                    st.markdown(f"""
                    <div style="background:{diff_bg}; border-radius:8px; padding:14px 18px; margin-bottom:16px; border-left:3px solid {diff_color}; font-size:0.88rem; color:{diff_color}; font-weight:600;">
                        정기예금 세후 총액 <strong>{fmt_krw(dep_custom['세후총액'])}</strong> 대비
                        <strong>{'+' if diff >= 0 else ''}{int(diff):,}원</strong> — {winner}
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown('<div class="section-title">ETF별 상세 결과</div>', unsafe_allow_html=True)
                display_df = build_detail_df(custom_result["상세"])
                st.dataframe(display_df, use_container_width=True)

                # 도넛 파이 차트
                detail = custom_result["상세"]
                pie_colors = [
                    "#1B3A6B", "#2E5BA8", "#3B82F6", "#60A5FA",
                    "#D4AF37", "#C49A20", "#F0D060", "#10B981",
                    "#EF4444", "#F97316",
                ]
                fig_pie = go.Figure(
                    go.Pie(
                        labels=detail.index.tolist(),
                        values=[
                            float(w.replace("%", ""))
                            for w in detail["비중"].tolist()
                        ],
                        hole=0.42,
                        textinfo="label+percent",
                        marker=dict(
                            colors=pie_colors[:len(detail)],
                            line=dict(color="#ffffff", width=2),
                        ),
                        textfont=dict(family="Pretendard, sans-serif", size=11),
                        hovertemplate="<b>%{label}</b><br>비중: %{percent}<extra></extra>",
                    )
                )
                fig_pie.update_layout(
                    height=340,
                    margin=dict(l=0, r=0, t=16, b=0),
                    showlegend=True,
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="Pretendard, sans-serif"),
                    legend=dict(
                        font=dict(size=11),
                        bgcolor="rgba(255,255,255,0.85)",
                        bordercolor="rgba(13,27,42,0.1)",
                        borderwidth=1,
                    ),
                    annotations=[dict(
                        text="비중",
                        x=0.5, y=0.5,
                        font_size=14,
                        font_color="#1B3A6B",
                        font_family="Pretendard, sans-serif",
                        showarrow=False,
                    )],
                )
                st.plotly_chart(fig_pie, use_container_width=True)

    else:
        st.markdown("""
        <div class="pb-card" style="text-align:center; padding: 40px 28px;">
            <div style="font-size:2.5rem; margin-bottom:16px; opacity:0.4;">💼</div>
            <div style="font-size:1.05rem; font-weight:600; color:#1B3A6B; margin-bottom:8px;">
                ETF를 선택해주세요
            </div>
            <div style="font-size:0.88rem; color:#7A8EAD; line-height:1.6;">
                위 카테고리 항목을 펼쳐 원하는 ETF 종목에 체크하면<br>
                비중 설정 및 수익률 계산을 진행할 수 있습니다.
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div class="disclaimer">
        본 자료는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.
        투자는 원금 손실 위험이 있으며, 투자 결정은 고객 본인의 판단과 책임 하에 이루어집니다.<br>
        ETF 수익률은 운용보수 및 매매비용이 반영되지 않은 단순 가격 수익률 기준입니다.
    </div>
    """, unsafe_allow_html=True)
