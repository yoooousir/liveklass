## 실행 방법

**필요한 도구**

- Docker Desktop (또는 Docker Engine + Docker Compose v2)

**설치 및 실행**

```bash
# 저장소 클론
git clone <repo-url>
cd web-event-pipeline

# 전체 스택 빌드 & 실행 (DB 기동 → 이벤트 생성 → 분석 → 차트 저장)
docker compose up --build

# 백그라운드 실행
docker compose up --build -d

# 실시간 로그 확인
docker compose logs -f app
```

`docker compose up` 완료 후 `./charts/` 폴더에 아래 파일이 생성됩니다.

| 파일 | 내용 |
|---|---|
| `1_event_type_count.png` | 이벤트 타입별 발생 횟수 (막대 그래프) |
| `2_top_users.png`        | 유저별 총 이벤트 수 Top 20 (누적 막대) |
| `3_hourly_trend.png`     | 시간대별 이벤트 추이 (라인 차트) |
| `4_error_analysis.png`   | 에러 비율 도넛 + HTTP 코드 분포 |


**이벤트 수 조정(선택)**
```bash
# 환경변수로 생성 건수 변경 (기본값 5000)
N_EVENTS=10000 docker compose up --build
```

**선택: DB 직접 접속**

```bash
psql -h localhost -p 5432 -U eventuser -d eventdb
```

---

## 스키마 설명
### [1] 이벤트 설계

#### 이벤트 타입 5종

| event_type | 비율 | 설명 | 핵심 추가 필드 |
|---|---|---|---|
| `page_view` | 45 % | 페이지 방문 | `page_path`, `referrer`, `duration_sec` |
| `search`    | 20 % | 검색 실행 | `query` |
| `purchase`  | 10 % | 결제 완료 | `product_id`, `product_name`, `amount`, `quantity` |
| `error`     | 10 % | HTTP 에러 발생 | `error_code`, `error_message` |
| `logout`    | 15 % | 세션 종료 | — |

#### 설계 이유
- **비율 설계** — 실제 e-커머스 funnel(조회→탐색→구매)을 반영했습니다. 구매는 전체의 10 %로 낮게 설정해 전환율 분석이 의미있도록 했습니다.
- **공통 필드** — `user_id`, `session_id`, `device`, `browser`, `country`를 모든 이벤트에 포함해 세그먼트 분석이 가능하게 했습니다.
- **이벤트별 전용 필드** — 타입마다 필요한 필드만 채우고 나머지는 NULL. 단일 테이블로 관리하면서도 sparse하게 설계했습니다.
- **타임스탬프 분산** — 시간대별 추이 분석이 가능하도록 하기 위해 24시간 범위에 랜덤 분포시켰습니다.

---

### [2] 저장소 설계
#### PostgreSQL 선택 이유
1. **필드 구분 저장** — JSON 덤프 없이 각 컬럼을 명시적으로 분리해 쿼리 최적화가 용이합니다.
2. **집계 쿼리 표현력** — `FILTER (WHERE ...)`, `OVER()` 윈도우 함수, `DATE_TRUNC` 등 분석 SQL을 간결하게 작성할 수 있습니다.
3. **인덱스 활용** — `event_type`, `user_id`, `created_at` 에 인덱스를 걸어 집계가 가능하도록 했습니다.
4. **Docker 공식 이미지** — `postgres:16-alpine`를 선택하여 컨테이너 실행이 용이합니다.

#### 스키마
```sql
CREATE TABLE events (
    event_id      UUID         PRIMARY KEY,       -- 중복 방지
    event_type    VARCHAR(20)  NOT NULL,           -- page_view|search|purchase|error|logout
    user_id       VARCHAR(20)  NOT NULL,           -- 유저 식별자
    session_id    UUID         NOT NULL,           -- 세션 식별자
    device        VARCHAR(10),                     -- desktop|mobile|tablet
    browser       VARCHAR(20),                     -- Chrome|Safari|Firefox|Edge
    country       CHAR(2),                         -- ISO 국가 코드
    -- page_view 전용
    page_path     VARCHAR(100),
    referrer      VARCHAR(50),
    duration_sec  INTEGER,
    -- search 전용
    query         VARCHAR(200),
    -- purchase 전용
    product_id    VARCHAR(10),
    product_name  VARCHAR(100),
    amount        NUMERIC(10,2),
    quantity      INTEGER,
    -- error 전용
    error_code    SMALLINT,
    error_message VARCHAR(100),
    -- 공통
    created_at    TIMESTAMP    NOT NULL
);

-- 집계 성능용 인덱스
CREATE INDEX idx_events_type    ON events(event_type);
CREATE INDEX idx_events_user    ON events(user_id);
CREATE INDEX idx_events_created ON events(created_at);
```

이벤트 타입마다 의미 있는 필드만 채우고 나머지는 NULL로 두는 **단일 테이블 sparse 설계**를 선택했습니다. 이벤트 종류가 5개로 적고, 조인 없이 타입별 집계를 한 쿼리로 처리할 수 있다는 점에서 테이블 분리보다 유리하다고 판단했습니다.

#### 데이터 집계 분석 쿼리

전체 쿼리는 [`sql/analytics.sql`](sql/analytics.sql) 참조.

---

## 구현하면서 고민한 점

### 저장소: SQLite vs PostgreSQL

처음에는 파일 하나로 끝나는 SQLite를 고려했습니다. 그런데 Docker Compose에서 app 컨테이너와 db 컨테이너가 동시에 SQLite 파일에 접근하면 락 충돌이 생길 수 있고, `SUM(COUNT(*)) OVER()` 같은 윈도우 함수를 SQLite가 일부 지원하지 않는다는 점이 걸렸습니다. 분석 쿼리를 타협하기 싫어서 PostgreSQL로 결정했습니다.

### 스키마: 테이블 분리 vs 단일 테이블

이벤트 타입마다 전용 테이블을 만드는 방식도 고려했습니다. 하지만 "유저별 총 이벤트 수"처럼 타입을 한꺼번에 집계할 때 조인이 필요해져 쿼리가 복잡해집니다. 이벤트 수 5,000건 규모에서 NULL 컬럼 오버헤드는 무시할 수 있다고 보고, 단일 테이블로 단순하게 가기로 했습니다.

### Docker Compose healthcheck 타이밍

app 컨테이너가 db보다 먼저 뜨면 psycopg2 연결 오류로 바로 죽습니다. `depends_on: condition: service_healthy`와 PostgreSQL healthcheck(`pg_isready`)를 조합해서 DB가 완전히 준비된 뒤에 앱이 실행되도록 했고, 혹시 모를 경우를 대비해 generator.py 안에도 재시도 로직(`wait_for_db`)을 넣었습니다.

---

## 프로젝트 구조
```
web-event-pipeline/
├── app/
│   ├── generator.py      # Step 1·2: 이벤트 생성 & DB 저장
│   ├── analytics.py      # Step 3·5: SQL 집계 & 차트 생성
│   ├── entrypoints.sh     # generator → analytics 순 실행
│   ├── requirements.txt
│   └── Dockerfile
├── sql/
│   └── analytics.sql     # Step 3: 집계 쿼리 모음
├── charts/               # Step 5: 시각화 결과 PNG (실행 후 생성)
├── docker-compose.yml    # Step 4
└── README.md
```
