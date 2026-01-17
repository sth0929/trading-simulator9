import streamlit as st
import pandas as pd
import random
import os
import streamlit.components.v1 as components

# =====================
# 🔗 Supabase 연결 (여기!)
# =====================
from supabase import create_client, Client

SUPABASE_URL = "https://fxphiilweuorekvqcdmo.supabase.co"
SUPABASE_KEY = "sb_publishable__hWexwyOhAhapgvDUBiFzg_96UZOPf_"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

LOG_FILE = "trade_log.csv"

# =====================
# 기본 설정
# =====================
st.set_page_config(layout="wide")

# =====================
# 지정가 주문 세션 초기화 (필수)
# =====================
if "pending_order" not in st.session_state:
    st.session_state.pending_order = False
    st.session_state.limit_price = None
    st.session_state.limit_direction = None

# =====================
# CSV 로그 초기화
# =====================
if not os.path.exists(LOG_FILE):
    pd.DataFrame(columns=[
        "trade_id",
        "entry_time",
        "exit_time",
        "play_hours",
        "direction",
        "entry_price",
        "exit_price",
        "leverage",
        "position_ratio",
        "entry_capital",
        "pnl_dollar",
        "pnl_pct",
        "balance_after"
    ]).to_csv(LOG_FILE, index=False)

import os

# =====================
# 차트 데이터 로드
# =====================
def generate_chart():
    # app.py 위치 기준 절대 경로
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_FILE = os.path.join(BASE_DIR, "btc_1h.csv")

    df = pd.read_csv(DATA_FILE)

    # open_time을 숫자로 강제 변환 (문자 제거)
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")

    # 값 크기로 ms / s 자동 판별
    # 10^12 이상이면 ms (2020년대 타임스탬프)
    df["open_time"] = df["open_time"].apply(
        lambda x: pd.to_datetime(x, unit="ms", errors="coerce")
        if x and x > 1e12
        else pd.to_datetime(x, unit="s", errors="coerce")
    )

    # 변환 실패한 행 제거
    df = df.dropna(subset=["open_time"])

    df = df.sort_values("open_time")
    df.set_index("open_time", inplace=True)

    return df

# =====================
# 세션 초기화
# =====================
if "df_chart" not in st.session_state:
    st.session_state.df_chart = generate_chart()
    st.session_state.start_idx = random.randint(0, len(st.session_state.df_chart) - 300)
    st.session_state.current_step = 300
    st.session_state.turn_count = 0

if "support_levels" not in st.session_state:
    st.session_state.support_levels = []


if "balance" not in st.session_state:
    st.session_state.balance = 1000.0
    st.session_state.position = None
    st.session_state.entry_price = None
    st.session_state.entry_capital = 0.0
    st.session_state.entry_time = None
    st.session_state.win = 0
    st.session_state.lose = 0
    st.session_state.total_pnl = 0.0
    st.session_state.trade_count = 0

if "stop_loss_price" not in st.session_state:
    st.session_state.stop_loss_price = None

if "trade_markers" not in st.session_state:
    st.session_state.trade_markers = []

# =====================
# 📦 로그 파일 로드 (항상 먼저)
# =====================
if os.path.exists(LOG_FILE):
    log_df = pd.read_csv(
        LOG_FILE,
        engine="python",
        on_bad_lines="skip"
    )
else:
    log_df = pd.DataFrame()

# =====================
# 누적 성과 복원
# =====================
if "performance_loaded" not in st.session_state:

    log_df = pd.read_csv(
        LOG_FILE,
        engine="python",
        on_bad_lines="skip"
    )

    if not log_df.empty:

        if "trade_id" not in log_df.columns:
            log_df.insert(0, "trade_id", range(1, len(log_df) + 1))
            log_df.to_csv(LOG_FILE, index=False)

        st.session_state.trade_count = int(log_df["trade_id"].max())
        st.session_state.win = int((log_df["pnl_dollar"] > 0).sum())
        st.session_state.lose = int((log_df["pnl_dollar"] <= 0).sum())
        st.session_state.total_pnl = float(log_df["pnl_dollar"].sum())
        st.session_state.balance = float(log_df.iloc[-1]["balance_after"])

    st.session_state.performance_loaded = True


