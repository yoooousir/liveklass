"""
Event Analytics & Visualization
--------------------------------
저장된 이벤트를 SQL로 집계하고 Matplotlib 차트 4종을 /charts/ 에 저장합니다.
"""

import os
import time
import psycopg2
import psycopg2.extras
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
from datetime import datetime

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "db"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME", "eventdb"),
    "user": os.getenv("DB_USER", "eventuser"),
    "password": os.getenv("DB_PASSWORD", "eventpass"),
}
CHARTS_DIR = os.getenv("CHARTS_DIR", "/charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# ── 팔레트 ────────────────────────────────────────────────────
PALETTE = {
    "page_view": "#4C72B0",
    "search":    "#55A868",
    "purchase":  "#C44E52",
    "error":     "#DD8452",
    "logout":    "#8172B2",
}
DEFAULT_COLORS = list(PALETTE.values())


def wait_for_data(conn, max_retries=10, delay=3):
    for i in range(1, max_retries + 1):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM events")
            cnt = cur.fetchone()[0]
        if cnt > 0:
            print(f"[✓] {cnt} events found in DB")
            return cnt
        print(f"[…] No data yet, waiting… ({i}/{max_retries})")
        time.sleep(delay)
    raise RuntimeError("No data in events table")


def query(conn, sql: str, params=None) -> list:
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ════════════════════════════════════════════════════════════
#  분석 1 — 이벤트 타입별 발생 횟수
# ════════════════════════════════════════════════════════════
def chart_event_type_count(conn):
    rows = query(conn, """
        SELECT event_type,
               COUNT(*)                             AS cnt,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) AS pct
        FROM   events
        GROUP  BY event_type
        ORDER  BY cnt DESC;
    """)
    labels = [r["event_type"] for r in rows]
    counts = [r["cnt"] for r in rows]
    pcts   = [float(r["pct"]) for r in rows]
    colors = [PALETTE.get(l, "#888") for l in labels]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, counts, color=colors, edgecolor="white", linewidth=0.8)
    ax.bar_label(bars, labels=[f"{c:,}\n({p}%)" for c, p in zip(counts, pcts)],
                 padding=6, fontsize=10)
    ax.set_title("Event Count by Type", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Event Type")
    ax.set_ylabel("Count")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.set_ylim(0, max(counts) * 1.2)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "1_event_type_count.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[✓] Saved: {path}")

    print("\n[분석 1] 이벤트 타입별 발생 횟수")
    for r in rows:
        print(f"  {r['event_type']:12s}: {r['cnt']:6,}  ({r['pct']}%)")


