import streamlit as st
import pandas as pd
import os
import random
import uuid
from datetime import datetime
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
# SESSION_ID 복원/생성
# =====================
if "SESSION_ID" not in st.session_state:
    res = (
        supabase.table("session_meta")
        .select("session_id")
        .eq("is_active", True)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if res.data:
        st.session_state.SESSION_ID = res.data[0]["session_id"]
    else:
        # 처음 실행 시
        new_id = str(uuid.uuid4())
        st.session_state.SESSION_ID = new_id
        from datetime import datetime, timezone

        supabase.table("session_meta").insert({
            "session_id": new_id,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()



SESSION_ID = st.session_state.SESSION_ID

# =====================
# 페이지 기본 설정
# =====================
st.set_page_config(layout="wide")

# =====================
# 기본 세션 초기화
# =====================
defaults = {
    "balance": 1000.0,
    "position": None,
    "entry_price": None,
    "entry_capital": 0.0,
    "entry_time": None,
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
    "pending_exits": []
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =====================
# 앱 시작 시 성과 복원
# =====================
def restore_performance():
    df = load_trade_log_df()
    if not df.empty:
        st.session_state.trade_count = int(df["trade_id"].max())
        st.session_state.win = int((df["pnl_dollar"] > 0).sum())
        st.session_state.lose = int((df["pnl_dollar"] <= 0).sum())
        st.session_state.total_pnl = float(df["pnl_dollar"].sum())
        st.session_state.balance = float(df.iloc[-1]["balance_after"])
        st.session_state.trade_markers = [
            {
                "time": int(pd.to_datetime(r["entry_time"]).timestamp()),
                "label": r["direction"],
                "color": "green" if r["pnl_dollar"]>0 else "red",
                "symbol": "arrow"
            } for _, r in df.iterrows()
        ]





# =====================
# 유틸 함수
# =====================
def now():
    return datetime.utcnow()

def to_iso(dt):
    return pd.to_datetime(dt).isoformat() if dt else None

def save_trade_log(row: dict):
    row["session_id"] = SESSION_ID
    supabase.table("trade_log").insert(row).execute()

def load_trade_log_df():
    res = supabase.table("trade_log").select("*").eq("session_id", SESSION_ID).order("trade_id").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def restore_performance():
    if st.session_state.performance_loaded:
        return
    df = load_trade_log_df()
    if not df.empty:
        st.session_state.trade_count = int(df["trade_id"].max())
        st.session_state.win = int((df["pnl_dollar"] > 0).sum())
        st.session_state.lose = int((df["pnl_dollar"] <= 0).sum())
        st.session_state.total_pnl = float(df["pnl_dollar"].sum())
        st.session_state.balance = float(df.iloc[-1]["balance_after"])
    st.session_state.performance_loaded = True

# =====================
# 앱 시작 시 성과 복원 호출
# =====================
restore_performance()

# =====================
# 차트 데이터 로드
# =====================
def generate_chart():
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
    return df

if st.session_state.df_chart is None:
    st.session_state.df_chart = generate_chart()
    st.session_state.start_idx = random.randint(0, len(st.session_state.df_chart) - 300)
    st.session_state.current_step = 300
    

# =====================
# 포지션 관련 함수
# =====================
def reset_position():
    st.session_state.position = None
    st.session_state.entry_price = None
    st.session_state.entry_capital = 0
    st.session_state.entry_time = None
    st.session_state.stop_loss_price = None

def open_position(pos, price, capital, leverage, position_ratio):
    st.session_state.position = pos
    st.session_state.entry_price = price
    st.session_state.entry_capital = capital
    st.session_state.leverage = leverage
    st.session_state.position_ratio = position_ratio

    # ✅ 현재 캔들의 시간 (고정)
    row = st.session_state.df_chart.iloc[
        st.session_state.start_idx + st.session_state.current_step - 1
    ]
    entry_time = int(row.name.timestamp())

    st.session_state.entry_time = entry_time

    st.session_state.trade_markers.append({
        "time": entry_time,   # ✅ 캔들 time
        "label": pos,
        "color": "green" if pos == "LONG" else "red",
        "symbol": "arrow"
    })

def close_position(exit_price, reason="MANUAL EXIT"):
    if st.session_state.position is None:
        return

    exit_ts = int(
        st.session_state.df_chart.iloc[
            st.session_state.start_idx + st.session_state.current_step - 1
        ].name.timestamp()
    )

    entry = st.session_state.entry_price
    amt = st.session_state.entry_capital
    pos = st.session_state.position
    lev = st.session_state.leverage

    pnl = ((exit_price - entry)/entry*amt*lev
           if pos=="LONG"
           else (entry - exit_price)/entry*amt*lev)

    st.session_state.balance += pnl
    st.session_state.total_pnl += pnl
    st.session_state.trade_count += 1
    st.session_state.win += int(pnl > 0)
    st.session_state.lose += int(pnl <= 0)

    save_trade_log({
        "entry_time": datetime.utcfromtimestamp(
            st.session_state.entry_time
        ).isoformat(),
        "exit_time": datetime.utcfromtimestamp(exit_ts).isoformat(),
        "play_hours": (exit_ts - st.session_state.entry_time) / 3600,
        "direction": pos,
        "entry_price": entry,
        "exit_price": exit_price,
        "leverage": lev,
        "position_ratio": int(st.session_state.position_ratio * 100),
        "entry_capital": amt,
        "pnl_dollar": pnl,
        "balance_after": st.session_state.balance,
        "reason": reason
    })

    reset_position()

    st.session_state.trade_markers.append({
        "time": exit_ts,
        "price": exit_price,
        "label": reason,
        "color": "red" if pnl<0 else "green",
        "symbol":"x"
    })
    reset_position()

# =====================
# 메인 UI
# =====================
st.title("📈 Trading Simulator")

# =====================
# ➡️ 다음 캔들 (차트보다 먼저!)
# =====================
MAX_TURNS = 50

if st.session_state.turn_count >= MAX_TURNS:

    st.warning("🛑 최대 50턴이 종료되었습니다.")

    # 🔁 새 매매 시작 버튼 (← 여기에 둔다)
    if st.button("🔁 새 매매 시작"):
        st.session_state.start_idx = random.randint(
            0, len(st.session_state.df_chart) - 300
        )
        st.session_state.current_step = 300
        st.session_state.turn_count = 0
        st.session_state.pending_entry = None
        st.session_state.trade_markers = []
        reset_position()
        st.rerun()

else:
    # ▶️ Next Candle 버튼
    if st.button("▶️ Next Candle", key="next_candle"):
        st.session_state.current_step += 1
        st.session_state.turn_count += 1

        # 📌 지정가 진입 체크
        if st.session_state.pending_entry is not None:
            row = st.session_state.df_chart.iloc[
                st.session_state.start_idx + st.session_state.current_step - 1
            ]

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

        st.rerun()
# =====================
# 데이터 슬라이싱
# =====================
start = st.session_state.start_idx
end = start + st.session_state.current_step
df_view = st.session_state.df_chart.iloc[start:end]
current_price = df_view["close"].iloc[-1]

# =====================
# 차트표시
# =====================
# HTML/JS 차트 렌더링
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
        "time": m["time"],   # ✅ 그대로 사용
        "position": "belowBar" if m["label"] == "LONG" else "aboveBar",
        "color": m["color"],
        "shape": "arrowUp" if m["label"] == "LONG" else "arrowDown",
        "text": m["label"]
    } for m in st.session_state.trade_markers
]

support_lines = [{"price": float(s), "color":"#2962FF","lineWidth":1,"lineStyle":2,"title":"Support"} for s in st.session_state.support_levels]
resistance_lines = [{"price": float(r), "color":"#FF1744","lineWidth":1,"lineStyle":2,"title":"Resistance"} for r in st.session_state.resistance_levels]

html_template = open("chart.html", encoding="utf-8").read()
html_template = html_template.replace("__CANDLE_DATA__", json.dumps(candles))
html_template = html_template.replace("__MARKER_DATA__", json.dumps(markers))
html_template = html_template.replace("__SUPPORT_LINES__", json.dumps(support_lines))
html_template = html_template.replace("__RESISTANCE_LINES__", json.dumps(resistance_lines))
components.html(html_template, height=600)

# ----------------------
# 남은 턴수 표시
# ----------------------
st.markdown(
    f"⏳ 남은 턴수: <span style='color:blue;font-weight:bold;'>{MAX_TURNS - st.session_state.turn_count}</span> / {MAX_TURNS}",
    unsafe_allow_html=True
)

restore_performance()

# ----------------------
# 포지션 손익 계산 및 표시 (레버리지 반영)
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

    st.markdown(f"""
    ### 📊 현재 포지션
    - 포지션: **{st.session_state.position}**
    - 진입가: **{entry:,.2f}**
    - 현재가: **{current_price:,.2f}**
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
st.sidebar.subheader("⚙️ 거래 설정")

# =====================
# 🔧 💰 레버지리(사이드바)
# =====================
st.session_state.leverage = st.sidebar.slider("레버리지", 1, 100, st.session_state.leverage)

# =====================
# 🔧 💰 진입 비중(사이드바)
# =====================
st.sidebar.subheader("💰 진입 비중")

st.session_state.position_ratio = st.sidebar.slider(
    "잔고 대비 진입 비중 (%)",
    min_value=0,
    max_value=100,
    value=int(st.session_state.position_ratio * 100),
    step=5
) / 100

# =====================
st.sidebar.subheader("📌 지정가 진입")
# =====================
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

# =====================
# ✅ 지정가 대기 상태 표시
# =====================
if st.session_state.pending_entry:
    st.sidebar.info(
        f"📌 지정가 대기중\n"
        f"가격: {st.session_state.pending_entry['price']}\n"
        f"방향: {st.session_state.pending_entry['dir']}"
    )
else:
    st.sidebar.info("📌 지정가 대기 없음")

st.sidebar.subheader("📤 지정가 청산")
exit_price = st.sidebar.number_input("청산 가격", value=0.0, step=1.0)
exit_ratio = st.sidebar.slider("청산 비율 (%)", 10, 100, 50)
if st.sidebar.button("청산 등록"):
    st.session_state.pending_exits.append({"price": exit_price, "ratio": exit_ratio/100})
# =====================
# 즉시 진입(사이드바)
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

    if st.sidebar.button("🔴 SHORT 진입"):
        open_position(
            "SHORT",
            current_price,
            capital,
            st.session_state.leverage,
            st.session_state.position_ratio
        )
else:
    st.sidebar.success(f"보유 포지션: {st.session_state.position}")

# =====================
# 진입후 포지션 청산 (사이드바)
# =====================
if st.session_state.position:
    st.sidebar.subheader("📤 포지션 청산")

    if st.sidebar.button("25% 청산"):
        close_position(current_price, "25% EXIT")

    if st.sidebar.button("50% 청산"):
        close_position(current_price, "50% EXIT")

    if st.sidebar.button("전체 청산"):
        close_position(current_price, "FULL EXIT")
# =====================
# 📏 지지선 / 저항선 (사이드바)
# =====================
st.sidebar.subheader("📏 지지선")

new_support = st.sidebar.number_input(
    "지지선 추가",
    value=0.0,
    step=1.0,
    key="sidebar_support"
)
if st.sidebar.button("➕ 지지선 추가"):
    if new_support > 0:
        st.session_state.support_levels.append(new_support)


# 현재 등록된 선 표시
if st.session_state.support_levels:
    st.sidebar.caption("🟦 지지선")
    for s in st.session_state.support_levels:
        st.sidebar.write(f"- {s}")
# =====================
# 📏 지지선 삭제(사이드바)
# =====================
st.sidebar.divider()
st.sidebar.caption("🟦 지지선 목록 (삭제 가능)")

for idx, support in enumerate(st.session_state.support_levels):
    col1, col2 = st.sidebar.columns([3, 1])

    col1.write(f"{support}")

    if col2.button("❌", key=f"del_support_{idx}"):
        st.session_state.support_levels.pop(idx)
        st.rerun()

# ===============================
# 🔁 성과 초기화 + 새 매매 시작 버튼(사이드바)
# ===============================
if st.sidebar.button("🔄 성과 초기화 + 새 매매 시작"):

    # 0️⃣ 기존 세션 ID 백업 (⭐ 중요)
    old_session_id = st.session_state.SESSION_ID

    # 1️⃣ 새 세션 ID 생성
    new_session_id = str(uuid.uuid4())
    st.session_state.SESSION_ID = new_session_id
    SESSION_ID = new_session_id

    # 2️⃣ 기존 세션 DB 기록 삭제
    supabase.table("trade_log").delete().eq(
        "session_id", old_session_id
    ).execute()

    # 3️⃣ 랜덤 차트 시작 위치 초기화
    st.session_state.start_idx = random.randint(
        0, len(st.session_state.df_chart) - 300
    )
    st.session_state.current_step = 300
    st.session_state.turn_count = 0
    st.session_state.pending_entry = None
    st.session_state.pending_exits = []
    st.session_state.trade_markers = []
    st.session_state.support_levels = []
    st.session_state.resistance_levels = []

    # 4️⃣ 포지션 초기화
    reset_position()

    # 5️⃣ 성과 초기화
    st.session_state.balance = 1000.0
    st.session_state.total_pnl = 0.0
    st.session_state.trade_count = 0
    st.session_state.win = 0
    st.session_state.lose = 0
    st.session_state.performance_loaded = False

    st.success("✅ 성과가 초기화되고 새 매매를 시작합니다!")

    # 6️⃣ 화면 새로고침
    st.markdown(
        "<script>window.location.reload();</script>",
        unsafe_allow_html=True
    )

# =====================
# 🔹 누적 성과 표시 (확장판)
# =====================
total_trades = st.session_state.win + st.session_state.lose
winrate = (st.session_state.win / total_trades * 100) if total_trades else 0

# 📊 매매 평균 수익률 계산 (전체 / 승 / 패)
def get_trade_return_stats():
    df = load_trade_log_df()
    if df.empty:
        return 0.0, 0.0, 0.0
    # 수익률 계산
    df["return_pct"] = df["pnl_dollar"] / df["entry_capital"] * 100
    overall_avg = df["return_pct"].mean()
    win_avg = df[df["return_pct"] > 0]["return_pct"].mean() if not df[df["return_pct"] > 0].empty else 0.0
    loss_avg = df[df["return_pct"] <= 0]["return_pct"].mean() if not df[df["return_pct"] <= 0].empty else 0.0
    return overall_avg, win_avg, loss_avg

avg_return, win_avg_return, loss_avg_return = get_trade_return_stats()

st.markdown(f"""
## 📊 누적 성과
- 승 : {st.session_state.win} / 패 : {st.session_state.lose}
- 승률: {winrate:.2f}%
- 누적 손익: ${st.session_state.total_pnl:,.2f}
- 매매 평균 수익률: {avg_return:+.2f}%
- 🟢 승리 트레이드 평균 수익률: {win_avg_return:+.2f}%
- 🔴 패배 트레이드 평균 손실률: {loss_avg_return:+.2f}%
""")

# 잔고 및 총 손익 표시
st.metric("잔고", f"${st.session_state.balance:,.2f}")
st.metric("총 손익", f"${st.session_state.total_pnl:,.2f}")