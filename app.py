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
# SESSION_ID
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
    "leverage": 20,
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
    "accumulated_pnl": 0.0,
    "chart_fit_content": True,
    "_pending_tf": None,
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
        grouped = df.groupby("entry_time")["pnl_dollar"].sum()
        st.session_state.trade_count = len(grouped)
        st.session_state.win  = int((grouped > 0).sum())
        st.session_state.lose = int((grouped <= 0).sum())
    st.session_state.performance_loaded = True

if st.session_state.get("_new_game_balance") is not None:
    st.session_state.balance = st.session_state["_new_game_balance"]
    del st.session_state["_new_game_balance"]

restore_performance()

# =====================
# 타임프레임별 lookback
# =====================
def get_lookback(timeframe):
    if timeframe == "1W":
        return 60
    elif timeframe == "1D":
        return 100
    else:  # 4H
        return 300

# =====================
# 차트 데이터 로드
# =====================
def generate_chart(timeframe="4H"):
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
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna()
    elif timeframe == "1W":
        df = df.resample("1W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna()
    return df

if "timeframe" not in st.session_state:
    st.session_state.timeframe = "4H"

if st.session_state.df_chart is None:
    st.session_state.df_chart = generate_chart(st.session_state.timeframe)
    lookback = get_lookback(st.session_state.timeframe)
    max_start = max(0, len(st.session_state.df_chart) - lookback - 50)
    st.session_state.start_idx = random.randint(0, max_start)
    st.session_state.current_step = lookback

# =====================
# 타임프레임 전환 처리 (rerun 안정화)
# =====================
if st.session_state.get("_pending_tf") is not None:
    tf_choice = st.session_state._pending_tf
    st.session_state._pending_tf = None

    cur_df = st.session_state.df_chart
    cur_end_idx = min(
        st.session_state.start_idx + st.session_state.current_step - 1,
        len(cur_df) - 1
    )
    cur_last_time = cur_df.index[cur_end_idx]

    st.session_state.timeframe = tf_choice
    new_df = generate_chart(tf_choice)
    st.session_state.df_chart = new_df
    lookback = get_lookback(tf_choice)

    new_end_pos = new_df.index.searchsorted(cur_last_time, side="right") - 1
    new_end_pos = max(lookback - 1, min(new_end_pos, len(new_df) - 2))

    st.session_state.start_idx    = max(0, new_end_pos - lookback + 1)
    st.session_state.current_step = lookback
    st.session_state.price_range_result = None
    st.session_state.chart_fit_content  = True
    st.query_params.clear()
    st.rerun()

# =====================
# 포지션 관련 함수
# =====================
def reset_position():
    st.session_state.position = None
    st.session_state.entry_price = None
    st.session_state.entry_capital = 0
    st.session_state.initial_capital = 0.0
    st.session_state.entry_time = None
    st.session_state.stop_loss_price = None
    st.session_state.entry_balance = st.session_state.balance
    st.session_state.pending_exits = []
    st.session_state.accumulated_pnl = 0.0

def open_position(pos, price, capital, leverage, position_ratio):
    st.session_state.position = pos
    st.session_state.entry_price = price
    st.session_state.entry_capital = capital
    st.session_state.initial_capital = capital
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
    st.session_state.accumulated_pnl += pnl
    is_full_close = (ratio >= 1.0) or (reason in ("LIQUIDATION", "TIMEOUT EXIT"))
    if is_full_close:
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
        reset_position()
    else:
        st.session_state.entry_capital = total_amt * (1.0 - ratio)

# =====================
# 강제청산 체크
# =====================
def check_liquidation(row):
    if st.session_state.position is None:
        return False
    entry = st.session_state.entry_price
    lev   = st.session_state.leverage
    pos   = st.session_state.position
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
    return False

# =====================
# 롱/숏별 통계
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
        grp_pnl     = sub.groupby("entry_time")["pnl_dollar"].sum()
        grp_capital = sub.groupby("entry_time")["entry_capital"].sum()
        total    = len(grp_pnl)
        wins     = int((grp_pnl > 0).sum())
        winrate  = wins / total * 100
        avg_ret  = (grp_pnl / grp_capital * 100).mean()
        total_pnl = grp_pnl.sum()
        result[direction] = {
            "total": total, "wins": wins,
            "winrate": winrate, "avg_ret": avg_ret, "total_pnl": total_pnl,
        }
    return result

def get_trade_return_stats():
    df = load_session_trade_log_df()
    if df.empty:
        return 0.0, 0.0, 0.0
    grp_pnl     = df.groupby("entry_time")["pnl_dollar"].sum()
    grp_capital = df.groupby("entry_time")["entry_capital"].sum()
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
# 턴 종료 처리
# =====================
if st.session_state.turn_count >= MAX_TURNS:
    if "turn_ended" not in st.session_state:
        st.session_state.turn_ended = False
    if not st.session_state.turn_ended and st.session_state.position is not None:
        row = st.session_state.df_chart.iloc[
            st.session_state.start_idx + st.session_state.current_step - 1
        ]
        close_position(float(row["close"]), reason="TIMEOUT EXIT")
        st.session_state.performance_loaded = False
        restore_performance()
    st.session_state.turn_ended = True
    st.warning("🛑 최대 50턴이 종료되었습니다.")
    if st.button("🔁 새 매매 시작"):
        _lookback = get_lookback(st.session_state.timeframe)
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
        st.query_params.clear()
        st.rerun()
else:
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

        if st.session_state.pending_entry is not None:
            limit_price = st.session_state.pending_entry["price"]
            direction   = st.session_state.pending_entry["dir"]
            hit = (direction == "LONG" and row["low"] <= limit_price) or \
                  (direction == "SHORT" and row["high"] >= limit_price)
            if hit:
                open_position(direction, limit_price,
                              st.session_state.balance * st.session_state.position_ratio,
                              st.session_state.leverage, st.session_state.position_ratio)
                st.session_state.pending_entry = None

        if st.session_state.position is not None and st.session_state.pending_exits:
            remaining = []
            for ex in st.session_state.pending_exits:
                hit = (st.session_state.position == "LONG"  and row["high"] >= ex["price"]) or \
                      (st.session_state.position == "SHORT" and row["low"]  <= ex["price"])
                if hit and st.session_state.position is not None:
                    close_position(ex["price"], reason=f"LIMIT EXIT ({ex['label']})", ratio=ex["ratio"])
                else:
                    remaining.append(ex)
            st.session_state.pending_exits = remaining

        liquidated = check_liquidation(row)
        if liquidated:
            st.session_state.pending_entry = None
            st.session_state.pending_exits = []

        st.rerun()

# =====================
# 데이터 슬라이싱
# =====================
start = st.session_state.start_idx
end   = start + st.session_state.current_step
df_view = st.session_state.df_chart.iloc[start:end]
current_price = df_view["close"].iloc[-1]

# =====================
# JS → Streamlit: 지지선 수신
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
        "time":   int(pd.to_datetime(r["open_time"]).timestamp()),
        "open":   float(r["open"]),
        "high":   float(r["high"]),
        "low":    float(r["low"]),
        "close":  float(r["close"]),
        "volume": float(r.get("volume", 0))
    }, axis=1
).tolist()

