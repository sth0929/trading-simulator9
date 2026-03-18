import streamlit as st
import pandas as pd
import os
import random
import uuid
from datetime import datetime, timezone
from supabase import create_client, Client
import json
import streamlit.components.v1 as components

# =====================
# 🔗 Supabase 설정
# =====================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# =====================
# 페이지 기본 설정
# =====================
st.set_page_config(layout="wide")

# =====================
# 👤 닉네임 로그인
# =====================
if "USER_ID" not in st.session_state:
    st.session_state.USER_ID = None

if st.session_state.USER_ID is None:
    st.title("📈 Trading Simulator")
    st.markdown("---")
    _, col_c, _ = st.columns([1, 2, 1])
    with col_c:
        st.subheader("👤 닉네임으로 시작하기")
        st.caption("닉네임은 나만의 고유 ID입니다. 같은 닉네임으로 접속하면 이전 데이터가 이어집니다.")
        nickname = st.text_input("닉네임 입력", placeholder="예: trader_kim, hong1234", max_chars=30)
        if st.button("🚀 시작", use_container_width=True):
            nick = nickname.strip()
            if not nick:
                st.error("닉네임을 입력해주세요.")
            elif len(nick) < 2:
                st.error("닉네임은 2자 이상이어야 합니다.")
            else:
                st.session_state.USER_ID = nick
                st.rerun()
    st.stop()

USER_ID = st.session_state.USER_ID