# ════════════════════════════════════════════════════════════
#  분석 2 — 유저별 총 이벤트 수 Top 20
# ════════════════════════════════════════════════════════════
def chart_top_users(conn):
    rows = query(conn, """
        SELECT user_id,
               COUNT(*)                                     AS total,
               COUNT(*) FILTER (WHERE event_type='purchase') AS purchases,
               COUNT(*) FILTER (WHERE event_type='error')    AS errors
        FROM   events
        GROUP  BY user_id
        ORDER  BY total DESC
        LIMIT  20;
    """)
    users    = [r["user_id"] for r in rows]
    totals   = [r["total"] for r in rows]
    purchases= [r["purchases"] for r in rows]
    errors   = [r["errors"] for r in rows]

    x = range(len(users))
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x, totals,    label="Total",    color="#4C72B0", alpha=0.85)
    ax.bar(x, purchases, label="Purchase", color="#C44E52", alpha=0.9)
    ax.bar(x, errors,    label="Error",    color="#DD8452", alpha=0.9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(users, rotation=45, ha="right", fontsize=8)
    ax.set_title("Top 20 Users by Event Count", fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("Event Count")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "2_top_users.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[✓] Saved: {path}")

    print("\n[분석 2] 유저별 총 이벤트 수 Top 5")
    for r in rows[:5]:
        print(f"  {r['user_id']}: {r['total']} events  "
              f"(purchases={r['purchases']}, errors={r['errors']})")


# ════════════════════════════════════════════════════════════
#  분석 3 — 시간대별 이벤트 추이 (1시간 단위)
# ════════════════════════════════════════════════════════════
def chart_hourly_trend(conn):
    rows = query(conn, """
        SELECT DATE_TRUNC('hour', created_at)            AS hour,
               event_type,
               COUNT(*)                                  AS cnt
        FROM   events
        GROUP  BY 1, 2
        ORDER  BY 1, 2;
    """)

    # pivot: hour → {event_type: count}
    from collections import defaultdict
    pivot = defaultdict(lambda: defaultdict(int))
    hours_set = set()
    for r in rows:
        pivot[r["hour"]][r["event_type"]] += r["cnt"]
        hours_set.add(r["hour"])

    hours = sorted(hours_set)
    fig, ax = plt.subplots(figsize=(14, 5))
    for etype, color in PALETTE.items():
        vals = [pivot[h].get(etype, 0) for h in hours]
        ax.plot(hours, vals, label=etype, color=color, linewidth=1.8, marker="o",
                markersize=3)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.xticks(rotation=45, ha="right", fontsize=8)
    ax.set_title("Hourly Event Trend by Type", fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("Count per Hour")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(linestyle="--", alpha=0.4)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "3_hourly_trend.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[✓] Saved: {path}")

    print(f"\n[분석 3] 시간대 범위: {min(hours)} ~ {max(hours)}  ({len(hours)}개 구간)")


# ════════════════════════════════════════════════════════════
#  분석 4 — 에러 이벤트 비율 & 에러 코드 분포
# ════════════════════════════════════════════════════════════
def chart_error_analysis(conn):
    # 전체 대비 에러 비율
    ratio_rows = query(conn, """
        SELECT event_type,
               COUNT(*) AS cnt
        FROM   events
        GROUP  BY event_type;
    """)
    total = sum(r["cnt"] for r in ratio_rows)
    error_cnt = next((r["cnt"] for r in ratio_rows if r["event_type"] == "error"), 0)
    non_error  = total - error_cnt
    error_pct  = error_cnt / total * 100

    # 에러 코드별 분포
    code_rows = query(conn, """
        SELECT error_code,
               error_message,
               COUNT(*) AS cnt
        FROM   events
        WHERE  event_type = 'error'
        GROUP  BY error_code, error_message
        ORDER  BY cnt DESC;
    """)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # 도넛 차트
    wedge_sizes  = [error_cnt, non_error]
    wedge_labels = [f"error\n({error_pct:.1f}%)", f"other\n({100-error_pct:.1f}%)"]
    wedge_colors = ["#DD8452", "#4C72B0"]
    ax1.pie(wedge_sizes, labels=wedge_labels, colors=wedge_colors,
            startangle=90, wedgeprops=dict(width=0.5),
            textprops=dict(fontsize=11))
    ax1.set_title("Error Event Ratio", fontsize=13, fontweight="bold")

    # 에러 코드 가로 막대
    codes  = [f"{r['error_code']}\n{r['error_message']}" for r in code_rows]
    cnts   = [r["cnt"] for r in code_rows]
    bar_colors = plt.cm.Oranges([0.4 + 0.5 * i / max(len(cnts)-1, 1)
                                 for i in range(len(cnts))])
    bars = ax2.barh(codes, cnts, color=bar_colors, edgecolor="white")
    ax2.bar_label(bars, labels=[str(c) for c in cnts], padding=4, fontsize=9)
    ax2.set_title("Error Code Distribution", fontsize=13, fontweight="bold")
    ax2.set_xlabel("Count")
    ax2.invert_yaxis()
    ax2.grid(axis="x", linestyle="--", alpha=0.4)
    ax2.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "4_error_analysis.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[✓] Saved: {path}")

    print(f"\n[분석 4] 에러 비율: {error_pct:.2f}%  ({error_cnt:,} / {total:,})")
    for r in code_rows:
        print(f"  HTTP {r['error_code']} {r['error_message']}: {r['cnt']}")


# ── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    time.sleep(2)   # generator가 먼저 완료될 시간 여유
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        wait_for_data(conn)
        chart_event_type_count(conn)
        chart_top_users(conn)
        chart_hourly_trend(conn)
        chart_error_analysis(conn)
    finally:
        conn.close()

    print("\n[✓] All charts saved to", CHARTS_DIR)