markers = [
    {
        "time":     m["time"],
        "position": "belowBar" if m["label"] == "LONG" else "aboveBar",
        "color":    m["color"],
        "shape":    "arrowUp" if m["label"] == "LONG" else "arrowDown",
        "text":     m["label"]
    } for m in st.session_state.trade_markers
]

support_lines_js = [{"price": float(p)} for p in st.session_state.support_levels]

entry_price_val = float(st.session_state.entry_price) if st.session_state.entry_price else 0.0

html_template = open("chart.html", encoding="utf-8").read()
html_template = html_template.replace("__CANDLE_DATA__",     json.dumps(candles))
html_template = html_template.replace("__MARKER_DATA__",     json.dumps(markers))
html_template = html_template.replace("__SUPPORT_LINES__",   json.dumps(support_lines_js))
html_template = html_template.replace("__AUTO_STOP_PRICE__", json.dumps(0.0))
html_template = html_template.replace("__ENTRY_PRICE__",     json.dumps(entry_price_val))
html_template = html_template.replace("__FIT_CONTENT__",     "true" if st.session_state.get("chart_fit_content", True) else "false")
st.session_state.chart_fit_content = False

components.html(html_template, height=420)

# ----------------------
# 포지션 손익 표시
# ----------------------
if st.session_state.position is not None:
    entry = st.session_state.entry_price
    amt   = st.session_state.entry_capital
    lev   = st.session_state.leverage

    price_change      = (current_price - entry) / entry if st.session_state.position == "LONG" else (entry - current_price) / entry
    pnl_leveraged_pct = price_change * lev * 100
    profit_leveraged  = amt * price_change * lev
    liq_price         = entry * (1 - 1/lev) if st.session_state.position == "LONG" else entry * (1 + 1/lev)

    st.markdown(f"""
### 📊 현재 포지션
- 포지션: **{st.session_state.position}**
- 진입가: **{entry:,.2f}**
- 현재가: **{current_price:,.2f}**
- 🚨 강제청산가: <span style="color:orange;font-weight:bold;">{liq_price:,.2f}</span>
- 진입 금액: **${amt:,.2f}**
- 레버리지: **{lev}x**
- 손익률 (레버리지): <span style="color:{'green' if pnl_leveraged_pct >= 0 else 'red'};"> **{pnl_leveraged_pct:+.2f}%** </span>
- 예상 수익 (레버리지): <span style="color:{'green' if profit_leveraged >= 0 else 'red'};"> **${profit_leveraged:+,.2f}** </span>
""", unsafe_allow_html=True)

