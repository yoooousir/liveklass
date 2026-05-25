"""
Web Event Generator
-------------------
웹 서비스에서 발생할 수 있는 이벤트를 랜덤 생성 후 PostgreSQL에 저장합니다.
"""

import random
import time
import os
import uuid
import psycopg2
from datetime import datetime, timedelta
from psycopg2.extras import execute_batch

# ── DB 연결 설정 ──────────────────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "db"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME", "eventdb"),
    "user": os.getenv("DB_USER", "eventuser"),
    "password": os.getenv("DB_PASSWORD", "eventpass"),
}

# ── 이벤트 설계 ───────────────────────────────────────────────
# 실제 e-커머스 서비스 트래픽을 모사:
#   page_view  가장 빈번, 전체의 ~45%
#   search     탐색 행동,  ~20%
#   purchase   전환 이벤트, ~10%
#   error      장애 시그널, ~10%
#   logout     세션 종료,  ~15%
EVENT_TYPES = ["page_view", "search", "purchase", "error", "logout"]
EVENT_WEIGHTS = [45, 20, 10, 10, 15]

PAGES = [
    "/home", "/products", "/products/detail", "/cart",
    "/checkout", "/mypage", "/search", "/about",
]
SEARCH_QUERIES = [
    "running shoes", "laptop", "wireless earbuds", "coffee maker",
    "yoga mat", "mechanical keyboard", "desk lamp", "backpack",
]
ERROR_CODES = [400, 401, 403, 404, 500, 502, 503]
ERROR_MESSAGES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}
PRODUCTS = [
    ("P001", "Nike Air Max", 129.99),
    ("P002", "MacBook Pro 14", 1999.99),
    ("P003", "Sony WH-1000XM5", 349.99),
    ("P004", "Breville Espresso", 599.99),
    ("P005", "Lululemon Mat", 88.00),
    ("P006", "Keychron K2", 89.99),
    ("P007", "BenQ Lamp", 49.99),
    ("P008", "Osprey Backpack", 179.95),
]
USER_IDS = [f"user_{i:04d}" for i in range(1, 201)]   # 200명 유저
DEVICES = ["desktop", "mobile", "tablet"]
BROWSERS = ["Chrome", "Safari", "Firefox", "Edge"]
COUNTRIES = ["KR", "US", "JP", "DE", "GB", "FR", "SG"]


def make_event(event_type: str, ts: datetime) -> dict:
    """이벤트 타입에 맞는 필드를 생성해 dict 반환."""
    user_id = random.choice(USER_IDS)
    session_id = str(uuid.uuid4())
    device = random.choice(DEVICES)
    browser = random.choice(BROWSERS)
    country = random.choice(COUNTRIES)

    base = dict(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        user_id=user_id,
        session_id=session_id,
        device=device,
        browser=browser,
        country=country,
        created_at=ts,
    )

    # 이벤트 타입별 추가 필드
    if event_type == "page_view":
        base["page_path"] = random.choice(PAGES)
        base["referrer"] = random.choice(
            ["google", "direct", "facebook", "instagram", "email", None]
        )
        base["duration_sec"] = random.randint(3, 300)
        # 나머지 타입 전용 필드는 None
        base.update(
            query=None, product_id=None, product_name=None,
            amount=None, quantity=None, error_code=None, error_message=None,
        )

    elif event_type == "search":
        base["query"] = random.choice(SEARCH_QUERIES)
        base["page_path"] = "/search"
        base["referrer"] = None
        base["duration_sec"] = None
        base.update(
            product_id=None, product_name=None,
            amount=None, quantity=None, error_code=None, error_message=None,
        )

    elif event_type == "purchase":
        product = random.choice(PRODUCTS)
        qty = random.randint(1, 3)
        base["product_id"] = product[0]
        base["product_name"] = product[1]
        base["amount"] = round(product[2] * qty, 2)
        base["quantity"] = qty
        base["page_path"] = "/checkout"
        base["referrer"] = None
        base["duration_sec"] = None
        base["query"] = None
        base.update(error_code=None, error_message=None)

    elif event_type == "error":
        code = random.choice(ERROR_CODES)
        base["error_code"] = code
        base["error_message"] = ERROR_MESSAGES[code]
        base["page_path"] = random.choice(PAGES)
        base["referrer"] = None
        base["duration_sec"] = None
        base.update(
            query=None, product_id=None, product_name=None,
            amount=None, quantity=None,
        )

    elif event_type == "logout":
        base["page_path"] = "/logout"
        base["referrer"] = None
        base["duration_sec"] = None
        base.update(
            query=None, product_id=None, product_name=None,
            amount=None, quantity=None, error_code=None, error_message=None,
        )

    return base