# =====================
# 사이드바
# =====================
with st.sidebar:

    # 🔌 Supabase 연결 테스트 (맨 위)
    st.subheader("🔌 Supabase 연결 테스트")
    if st.button("연결 테스트"):
        res = supabase.table("trade_log").select("*").limit(1).execute()
        st.write(res.data)

    # ⚙️ 매매 설정
    st.subheader("⚙️ 매매 설정")
    leverage = st.radio("레버리지", [1, 5, 10, 20, 50], index=3)
    position_ratio = st.radio("진입 비중 (%)", [5, 10, 20], index=0)


    st.markdown("---")

    # =====================
    # 🛑 스탑로스 (위)
    # =====================
    st.subheader("🛑 스탑로스")

    stop_loss_input = st.number_input(
        "스탑로스 가격",
        value=0.0,
        step=10.0
    )

    if st.button("🛑 스탑로스 설정"):
        if stop_loss_input > 0:
            st.session_state.stop_loss_price = stop_loss_input
            st.success(f"스탑로스 설정: {stop_loss_input}")

    st.markdown("---")

    # =====================
    # 📌 지정가 진입 (아래)
    # =====================
    st.subheader("📌 지정가 진입")

    limit_direction = st.radio("방향", ["LONG", "SHORT"], horizontal=True)
    limit_price = st.number_input("지정가 가격", value=0.0, step=10.0)

    if st.button("📍 지정가 주문 등록"):
        st.session_state.pending_order = True
        st.session_state.limit_price = limit_price
        st.session_state.limit_direction = limit_direction
        st.success("지정가 주문 등록 완료")

    st.markdown("---")
    st.subheader("📐 지지 / 저항 (다중 관리)")

    # ---------- 지지선 ----------
    support_input = st.number_input(
        "🟦 지지선 추가",
        value=0.0,
        step=10.0,
        key="support_input"
    )

    if st.button("➕ 지지선 추가"):
        if support_input > 0:
            st.session_state.support_levels.append(support_input)

    if st.session_state.support_levels:
        st.markdown("🗑 지지선 삭제")
        for i, s in enumerate(st.session_state.support_levels):
            if st.button(f"❌ {s}", key=f"del_support_{i}"):
                st.session_state.support_levels.pop(i)
                st.rerun()

    if st.button("🧹 지지선 전체 삭제"):
        st.session_state.support_levels = []




    st.markdown("---")
    st.subheader("🧹 성과 관리")
    if st.button("🔄 성과 전체 리셋"):
        pd.DataFrame(columns=[
            "trade_id","entry_time","exit_time","play_hours","direction",
            "entry_price","exit_price","leverage","position_ratio",
            "entry_capital","pnl_dollar","pnl_pct","balance_after"
        ]).to_csv(LOG_FILE, index=False)
        st.session_state.clear()
        st.rerun()


if st.session_state.pending_order:
    if st.button("❌ 지정가 주문 취소"):
        st.session_state.pending_order = False
        st.session_state.limit_price = None
        st.session_state.limit_direction = None

# =====================
# 데이터 슬라이싱
# =====================
start = st.session_state.start_idx
end = start + st.session_state.current_step
df_view = st.session_state.df_chart.iloc[start:end]
current_price = df_view["close"].iloc[-1]

# =====================
# 📈 고급 캔들 차트 (Lightweight)
# =====================
import json

markers = []

for m in st.session_state.trade_markers:
    markers.append({
        "time": int(pd.to_datetime(m["time"]).timestamp()),
        "position": "belowBar" if m["label"] in ["LONG", "LIMIT LONG"] else "aboveBar",
        "color": m["color"],
        "shape": "arrowUp" if m["label"] in ["LONG", "LIMIT LONG"] else "arrowDown",
        "text": m["label"]
    })

candles = df_view.reset_index().apply(
    lambda r: {
        "time": int(r["open_time"].timestamp()),
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
        "volume": float(r["volume"]),
    },
    axis=1
).tolist()

# =====================
# 📐 지지선 데이터 (차트 전달용)
# =====================
support_lines = [
    {
        "price": float(s),
        "color": "#2962FF",
        "lineWidth": 1,
        "lineStyle": 2,   # dashed
        "title": "Support"
    }
    for s in st.session_state.support_levels
]

html = open("chart.html", encoding="utf-8").read()

html = html.replace("__CANDLE_DATA__", json.dumps(candles))
html = html.replace("__MARKER_DATA__", json.dumps(markers))
html = html.replace("__SUPPORT_LINES__", json.dumps(support_lines))

