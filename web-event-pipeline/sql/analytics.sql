-- ============================================================
--  Web Event Analytics Queries
--  대상 테이블: events
-- ============================================================

-- ────────────────────────────────────────────────────────────
--  분석 1. 이벤트 타입별 발생 횟수 및 비율
-- ────────────────────────────────────────────────────────────
SELECT
    event_type,
    COUNT(*)                                          AS cnt,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM   events
GROUP  BY event_type
ORDER  BY cnt DESC;

-- ────────────────────────────────────────────────────────────
--  분석 2. 유저별 총 이벤트 수 (구매·에러 건수 포함) Top 20
-- ────────────────────────────────────────────────────────────
SELECT
    user_id,
    COUNT(*)                                          AS total_events,
    COUNT(*) FILTER (WHERE event_type = 'purchase')   AS purchase_cnt,
    COUNT(*) FILTER (WHERE event_type = 'error')      AS error_cnt,
    ROUND(SUM(amount) FILTER (
        WHERE event_type = 'purchase'), 2)            AS total_revenue
FROM   events
GROUP  BY user_id
ORDER  BY total_events DESC
LIMIT  20;

-- ────────────────────────────────────────────────────────────
--  분석 3. 시간대별 이벤트 추이 (1시간 단위)
-- ────────────────────────────────────────────────────────────
SELECT
    DATE_TRUNC('hour', created_at)                    AS hour,
    COUNT(*)                                          AS total,
    COUNT(*) FILTER (WHERE event_type = 'page_view')  AS page_views,
    COUNT(*) FILTER (WHERE event_type = 'purchase')   AS purchases,
    COUNT(*) FILTER (WHERE event_type = 'error')      AS errors
FROM   events
GROUP  BY hour
ORDER  BY hour;

-- ────────────────────────────────────────────────────────────
--  분석 4. 에러 이벤트 비율 및 HTTP 에러 코드 분포
-- ────────────────────────────────────────────────────────────
-- 4-a. 전체 대비 에러 비율
SELECT
    SUM(CASE WHEN event_type = 'error' THEN 1 ELSE 0 END) AS error_cnt,
    COUNT(*)                                               AS total_cnt,
    ROUND(
        SUM(CASE WHEN event_type = 'error' THEN 1 ELSE 0 END)
        * 100.0 / COUNT(*), 2
    )                                                      AS error_pct
FROM events;

-- 4-b. HTTP 에러 코드별 분포
SELECT
    error_code,
    error_message,
    COUNT(*)                                          AS cnt,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
FROM   events
WHERE  event_type = 'error'
GROUP  BY error_code, error_message
ORDER  BY cnt DESC;

-- ────────────────────────────────────────────────────────────
--  보너스 1. 상품별 매출 Top 10
-- ────────────────────────────────────────────────────────────
SELECT
    product_id,
    product_name,
    COUNT(*)                   AS order_cnt,
    SUM(quantity)              AS total_qty,
    ROUND(SUM(amount), 2)      AS total_revenue,
    ROUND(AVG(amount), 2)      AS avg_order_value
FROM   events
WHERE  event_type = 'purchase'
GROUP  BY product_id, product_name
ORDER  BY total_revenue DESC
LIMIT  10;

-- ────────────────────────────────────────────────────────────
--  보너스 2. 디바이스·브라우저별 에러율
-- ────────────────────────────────────────────────────────────
SELECT
    device,
    browser,
    COUNT(*)                                            AS total,
    COUNT(*) FILTER (WHERE event_type = 'error')        AS errors,
    ROUND(
        COUNT(*) FILTER (WHERE event_type = 'error')
        * 100.0 / COUNT(*), 2
    )                                                   AS error_rate_pct
FROM   events
GROUP  BY device, browser
ORDER  BY error_rate_pct DESC;

-- ────────────────────────────────────────────────────────────
--  보너스 3. 국가별 구매 전환율 (purchase / total)
-- ────────────────────────────────────────────────────────────
SELECT
    country,
    COUNT(*)                                              AS total_events,
    COUNT(*) FILTER (WHERE event_type = 'purchase')       AS purchases,
    ROUND(
        COUNT(*) FILTER (WHERE event_type = 'purchase')
        * 100.0 / COUNT(*), 2
    )                                                     AS conversion_pct,
    ROUND(SUM(amount) FILTER (
        WHERE event_type = 'purchase'), 2)                AS revenue
FROM   events
GROUP  BY country
ORDER  BY revenue DESC NULLS LAST;