# =====================
# 사이드바
# =====================
st.sidebar.markdown(f"👤 **{USER_ID}** 님")
if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
st.sidebar.divider()

# =====================
# 🧮 레버리지 계산기
# =====================
st.sidebar.subheader("🧮 레버리지 계산기")

balance_now      = st.session_state.balance
position_ratio   = st.session_state.position_ratio
invest_amount    = balance_now * position_ratio   # 실제 투입금액
max_loss_amount  = balance_now * 0.03             # 시드의 3% = 허용 최대 손실금

calc_entry = st.sidebar.number_input(
    "진입가", value=float(current_price), step=1.0, key="calc_entry", format="%.1f"
)
calc_sl = st.sidebar.number_input(
    "손절가", value=float(current_price) * 0.97, step=1.0, key="calc_sl", format="%.1f"
)

if calc_entry > 0 and calc_sl > 0 and calc_entry != calc_sl:
    sl_distance_pct = abs(calc_entry - calc_sl) / calc_entry  # 손절 거리 비율

    # 핵심 공식:
    # 손실금 = 투입금액 × 레버리지 × 손절거리%
    # 최대손실 = 투입금액 × 레버리지 × 손절거리%
    # → 레버리지 = 최대손실금 / (투입금액 × 손절거리%)
    required_lev = max_loss_amount / (invest_amount * sl_distance_pct)

    actual_loss   = invest_amount * required_lev * sl_distance_pct  # = max_loss_amount
    sl_dir_label  = "LONG용 (손절 < 진입)" if calc_sl < calc_entry else "SHORT용 (손절 > 진입)"
    lev_color     = "green" if required_lev <= 10 else ("orange" if required_lev <= 20 else "red")

    st.sidebar.markdown(f"""
<div style="background:#1a1a2e; border:1px solid #333; border-radius:10px; padding:14px; margin-top:6px;">
  <div style="color:#888; font-size:12px; margin-bottom:10px;">{sl_dir_label}</div>

  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
    <span style="color:#aaa; font-size:13px;">현재 잔고</span>
    <span style="color:white; font-size:13px;">${balance_now:,.2f}</span>
  </div>
  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
    <span style="color:#aaa; font-size:13px;">진입 비중 ({int(position_ratio*100)}%)</span>
    <span style="color:white; font-size:13px;">${invest_amount:,.2f}</span>
  </div>
  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
    <span style="color:#aaa; font-size:13px;">손절 거리</span>
    <span style="color:white; font-size:13px;">{sl_distance_pct*100:.2f}%</span>
  </div>
  <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
    <span style="color:#aaa; font-size:13px;">허용 최대 손실 (시드 -3%)</span>
    <span style="color:#ff6b6b; font-size:13px;">-${max_loss_amount:,.2f}</span>
  </div>

  <hr style="border-color:#333; margin:0 0 12px 0;">

  <div style="text-align:center;">
    <div style="color:#aaa; font-size:13px; margin-bottom:4px;">적정 레버리지</div>
    <div style="font-size:36px; font-weight:bold; color:{lev_color};">{required_lev:.1f}x</div>
    <div style="color:#ff6b6b; font-size:12px; margin-top:4px;">
      손절 시 예상 손실: -${actual_loss:,.2f} (시드 대비 -3.00%)
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

else:
    st.sidebar.caption("진입가와 손절가를 입력하면 적정 레버리지를 계산합니다.")

st.sidebar.divider()

# =====================
# 거래 설정
# =====================
st.sidebar.subheader("⚙️ 거래 설정")
lev_options = [5, 10, 15, 20]
current_lev = st.session_state.leverage if st.session_state.leverage in lev_options else 20
lev_index   = lev_options.index(current_lev)
is_in_position = st.session_state.position is not None

st.session_state.leverage = st.sidebar.radio(
    "레버리지", options=lev_options, index=lev_index,
    format_func=lambda x: f"{x}x", horizontal=True,
    key="leverage_radio", disabled=is_in_position
)
if is_in_position:
    st.sidebar.caption("⚠️ 포지션 보유 중 레버리지 변경 불가")
st.sidebar.info(f"레버리지: **{st.session_state.leverage}x**")

# 타임프레임
st.sidebar.subheader("📊 타임프레임")
tf_options = ["4H", "1D", "1W"]
tf_choice = st.sidebar.radio(
    "캔들 기준", options=tf_options,
    index=tf_options.index(st.session_state.timeframe),
    horizontal=True
)
if tf_choice != st.session_state.timeframe:
    st.session_state._pending_tf = tf_choice
    st.rerun()

# 진입 비중
st.sidebar.subheader("💰 진입 비중")
ratio_choice = st.sidebar.radio("잔고 대비 진입 비중", options=["5%", "10%"],
                                 index=0 if st.session_state.position_ratio <= 0.05 else 1, horizontal=True)
st.session_state.position_ratio = 0.05 if ratio_choice == "5%" else 0.10

# 지지선
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

# 지정가 진입
st.sidebar.subheader("📌 지정가 진입")
limit_price = st.sidebar.number_input("지정가 가격", value=0.0, step=1.0)
limit_dir   = st.sidebar.selectbox("방향", ["LONG", "SHORT"])
col1, col2  = st.sidebar.columns(2)
if col1.button("지정가 진입"):
    st.session_state.pending_entry = {"price": limit_price, "dir": limit_dir}
if col2.button("지정가 취소"):
    st.session_state.pending_entry = None
if st.session_state.pending_entry:
    st.sidebar.info(f"📌 지정가 대기중\n가격: {st.session_state.pending_entry['price']}\n방향: {st.session_state.pending_entry['dir']}")
else:
    st.sidebar.info("📌 지정가 대기 없음")

# 즉시 진입
st.sidebar.subheader("🚀 즉시 진입")
if st.session_state.position is None:
    capital = st.session_state.balance * st.session_state.position_ratio
    if st.sidebar.button("🟢 LONG 진입"):
        open_position("LONG", current_price, capital, st.session_state.leverage, st.session_state.position_ratio)
        st.rerun()
    if st.sidebar.button("🔴 SHORT 진입"):
        open_position("SHORT", current_price, capital, st.session_state.leverage, st.session_state.position_ratio)
        st.rerun()
else:
    st.sidebar.success(f"보유 포지션: {st.session_state.position}")

# 포지션 청산
if st.session_state.position:
    st.sidebar.subheader("📤 포지션 청산")
    if st.sidebar.button("25% 청산"):
        close_position(current_price, "25% EXIT", ratio=0.25)
        st.rerun()
    if st.sidebar.button("50% 청산"):
        close_position(current_price, "50% EXIT", ratio=0.5)
        st.rerun()
    if st.sidebar.button("전체 청산"):
        close_position(current_price, "FULL EXIT", ratio=1.0)
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.caption("📌 지정가 청산 예약")
    exit_price_input = st.sidebar.number_input("청산 지정가", value=float(current_price), step=1.0, key="exit_limit_price")
    exit_ratio_choice = st.sidebar.radio("청산 비중", ["25%", "50%", "100%"], horizontal=True, key="exit_ratio_radio")
    exit_ratio_map = {"25%": 0.25, "50%": 0.5, "100%": 1.0}
    if st.sidebar.button("✅ 지정가 청산 예약"):
        st.session_state.pending_exits.append({
            "price": exit_price_input,
            "ratio": exit_ratio_map[exit_ratio_choice],
            "label": exit_ratio_choice
        })
        st.rerun()
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

# 새 게임
st.sidebar.divider()
if st.sidebar.button("🔄 새 게임 시작"):
    new_session_id = str(uuid.uuid4())
    st.session_state.SESSION_ID = new_session_id
    SESSION_ID = new_session_id
    supabase.table("session_meta").insert({
        "session_id": new_session_id, "user_id": USER_ID,
        "is_active": True, "created_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    lookback  = get_lookback(st.session_state.timeframe)
    max_start = max(0, len(st.session_state.df_chart) - lookback - 50)
    st.session_state.start_idx    = random.randint(0, max_start)
    st.session_state.current_step = lookback
    st.session_state.turn_count   = 0
    st.session_state.pending_entry  = None
    st.session_state.pending_exits  = []
    st.session_state.trade_markers  = []
    st.session_state.support_levels = []
    st.session_state.resistance_levels = []
    st.session_state.price_range_result = None
    st.session_state.turn_ended = False
    st.query_params.clear()
    reset_position()
    st.session_state.balance  = 1000.0
    st.session_state.total_pnl = 0.0
    st.session_state.trade_count = 0
    st.session_state.win  = 0
    st.session_state.lose = 0
    st.session_state.performance_loaded = True
    st.session_state.chart_fit_content  = True
    st.rerun()

# =====================
# 누적 성과
# =====================
total_trades = st.session_state.win + st.session_state.lose
winrate = (st.session_state.win / total_trades * 100) if total_trades else 0
avg_return, win_avg_return, loss_avg_return = get_trade_return_stats()
dir_stats = get_direction_stats()
long_s  = dir_stats.get("LONG")
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