components.html(html, height=600)
# =====================
# 🛑 스탑로스 체크
# =====================
if st.session_state.position is not None and st.session_state.stop_loss_price:

    stop = st.session_state.stop_loss_price
    entry = st.session_state.entry_price
    amt = st.session_state.entry_capital
    pos = st.session_state.position

    hit = False
    if pos == "LONG" and current_price <= stop:
        hit = True
    if pos == "SHORT" and current_price >= stop:
        hit = True

    if hit:
        exit_time = df_view.index[-1]

        pnl_ratio = (
            (current_price - entry) / entry
            if pos == "LONG"
            else (entry - current_price) / entry
        ) * leverage

        profit = amt * pnl_ratio

        st.session_state.balance += profit
        st.session_state.total_pnl += profit
        st.session_state.trade_count += 1

        if profit > 0:
            st.session_state.win += 1
        else:
            st.session_state.lose += 1

        pd.DataFrame([{
            "trade_id": st.session_state.trade_count,
            "entry_time": st.session_state.entry_time,
            "exit_time": exit_time,
            "play_hours": (
                exit_time - st.session_state.entry_time
            ).total_seconds() / 3600,
            "direction": pos,
            "entry_price": entry,
            "exit_price": current_price,
            "leverage": leverage,
            "position_ratio": position_ratio,
            "entry_capital": amt,
            "pnl_dollar": profit,
            "pnl_pct": pnl_ratio * 100,
            "balance_after": st.session_state.balance
        }]).to_csv(LOG_FILE, mode="a", header=False, index=False)

        st.session_state.trade_markers.append({
            "time": exit_time,
            "price": current_price,
            "label": "STOP LOSS",
            "color": "orange",
            "symbol": "x"
        })

        st.session_state.position = None
        st.session_state.entry_price = None
        st.session_state.entry_capital = 0
        st.session_state.entry_time = None
        st.session_state.stop_loss_price = None

        st.warning("🛑 스탑로스 체결")
        st.rerun()

# =====================
# 🔥 강제청산 체크 (진입 시드 초과 손실 방지)
# =====================
if st.session_state.position is not None:
    entry = st.session_state.entry_price
    amt = st.session_state.entry_capital
    pos = st.session_state.position

    if pos == "LONG":
        pnl_ratio = (current_price - entry) / entry * leverage
    else:
        pnl_ratio = (entry - current_price) / entry * leverage

    # 🔴 손실이 -100% 도달 → 강제청산
    if pnl_ratio <= -1.0:
        exit_time = df_view.index[-1]

        loss = -amt  # 최대 손실 = 진입금액
        st.session_state.balance += loss
        st.session_state.total_pnl += loss
        st.session_state.trade_count += 1
        st.session_state.lose += 1

        # 로그 기록
        pd.DataFrame([{
            "trade_id": st.session_state.trade_count,
            "entry_time": st.session_state.entry_time,
            "exit_time": exit_time,
            "play_hours": (
                exit_time - st.session_state.entry_time
            ).total_seconds() / 3600,
            "direction": pos,
            "entry_price": entry,
            "exit_price": current_price,
            "leverage": leverage,
            "position_ratio": position_ratio,
            "entry_capital": amt,
            "pnl_dollar": loss,
            "pnl_pct": -100.0,
            "balance_after": st.session_state.balance
        }]).to_csv(LOG_FILE, mode="a", header=False, index=False)

        # 차트 마커
        st.session_state.trade_markers.append({
            "time": exit_time,
            "price": current_price,
            "label": "FORCED EXIT",
            "color": "darkred",
            "symbol": "x"
        })

        # 포지션 초기화
        st.session_state.position = None
        st.session_state.entry_price = None
        st.session_state.entry_capital = 0
        st.session_state.entry_time = None

        st.warning("⚠️ 진입 시드 초과 손실 → 강제청산")
        st.rerun()


# =====================
# 계좌 정보 (상단 요약)
# =====================
if st.session_state.position:
    entry = st.session_state.entry_price
    pos = st.session_state.position

    if pos == "LONG":
        pnl_pct = (current_price - entry) / entry * 100
    else:
        pnl_pct = (entry - current_price) / entry * 100

    st.markdown(
        f"""
        ### 💰 Balance: ${st.session_state.balance:,.2f}
        | 📍 **{pos} @ {entry:,.2f}**  
        <span style="color:{'green' if pnl_pct >= 0 else 'red'};">
        ({pnl_pct:+.2f}%)
        </span>
        """,
        unsafe_allow_html=True
    )