# =====================
# SESSION_ID: 유저별 현재 게임 세션
# =====================
if "SESSION_ID" not in st.session_state:
    res = (
        supabase.table("session_meta")
        .select("session_id")
        .eq("user_id", USER_ID)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        st.session_state.SESSION_ID = res.data[0]["session_id"]
    else:
        new_id = str(uuid.uuid4())
        st.session_state.SESSION_ID = new_id
        supabase.table("session_meta").insert({
            "session_id": new_id,
            "user_id": USER_ID,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()

SESSION_ID = st.session_state.SESSION_ID

# =====================
# 기본 세션 초기화
# =====================
defaults = {
    "balance": 1000.0,
    "position": None,
    "entry_price": None,
    "entry_capital": 0.0,
    "entry_time": None,
    "entry_balance": 1000.0,
    "leverage": 5,
    "position_ratio": 0.05,
    "trade_count": 0,
    "win": 0,
    "lose": 0,
    "total_pnl": 0.0,
    "trade_markers": [],
    "turn_count": 0,
    "stop_loss_price": None,
    "pending_order": False,
    "limit_price": None,
    "limit_direction": None,
    "performance_loaded": False,
    "start_idx": 0,
    "current_step": 300,
    "df_chart": None,
    "support_levels": [],
    "resistance_levels": [],
    "pending_entry": None,
    "pending_exits": [],
    "support_draw_mode": False,
    "turn_ended": False,
    "price_range_result": None,
    "accumulated_pnl": 0.0,    # ✅ 분할 청산 중 누적 손익 (포지션 단위 승/패 판정용)
    "chart_fit_content": True,  # ✅ 초기/새게임/타임프레임 전환 시 전체 캔들 표시
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =====================
# 유틸 함수
# =====================
def now():
    return datetime.utcnow()

def to_iso(dt):
    return pd.to_datetime(dt).isoformat() if dt else None

def save_trade_log(row: dict):
    row["session_id"] = SESSION_ID
    row["user_id"] = USER_ID
    try:
        supabase.table("trade_log").insert(row).execute()
    except Exception as e:
        st.error(f"❌ DB 저장 실패\n\n**에러:** {e}\n\n**데이터:** {row}")
        raise

def load_trade_log_df():
    res = supabase.table("trade_log").select("*").eq("user_id", USER_ID).order("trade_id").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def load_session_trade_log_df():
    res = supabase.table("trade_log").select("*").eq("session_id", SESSION_ID).order("trade_id").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def restore_performance():
    if st.session_state.performance_loaded:
        return
    df = load_session_trade_log_df()
    if not df.empty:
        st.session_state.total_pnl = float(df["pnl_dollar"].sum())
        st.session_state.balance = float(df.iloc[-1]["balance_after"])

        # ✅ 포지션 단위 승/패: entry_time 기준으로 그룹핑 후 합산 pnl로 판정
        grouped = df.groupby("entry_time")["pnl_dollar"].sum()
        st.session_state.trade_count = len(grouped)
        st.session_state.win  = int((grouped > 0).sum())
        st.session_state.lose = int((grouped <= 0).sum())
    st.session_state.performance_loaded = True

# =====================
# 앱 시작 시 성과 복원 호출
# =====================
# ✅ 새 게임 시작 직후 rerun된 경우: balance를 1000으로 강제 고정
if st.session_state.get("_new_game_balance") is not None:
    st.session_state.balance = st.session_state["_new_game_balance"]
    del st.session_state["_new_game_balance"]

restore_performance()

# =====================
# 차트 데이터 로드
# =====================
def generate_chart(timeframe="4h"):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_FILE = os.path.join(BASE_DIR, "btc_1h.csv")
    df = pd.read_csv(DATA_FILE)
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df["open_time"] = df["open_time"].apply(
        lambda x: pd.to_datetime(x, unit="ms", errors="coerce") if x and x > 1e12 else pd.to_datetime(x, unit="s", errors="coerce")
    )
    df = df.dropna(subset=["open_time"])
    df = df.sort_values("open_time")
    df.set_index("open_time", inplace=True)

    if timeframe == "1D":
        df = df.resample("1D").agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum"
        }).dropna()

    return df

# 타임프레임 기본값 초기화
if "timeframe" not in st.session_state:
    st.session_state.timeframe = "4H"

if st.session_state.df_chart is None:
    st.session_state.df_chart = generate_chart(st.session_state.timeframe)
    # 일봉은 캔들 수가 적으므로 look-back을 100으로 조정
    lookback = 100 if st.session_state.timeframe == "1D" else 300
    max_start = max(0, len(st.session_state.df_chart) - lookback - 50)
    st.session_state.start_idx = random.randint(0, max_start)
    st.session_state.current_step = lookback

# =====================
# 포지션 관련 함수
# =====================
def reset_position():
    st.session_state.position = None
    st.session_state.entry_price = None
    st.session_state.entry_capital = 0
    st.session_state.initial_capital = 0.0  # ✅ 최초 진입 원금 초기화
    st.session_state.entry_time = None
    st.session_state.stop_loss_price = None
    st.session_state.entry_balance = st.session_state.balance
    st.session_state.pending_exits = []     # ✅ 포지션 초기화 시 지정가 청산도 초기화
    st.session_state.accumulated_pnl = 0.0  # ✅ 포지션 단위 누적 손익 초기화

def open_position(pos, price, capital, leverage, position_ratio):
    st.session_state.position = pos
    st.session_state.entry_price = price
    st.session_state.entry_capital = capital
    st.session_state.initial_capital = capital  # ✅ 최초 진입 원금 (수익률 기준)
    st.session_state.leverage = leverage
    st.session_state.position_ratio = position_ratio
    st.session_state.entry_balance = st.session_state.balance

    row = st.session_state.df_chart.iloc[
        st.session_state.start_idx + st.session_state.current_step - 1
    ]
    entry_time = int(row.name.timestamp())
    st.session_state.entry_time = entry_time

    st.session_state.trade_markers.append({
        "time": entry_time,
        "label": pos,
        "color": "green" if pos == "LONG" else "red",
        "symbol": "arrow"
    })

def close_position(exit_price, reason="MANUAL EXIT", ratio=1.0):
    if st.session_state.position is None:
        return

    exit_ts = int(
        st.session_state.df_chart.iloc[
            st.session_state.start_idx + st.session_state.current_step - 1
        ].name.timestamp()
    )

    entry = st.session_state.entry_price
    total_amt = st.session_state.entry_capital
    pos = st.session_state.position
    lev = st.session_state.leverage

    close_amt = total_amt * ratio

    pnl = ((exit_price - entry) / entry * close_amt * lev
           if pos == "LONG"
           else (entry - exit_price) / entry * close_amt * lev)

    st.session_state.balance += pnl
    st.session_state.total_pnl += pnl

    # ✅ 포지션 단위 누적 손익에 이번 분할 pnl 누적
    st.session_state.accumulated_pnl += pnl

    is_full_close = (ratio >= 1.0) or (reason in ("LIQUIDATION", "TIMEOUT EXIT", "AUTO STOP LOSS"))

    if is_full_close:
        # ✅ 분할 청산 포함 전체 합산 pnl 기준으로 승/패 1회만 기록
        final_pnl = st.session_state.accumulated_pnl
        st.session_state.trade_count += 1
        st.session_state.win  += int(final_pnl > 0)
        st.session_state.lose += int(final_pnl <= 0)

    save_trade_log({
        "entry_time": datetime.utcfromtimestamp(st.session_state.entry_time).isoformat(),
        "exit_time": datetime.utcfromtimestamp(exit_ts).isoformat(),
        "play_hours": (exit_ts - st.session_state.entry_time) / 3600,
        "direction": pos,
        "entry_price": entry,
        "exit_price": exit_price,
        "leverage": lev,
        "position_ratio": int(st.session_state.position_ratio * 100),
        "entry_capital": close_amt,
        "pnl_dollar": pnl,
        "balance_after": st.session_state.balance,
        "reason": reason
    })

    st.session_state.trade_markers.append({
        "time": exit_ts,
        "price": exit_price,
        "label": reason,
        "color": "red" if pnl < 0 else "green",
        "symbol": "x"
    })

    if is_full_close:
        reset_position()  # ← accumulated_pnl도 여기서 0으로 리셋됨
    else:
        remaining_amt = total_amt * (1.0 - ratio)
        st.session_state.entry_capital = remaining_amt

# =====================
# 강제청산 + 자동손절 체크
# =====================
def check_liquidation(row):
    if st.session_state.position is None:
        return False

    entry = st.session_state.entry_price
    lev   = st.session_state.leverage
    pos   = st.session_state.position
    amt   = st.session_state.entry_capital

    # ── 1. 강제청산가 (증거금 100% 소진)
    if pos == "LONG":
        liq_price = entry * (1 - 1 / lev)
        if float(row["low"]) <= liq_price:
            close_position(liq_price, reason="LIQUIDATION")
            return True
    else:
        liq_price = entry * (1 + 1 / lev)
        if float(row["high"]) >= liq_price:
            close_position(liq_price, reason="LIQUIDATION")
            return True

    # ── 2. 자동손절: 현재 잔고 2% 초과손실
    if amt > 0:
        max_loss = st.session_state.balance * 0.03
        price_change_stop = max_loss / (amt * lev)

        if pos == "LONG":
            stop_price = entry * (1 - price_change_stop)
            if float(row["low"]) <= stop_price:
                close_position(stop_price, reason="AUTO STOP LOSS")
                return True
        else:
            stop_price = entry * (1 + price_change_stop)
            if float(row["high"]) >= stop_price:
                close_position(stop_price, reason="AUTO STOP LOSS")
                return True

    return False

# =====================
# 롱/숏별 통계 함수 ✅ NEW
# =====================
def get_direction_stats():
    df = load_session_trade_log_df()
    if df.empty:
        return {}
    result = {}
    for direction in ["LONG", "SHORT"]:
        sub = df[df["direction"] == direction]
        if sub.empty:
            result[direction] = None
            continue

        # ✅ 포지션 단위 집계: entry_time으로 그룹핑
        grp_pnl = sub.groupby("entry_time")["pnl_dollar"].sum()      # 포지션별 최종 합산 손익
        grp_capital = sub.groupby("entry_time")["entry_capital"].sum()  # 분할 청산 합산 = 최초 원금

        total = len(grp_pnl)
        wins = int((grp_pnl > 0).sum())
        winrate = wins / total * 100
        avg_ret = (grp_pnl / grp_capital * 100).mean()
        total_pnl = grp_pnl.sum()

        result[direction] = {
            "total": total,
            "wins": wins,
            "winrate": winrate,
            "avg_ret": avg_ret,
            "total_pnl": total_pnl,
        }
    return result

def get_trade_return_stats():
    df = load_session_trade_log_df()
    if df.empty:
        return 0.0, 0.0, 0.0

    # ✅ 포지션 단위 집계: entry_time 기준으로 그룹핑
    grp_pnl     = df.groupby("entry_time")["pnl_dollar"].sum()       # 포지션별 최종 합산 손익
    grp_capital = df.groupby("entry_time")["entry_capital"].sum()    # 분할 청산 합산 = 최초 원금
    grp_ret     = grp_pnl / grp_capital * 100

    overall_avg = float(grp_ret.mean())
    win_avg     = float(grp_ret[grp_ret > 0].mean())  if (grp_ret > 0).any()  else 0.0
    loss_avg    = float(grp_ret[grp_ret <= 0].mean()) if (grp_ret <= 0).any() else 0.0
    return overall_avg, win_avg, loss_avg

# =====================
# 메인 UI
# =====================
st.title("📈 Trading Simulator")

MAX_TURNS = 50

# =====================
# ⏱ 턴 종료 처리
# =====================
if st.session_state.turn_count >= MAX_TURNS:

    if "turn_ended" not in st.session_state:
        st.session_state.turn_ended = False

    if not st.session_state.turn_ended and st.session_state.position is not None:
        row = st.session_state.df_chart.iloc[
            st.session_state.start_idx + st.session_state.current_step - 1
        ]
        final_price = float(row["close"])
        close_position(final_price, reason="TIMEOUT EXIT")
        st.session_state.performance_loaded = False
        restore_performance()

    st.session_state.turn_ended = True

    st.warning("🛑 최대 50턴이 종료되었습니다.")

    if st.button("🔁 새 매매 시작"):
        _lookback = 100 if st.session_state.timeframe == "1D" else 300
        _max_start = max(0, len(st.session_state.df_chart) - _lookback - 50)
        st.session_state.start_idx = random.randint(0, _max_start)
        st.session_state.current_step = _lookback
        st.session_state.turn_count = 0
        st.session_state.pending_entry = None
        st.session_state.trade_markers = []
        st.session_state.support_levels = []
        st.session_state.resistance_levels = []
        st.session_state.price_range_result = None
        reset_position()
        st.session_state.turn_ended = False
        st.query_params.clear()   # ✅ URL에 남은 support_all 파라미터 제거
        st.rerun()

else:
    # 차트 오른쪽 아래 정렬을 위해 빈 컬럼 + 버튼 컬럼
    _col_empty, _col_turns, _col_btn = st.columns([4, 2, 1])
    with _col_turns:
        st.markdown(
            f"<div style='text-align:right; padding-top:6px; color:#888; font-size:13px;'>⏳ 남은 턴: <b>{MAX_TURNS - st.session_state.turn_count}</b> / {MAX_TURNS}</div>",
            unsafe_allow_html=True
        )
    with _col_btn:
        next_clicked = st.button("▶ Next", key="next_candle", use_container_width=True)

    if next_clicked:
        st.session_state.current_step += 1
        st.session_state.turn_count += 1

        target_idx = st.session_state.start_idx + st.session_state.current_step - 1
        if target_idx >= len(st.session_state.df_chart):
            st.warning("⚠️ 데이터 끝에 도달했습니다. 새 게임을 시작해주세요.")
            st.stop()

        row = st.session_state.df_chart.iloc[target_idx]

        # 📌 지정가 진입 체크
        if st.session_state.pending_entry is not None:
            limit_price = st.session_state.pending_entry["price"]
            direction = st.session_state.pending_entry["dir"]
            hit = False
            if direction == "LONG" and row["low"] <= limit_price:
                hit = True
            if direction == "SHORT" and row["high"] >= limit_price:
                hit = True
            if hit:
                open_position(
                    direction,
                    limit_price,
                    st.session_state.balance * st.session_state.position_ratio,
                    st.session_state.leverage,
                    st.session_state.position_ratio
                )
                st.session_state.pending_entry = None

        # ✅ 지정가 청산 체크
        if st.session_state.position is not None and st.session_state.pending_exits:
            remaining = []
            for ex in st.session_state.pending_exits:
                ex_price = ex["price"]
                ex_ratio = ex["ratio"]
                ex_label = ex["label"]
                hit = False
                if st.session_state.position == "LONG" and row["high"] >= ex_price:
                    hit = True
                if st.session_state.position == "SHORT" and row["low"] <= ex_price:
                    hit = True
                if hit and st.session_state.position is not None:
                    close_position(ex_price, reason=f"LIMIT EXIT ({ex_label})", ratio=ex_ratio)
                else:
                    remaining.append(ex)
            st.session_state.pending_exits = remaining

        # 🔴 강제청산 + 자동손절 체크
        liquidated = check_liquidation(row)
        if liquidated:
            st.session_state.pending_entry = None
            st.session_state.pending_exits = []

        st.rerun()

# =====================
# 데이터 슬라이싱
# =====================
start = st.session_state.start_idx
end = start + st.session_state.current_step
df_view = st.session_state.df_chart.iloc[start:end]
current_price = df_view["close"].iloc[-1]

# =====================
# 📩 JS → Streamlit: 지지선 전체 목록 수신
# =====================
params = st.query_params

if "support_all" in params:
    raw = params["support_all"]
    if isinstance(raw, list):
        raw = raw[0]
    try:
        prices = json.loads(raw)
        st.session_state.support_levels = [float(p) for p in prices if p > 0]
    except Exception:
        pass
    st.query_params.clear()
    st.rerun()

elif "support_price" in params:
    price = float(params["support_price"][0] if isinstance(params["support_price"], list) else params["support_price"])
    if price not in st.session_state.support_levels:
        st.session_state.support_levels.append(price)
    st.query_params.clear()
    st.rerun()

# =====================
# 차트 표시
# =====================
df_reset = df_view.reset_index()

candles = df_reset.apply(
    lambda r: {
        "time": int(pd.to_datetime(r["open_time"]).timestamp()),
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
        "volume": float(r.get("volume", 0))
    },
    axis=1
).tolist()

markers = [
    {
        "time": m["time"],
        "position": "belowBar" if m["label"] == "LONG" else "aboveBar",
        "color": m["color"],
        "shape": "arrowUp" if m["label"] == "LONG" else "arrowDown",
        "text": m["label"]
    } for m in st.session_state.trade_markers
]

support_lines_js = [
    {"price": float(p)} for p in st.session_state.support_levels
]

html_template = open("chart.html", encoding="utf-8").read()
html_template = html_template.replace("__CANDLE_DATA__", json.dumps(candles))
html_template = html_template.replace("__MARKER_DATA__", json.dumps(markers))
html_template = html_template.replace("__SUPPORT_LINES__", json.dumps(support_lines_js))
html_template = html_template.replace("__FIT_CONTENT__", "true" if st.session_state.get("chart_fit_content", True) else "false")
st.session_state.chart_fit_content = False  # ✅ 이후 렌더링은 줌 상태 유지

components.html(html_template, height=420)

# 남은 턴수는 chart.html 하단에 표시됨

# ----------------------
# 포지션 손익 계산 및 표시
# ----------------------
if st.session_state.position is not None:
    entry = st.session_state.entry_price
    amt = st.session_state.entry_capital
    lev = st.session_state.leverage

    if st.session_state.position == "LONG":
        price_change = (current_price - entry) / entry
    else:
        price_change = (entry - current_price) / entry

    pnl_leveraged_pct = price_change * lev * 100
    profit_leveraged = amt * price_change * lev

    if st.session_state.position == "LONG":
        liq_price = entry * (1 - 1 / lev)
    else:
        liq_price = entry * (1 + 1 / lev)

    if amt > 0:
        price_change_stop = (st.session_state.balance * 0.03) / (amt * lev)
        if st.session_state.position == "LONG":
            auto_stop_price = entry * (1 - price_change_stop)
        else:
            auto_stop_price = entry * (1 + price_change_stop)
    else:
        auto_stop_price = None

    st.markdown(f"""
### 📊 현재 포지션
- 포지션: **{st.session_state.position}**
- 진입가: **{entry:,.2f}**
- 현재가: **{current_price:,.2f}**
- 🚨 강제청산가: <span style="color:orange;font-weight:bold;">{liq_price:,.2f}</span>
- 🛑 자동손절가 <span style="font-size:0.85em;color:gray;">(현재잔고 2%)</span>: <span style="color:#e05c5c;font-weight:bold;">{f'{auto_stop_price:,.2f}' if auto_stop_price else 'N/A'}</span>
- 진입 금액: **${amt:,.2f}**
- 레버리지: **{lev}x**
- 손익률 (레버리지):
  <span style="color:{'green' if pnl_leveraged_pct >= 0 else 'red'};">
  **{pnl_leveraged_pct:+.2f}%**
  </span>
- 예상 수익 (레버리지):
  <span style="color:{'green' if profit_leveraged >= 0 else 'red'};">
  **${profit_leveraged:+,.2f}**
  </span>
""", unsafe_allow_html=True)


# =====================
# 🔧 사이드바
# =====================
st.sidebar.markdown(f"👤 **{USER_ID}** 님")
if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
st.sidebar.divider()

st.sidebar.subheader("⚙️ 거래 설정")
st.sidebar.info("레버리지: **20x** (고정)  |  자동손절: **시드 3%**")
st.session_state.leverage = 20

# =====================
# 📊 타임프레임 선택
# =====================
st.sidebar.subheader("📊 타임프레임")
tf_choice = st.sidebar.radio(
    "캔들 기준",
    options=["4H", "1D"],
    index=0 if st.session_state.timeframe == "4H" else 1,
    horizontal=True
)

if tf_choice != st.session_state.timeframe:
    # ✅ 현재 차트의 마지막 캔들 시간 저장 (타임프레임 전환 후 같은 시점으로 맞추기 위해)
    cur_last_time = None
    if st.session_state.df_chart is not None:
        cur_end_idx = st.session_state.start_idx + st.session_state.current_step - 1
        if cur_end_idx < len(st.session_state.df_chart):
            cur_last_time = st.session_state.df_chart.index[cur_end_idx]

    st.session_state.timeframe = tf_choice
    new_df = generate_chart(tf_choice)
    st.session_state.df_chart = new_df
    lookback = 100 if tf_choice == "1D" else 300

    # ✅ 이전 마지막 캔들 시간과 가장 가까운 위치를 새 데이터에서 찾기
    if cur_last_time is not None and cur_last_time in new_df.index:
        new_end_pos = new_df.index.get_loc(cur_last_time)
    elif cur_last_time is not None:
        # 정확히 없으면 가장 가까운 날짜 찾기
        new_end_pos = new_df.index.searchsorted(cur_last_time)
        new_end_pos = min(new_end_pos, len(new_df) - 1)
    else:
        new_end_pos = lookback - 1

    new_start = max(0, new_end_pos - lookback + 1)
    # 뒤에 최소 50개 캔들이 남도록 보정
    if new_start + lookback + 50 > len(new_df):
        new_start = max(0, len(new_df) - lookback - 50)

    st.session_state.start_idx = new_start
    st.session_state.current_step = lookback
    # ✅ 타임프레임 전환: 포지션/마커/지정가/지지선 등 매매 상태 전부 유지
    st.session_state.price_range_result = None
    st.session_state.chart_fit_content = True  # ✅ 타임프레임 전환: 전체 캔들 표시
    st.query_params.clear()
    st.rerun()

# =====================
# 💰 진입 비중
# =====================
st.sidebar.subheader("💰 진입 비중")
ratio_choice = st.sidebar.radio(
    "잔고 대비 진입 비중",
    options=["5%", "10%"],
    index=0 if st.session_state.position_ratio <= 0.05 else 1,
    horizontal=True
)
st.session_state.position_ratio = 0.05 if ratio_choice == "5%" else 0.10

# =====================
# 📏 지지선
# =====================
st.sidebar.subheader("📏 지지선")
st.sidebar.caption("차트에서 ✏️ 버튼으로 그리기 모드 활성화 후\n클릭으로 추가 · 드래그로 이동 · 더블클릭으로 삭제")

if st.session_state.support_levels:
    st.sidebar.divider()
    st.sidebar.caption("🟦 지지선 목록")
    for idx, support in enumerate(st.session_state.support_levels):
        col1, col2 = st.sidebar.columns([3, 1])
        col1.write(f"{support:,.2f}")
        if col2.button("❌", key=f"del_support_{idx}"):
            st.session_state.support_levels.pop(idx)
            st.rerun()
else:
    st.sidebar.info("등록된 지지선 없음")

# =====================
# 📌 지정가 진입
# =====================
st.sidebar.subheader("📌 지정가 진입")
limit_price = st.sidebar.number_input("지정가 가격", value=0.0, step=1.0)
limit_dir = st.sidebar.selectbox("방향", ["LONG", "SHORT"])

col1, col2 = st.sidebar.columns(2)
if col1.button("지정가 진입"):
    st.session_state.pending_entry = {
        "price": limit_price,
        "dir": limit_dir
    }

if col2.button("지정가 취소"):
    st.session_state.pending_entry = None

if st.session_state.pending_entry:
    st.sidebar.info(
        f"📌 지정가 대기중\n"
        f"가격: {st.session_state.pending_entry['price']}\n"
        f"방향: {st.session_state.pending_entry['dir']}"
    )
else:
    st.sidebar.info("📌 지정가 대기 없음")

# =====================
# 🚀 즉시 진입
# =====================
st.sidebar.subheader("🚀 즉시 진입")

if st.session_state.position is None:
    capital = st.session_state.balance * st.session_state.position_ratio

    if st.sidebar.button("🟢 LONG 진입"):
        open_position(
            "LONG",
            current_price,
            capital,
            st.session_state.leverage,
            st.session_state.position_ratio
        )
        st.rerun()

    if st.sidebar.button("🔴 SHORT 진입"):
        open_position(
            "SHORT",
            current_price,
            capital,
            st.session_state.leverage,
            st.session_state.position_ratio
        )
        st.rerun()
else:
    st.sidebar.success(f"보유 포지션: {st.session_state.position}")

# =====================
# 📤 포지션 청산
# =====================
if st.session_state.position:
    st.sidebar.subheader("📤 포지션 청산")

    # 즉시 청산
    if st.sidebar.button("25% 청산"):
        close_position(current_price, "25% EXIT", ratio=0.25)
        st.rerun()

    if st.sidebar.button("50% 청산"):
        close_position(current_price, "50% EXIT", ratio=0.5)
        st.rerun()

    if st.sidebar.button("전체 청산"):
        close_position(current_price, "FULL EXIT", ratio=1.0)
        st.rerun()

    # ✅ 지정가 청산
    st.sidebar.markdown("---")
    st.sidebar.caption("📌 지정가 청산 예약")

    exit_price_input = st.sidebar.number_input(
        "청산 지정가",
        value=float(current_price),
        step=1.0,
        key="exit_limit_price"
    )
    exit_ratio_choice = st.sidebar.radio(
        "청산 비중",
        ["25%", "50%", "100%"],
        horizontal=True,
        key="exit_ratio_radio"
    )
    exit_ratio_map = {"25%": 0.25, "50%": 0.5, "100%": 1.0}

    if st.sidebar.button("✅ 지정가 청산 예약"):
        st.session_state.pending_exits.append({
            "price": exit_price_input,
            "ratio": exit_ratio_map[exit_ratio_choice],
            "label": exit_ratio_choice
        })
        st.rerun()

    # 지정가 청산 대기 목록
    if st.session_state.pending_exits:
        st.sidebar.caption("🕐 지정가 청산 대기 목록")
        for i, ex in enumerate(st.session_state.pending_exits):
            col1, col2 = st.sidebar.columns([3, 1])
            col1.write(f"{ex['price']:,.2f} ({ex['label']})")
            if col2.button("❌", key=f"del_exit_{i}"):
                st.session_state.pending_exits.pop(i)
                st.rerun()
    else:
        st.sidebar.info("📌 지정가 청산 대기 없음")

# ===============================
# 🔁 새 게임 시작
# ===============================
st.sidebar.divider()
if st.sidebar.button("🔄 새 게임 시작"):

    new_session_id = str(uuid.uuid4())
    st.session_state.SESSION_ID = new_session_id
    SESSION_ID = new_session_id

    supabase.table("session_meta").insert({
        "session_id": new_session_id,
        "user_id": USER_ID,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }).execute()

    lookback = 100 if st.session_state.timeframe == "1D" else 300
    max_start = max(0, len(st.session_state.df_chart) - lookback - 50)
    st.session_state.start_idx = random.randint(0, max_start)
    st.session_state.current_step = lookback
    st.session_state.turn_count = 0
    st.session_state.pending_entry = None
    st.session_state.pending_exits = []
    st.session_state.trade_markers = []
    st.session_state.support_levels = []
    st.session_state.resistance_levels = []
    st.session_state.price_range_result = None
    st.session_state.turn_ended = False
    st.query_params.clear()   # ✅ URL에 남은 support_all 파라미터 제거

    reset_position()

    st.session_state.balance = 1000.0
    st.session_state.total_pnl = 0.0
    st.session_state.trade_count = 0
    st.session_state.win = 0
    st.session_state.lose = 0
    st.session_state.performance_loaded = True  # ✅ DB 복원 막기 (새 게임은 0부터 시작)
    st.session_state.chart_fit_content = True   # ✅ 새 게임: 전체 캔들 표시

    st.rerun()

# =====================
# 📊 누적 성과 표시
# =====================
total_trades = st.session_state.win + st.session_state.lose
winrate = (st.session_state.win / total_trades * 100) if total_trades else 0

avg_return, win_avg_return, loss_avg_return = get_trade_return_stats()

# ✅ 롱/숏별 통계
dir_stats = get_direction_stats()
long_s = dir_stats.get("LONG")
short_s = dir_stats.get("SHORT")

if long_s:
    long_block = f"""
#### 🟢 LONG
- 매매 수: {long_s['total']}건 &nbsp; (승 {long_s['wins']} / 패 {long_s['total'] - long_s['wins']})
- 승률: {long_s['winrate']:.1f}%
- 평균 수익률: <span style="color:{'green' if long_s['avg_ret'] >= 0 else 'red'};">{long_s['avg_ret']:+.2f}%</span>
- 누적 손익: <span style="color:{'green' if long_s['total_pnl'] >= 0 else 'red'};">${long_s['total_pnl']:+,.2f}</span>
"""
else:
    long_block = "#### 🟢 LONG\n- 기록 없음"

if short_s:
    short_block = f"""
#### 🔴 SHORT
- 매매 수: {short_s['total']}건 &nbsp; (승 {short_s['wins']} / 패 {short_s['total'] - short_s['wins']})
- 승률: {short_s['winrate']:.1f}%
- 평균 수익률: <span style="color:{'green' if short_s['avg_ret'] >= 0 else 'red'};">{short_s['avg_ret']:+.2f}%</span>
- 누적 손익: <span style="color:{'green' if short_s['total_pnl'] >= 0 else 'red'};">${short_s['total_pnl']:+,.2f}</span>
"""
else:
    short_block = "#### 🔴 SHORT\n- 기록 없음"

st.markdown(f"""
## 📊 누적 성과
- 승 : {st.session_state.win} / 패 : {st.session_state.lose}
- 승률: {winrate:.2f}%
- 누적 손익: ${st.session_state.total_pnl:,.2f}
- 매매 평균 수익률: {avg_return:+.2f}%
- 🟢 승리 트레이드 평균 수익률: {win_avg_return:+.2f}%
- 🔴 패배 트레이드 평균 손실률: {loss_avg_return:+.2f}%

---
{long_block}

{short_block}
""", unsafe_allow_html=True)

st.metric("잔고", f"${st.session_state.balance:,.2f}")
st.metric("총 손익", f"${st.session_state.total_pnl:,.2f}")