def generate_events(n: int, spread_hours: int = 24) -> list[dict]:
    """n개 이벤트를 spread_hours 시간에 걸쳐 랜덤 타임스탬프로 생성."""
    now = datetime.utcnow()
    events = []
    for _ in range(n):
        offset_sec = random.randint(0, spread_hours * 3600)
        ts = now - timedelta(seconds=offset_sec)
        etype = random.choices(EVENT_TYPES, weights=EVENT_WEIGHTS, k=1)[0]
        events.append(make_event(etype, ts))
    # 시간 순 정렬
    events.sort(key=lambda e: e["created_at"])
    return events


# ── DB 초기화 & 저장 ──────────────────────────────────────────
def wait_for_db(max_retries: int = 15, delay: int = 3):
    for attempt in range(1, max_retries + 1):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.close()
            print(f"[✓] DB connected (attempt {attempt})")
            return
        except psycopg2.OperationalError:
            print(f"[…] DB not ready, retrying ({attempt}/{max_retries})…")
            time.sleep(delay)
    raise RuntimeError("DB connection failed after max retries")


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id      UUID        PRIMARY KEY,
                event_type    VARCHAR(20) NOT NULL,
                user_id       VARCHAR(20) NOT NULL,
                session_id    UUID        NOT NULL,
                device        VARCHAR(10),
                browser       VARCHAR(20),
                country       CHAR(2),
                page_path     VARCHAR(100),
                referrer      VARCHAR(50),
                duration_sec  INTEGER,
                query         VARCHAR(200),
                product_id    VARCHAR(10),
                product_name  VARCHAR(100),
                amount        NUMERIC(10,2),
                quantity      INTEGER,
                error_code    SMALLINT,
                error_message VARCHAR(100),
                created_at    TIMESTAMP   NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_type
                ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_user
                ON events(user_id);
            CREATE INDEX IF NOT EXISTS idx_events_created
                ON events(created_at);
        """)
        conn.commit()
    print("[✓] Schema initialized")


INSERT_SQL = """
    INSERT INTO events (
        event_id, event_type, user_id, session_id,
        device, browser, country, page_path, referrer, duration_sec,
        query, product_id, product_name, amount, quantity,
        error_code, error_message, created_at
    ) VALUES (
        %(event_id)s, %(event_type)s, %(user_id)s, %(session_id)s,
        %(device)s, %(browser)s, %(country)s, %(page_path)s, %(referrer)s, %(duration_sec)s,
        %(query)s, %(product_id)s, %(product_name)s, %(amount)s, %(quantity)s,
        %(error_code)s, %(error_message)s, %(created_at)s
    )
    ON CONFLICT (event_id) DO NOTHING;
"""


def save_events(conn, events: list[dict]):
    with conn.cursor() as cur:
        execute_batch(cur, INSERT_SQL, events, page_size=500)
    conn.commit()
    print(f"[✓] Saved {len(events)} events to DB")


# ── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    N_EVENTS = int(os.getenv("N_EVENTS", 5000))
    SPREAD_HOURS = int(os.getenv("SPREAD_HOURS", 24))

    print(f"[*] Generating {N_EVENTS} events over {SPREAD_HOURS}h window…")
    events = generate_events(N_EVENTS, SPREAD_HOURS)

    # 타입별 분포 출력
    from collections import Counter
    dist = Counter(e["event_type"] for e in events)
    for k, v in sorted(dist.items()):
        print(f"    {k:12s}: {v:5d}  ({v/N_EVENTS*100:.1f}%)")

    wait_for_db()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        init_schema(conn)
        save_events(conn, events)
    finally:
        conn.close()

    print("[✓] Done — generator finished")