else:
    st.markdown(
        f"""
        ### 💰 Balance: ${st.session_state.balance:,.2f}
        | 📍 NO POSITION
        """
    )

st.caption(f"현재가: {current_price:,.2f} | 턴: {st.session_state.turn_count} / 100")



# =====================
# 다음 캔들
# =====================
if st.button("➡️ Next Candle"):
    if st.session_state.turn_count < 100:
        st.session_state.current_step += 1
        st.session_state.turn_count += 1

        # ✅ 새 캔들 기준 지정가 체결 체크
        if st.session_state.pending_order and st.session_state.position is None:
            new_candle = st.session_state.df_chart.iloc[
                st.session_state.start_idx + st.session_state.current_step - 1
            ]

            filled = False
            if st.session_state.limit_direction == "LONG":
                filled = new_candle["low"] <= st.session_state.limit_price
            else:
                filled = new_candle["high"] >= st.session_state.limit_price

            if filled:
                st.session_state.pending_order = False
                st.session_state.position = st.session_state.limit_direction
                st.session_state.entry_price = st.session_state.limit_price
                st.session_state.entry_time = new_candle.name
                st.session_state.entry_capital = (
                    st.session_state.balance * (position_ratio / 100)
                )

                st.session_state.trade_markers.append({
                    "time": new_candle.name,
                    "price": st.session_state.entry_price,
                    "label": f"LIMIT {st.session_state.position}",
                    "color": "lime" if st.session_state.position == "LONG" else "red",
                    "symbol": "circle"
                })

                st.session_state.limit_price = None
                st.session_state.limit_direction = None

        st.rerun()

# =====================
# 🧹 100턴 종료 시 자동 포지션 정리
# =====================
if st.session_state.turn_count >= 100 and st.session_state.position is not None:
    exit_time = df_view.index[-1]
    entry = st.session_state.entry_price
    amt = st.session_state.entry_capital
    pos = st.session_state.position

    if pos == "LONG":
        pnl_ratio = (current_price - entry) / entry * leverage
    else:
        pnl_ratio = (entry - current_price) / entry * leverage

    profit = amt * pnl_ratio
    st.session_state.balance += profit
    st.session_state.total_pnl += profit
    st.session_state.trade_count += 1

    if profit > 0:
        st.session_state.win += 1
    else:
        st.session_state.lose += 1

    pd.DataFrame([{
        "trade_id": st.session_state.trade_count,
        "entry_time": st.session_state.entry_time,
        "exit_time": exit_time,
        "play_hours": (
            exit_time - st.session_state.entry_time
        ).total_seconds() / 3600,
        "direction": pos,
        "entry_price": entry,
        "exit_price": current_price,
        "leverage": leverage,
        "position_ratio": position_ratio,
        "entry_capital": amt,
        "pnl_dollar": profit,
        "pnl_pct": pnl_ratio * 100,
        "balance_after": st.session_state.balance
    }]).to_csv(LOG_FILE, mode="a", header=False, index=False)

    st.session_state.trade_markers.append({
        "time": exit_time,
        "price": current_price,
        "label": "AUTO EXIT (100)",
        "color": "black",
        "symbol": "x"
    })

    st.session_state.position = None
    st.session_state.entry_price = None
    st.session_state.entry_capital = 0
    st.session_state.entry_time = None

# =====================
# 100턴 종료 후 새 매매 시작
# =====================
if st.session_state.turn_count >= 100:
    st.info("🕒 100턴 종료 — 새로운 시뮬레이션을 시작하세요")

    if st.button("🔁 새 매매 시작"):
        st.session_state.start_idx = random.randint(0, len(st.session_state.df_chart) - 300)
        st.session_state.current_step = 300
        st.session_state.turn_count = 0
        st.session_state.trade_markers = []
        st.session_state.position = None

        # ✅ 지지선 / 저항선 초기화
        st.session_state.support_levels = []
        st.session_state.resistance_levels = []

        st.rerun()

# =====================
# 진입 함수
# =====================
def enter_position(pos):
    capital = st.session_state.balance * (position_ratio / 100)

    st.session_state.position = pos
    st.session_state.entry_price = float(df_view["close"].iloc[-1])
    st.session_state.entry_capital = capital
    st.session_state.entry_time = df_view.index[-1]

    st.session_state.trade_markers.append({
        "time": df_view.index[-1],
        "price": st.session_state.entry_price,
        "label": pos,
        "color": "lime" if pos == "LONG" else "red",
        "symbol": "triangle-up" if pos == "LONG" else "triangle-down"
    })
# =====================
# 매매 버튼
# =====================
c1, c2, c3 = st.columns(3)

with c1:
    if st.button("📈 LONG") and st.session_state.position is None:
        enter_position("LONG")
        st.rerun()

with c2:
    if st.button("📉 SHORT") and st.session_state.position is None:
        enter_position("SHORT")
        st.rerun()

with c3:
    if st.button("❌ 전체청산") and st.session_state.position:
        exit_time = df_view.index[-1]
        play_hours = (exit_time - st.session_state.entry_time).total_seconds() / 3600

        pnl = ((current_price - st.session_state.entry_price)
               if st.session_state.position == "LONG"
               else (st.session_state.entry_price - current_price)) \
              / st.session_state.entry_price * leverage

        profit = st.session_state.entry_capital * pnl
        st.session_state.balance += profit
        st.session_state.total_pnl += profit
        st.session_state.trade_count += 1

        if profit > 0:
            st.session_state.win += 1
        else:
            st.session_state.lose += 1

        pd.DataFrame([{
            "trade_id": st.session_state.trade_count,
            "entry_time": st.session_state.entry_time,
            "exit_time": exit_time,
            "play_hours": round(play_hours, 2),
            "direction": st.session_state.position,
            "entry_price": st.session_state.entry_price,
            "exit_price": current_price,
            "leverage": leverage,
            "position_ratio": position_ratio,
            "entry_capital": st.session_state.entry_capital,
            "pnl_dollar": profit,
            "pnl_pct": pnl * 100,
            "balance_after": st.session_state.balance
        }]).to_csv(LOG_FILE, mode="a", header=False, index=False)

        st.session_state.trade_markers.append({
            "time": exit_time,
            "price": current_price,
            "label": "EXIT",
            "color": "black",
            "symbol": "x"
        })

        st.session_state.position = None
        st.session_state.entry_capital = 0
        st.session_state.entry_price = None
        st.session_state.entry_time = None
        st.rerun()

# =====================
# 평균 매매 수익률 계산
# =====================
avg_pnl_pct = 0.0

if os.path.exists(LOG_FILE):
    df_log = pd.read_csv(LOG_FILE, engine="python", on_bad_lines="skip")

    if not df_log.empty and "pnl_pct" in df_log.columns:
        avg_pnl_pct = df_log["pnl_pct"].mean()

# =====================
# 누적 성과
# =====================
total = st.session_state.win + st.session_state.lose
winrate = (st.session_state.win / total * 100) if total else 0

st.markdown(f"""
## 📊 누적 성과
- 트레이드 수: {st.session_state.trade_count}
- 승 / 패: {st.session_state.win} / {st.session_state.lose}
- 승률: {winrate:.2f}%
- 누적 손익: ${st.session_state.total_pnl:.2f}
- 📈 **평균 매매 수익률:** {avg_pnl_pct:+.2f}%
""")

# ----------------------
# 9️⃣ 포지션 손익 계산 및 표시 (레버리지 반영)
# ----------------------
if st.session_state.position is not None:
    entry = st.session_state.entry_price
    amt = st.session_state.entry_capital
    lev = leverage

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
# 개별 매매 내역
# =====================
st.markdown("## 🧾 개별 매매 내역")

if os.path.exists(LOG_FILE):
    df_log = pd.read_csv(
        LOG_FILE,
        engine="python",
        on_bad_lines="skip"
    )

    if not df_log.empty:
        # 시간 컬럼 정리 (안전장치)
        if "exit_time" in df_log.columns:
            df_log["exit_time"] = pd.to_datetime(df_log["exit_time"], errors="coerce")

        # ✅ 매매 순서 기준 정렬
        if "trade_id" in df_log.columns:
            df_log = df_log.sort_values("trade_id", ascending=False)
        else:
            df_log = df_log.sort_values("exit_time", ascending=False)

        df_log = df_log.reset_index(drop=True)

        st.dataframe(df_log, use_container_width=True)

    else:
        st.info("아직 매매 기록이 없습니다.")
else:
    st.info("매매 로그 파일이 없습니다.")