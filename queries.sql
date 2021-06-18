-- Query examples

-- TimescaleDB request for time-weighted aggregations: https://github.com/timescale/timescaledb/issues/2536
-- Weighted stdDev and mean formulas: https://stats.stackexchange.com/a/6536

-- Avg single container
SELECT
    *,
    (total_memory_mi_seconds / total_seconds) AS avg_memory_mi
FROM (
    SELECT 
        *,
        extract(epoch FROM (till - since)) AS total_seconds
    FROM (
        SELECT 
            min(measured_at) AS since, 
            max(measured_at) AS till,
            sum(memory_mi_seconds) AS total_memory_mi_seconds
        FROM (
            SELECT
                measured_at,
                (memory_mi * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS memory_mi_seconds
            FROM kra_resourceusage
            WHERE container_id=262458
            WINDOW w AS (ORDER BY measured_at)
        ) AS weighted1
    ) AS aggr1
) AS aggr2
;

-- StdDev single container (second pass)
SELECT
    *,
    sqrt(total_stddev_memory_mi2_seconds / total_seconds) AS memory_mi_stddev
FROM (
    SELECT 
        *,
        extract(epoch FROM (till - since)) AS total_seconds
    FROM (
        SELECT 
            min(measured_at) AS since, 
            max(measured_at) AS till,
            sum(stddev_memory_mi2_seconds) AS total_stddev_memory_mi2_seconds
        FROM (
            SELECT
                measured_at,
                ((memory_mi - avg_memory_mi)^2 * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS stddev_memory_mi2_seconds
            FROM kra_resourceusage
            WHERE container_id=CONTAINER_ID
            WINDOW w AS (ORDER BY measured_at)
        ) AS weighted1
    ) AS aggr1
) AS aggr2
;

-- Avg all containers
SELECT
    *
FROM kra_container AS c
LEFT JOIN LATERAL (
    SELECT
        *,
        (total_memory_mi_seconds / total_seconds) AS avg_memory_mi
    FROM (
        SELECT 
            *,
            extract(epoch FROM (till - since)) AS total_seconds
        FROM (
            SELECT 
                min(measured_at) AS since, 
                max(measured_at) AS till,
                sum(memory_mi_seconds) AS total_memory_mi_seconds
            FROM (
                SELECT
                    measured_at,
                    (memory_mi * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS memory_mi_seconds
                FROM kra_resourceusage
                WHERE container_id=c.id
                WINDOW w AS (ORDER BY measured_at)
            ) AS q1
        ) AS q2
    ) AS q3
) AS aggr ON TRUE
;

-- Single container 2-passes
SELECT * FROM (
    SELECT
        *,
        (total_memory_mi_seconds / total_seconds) AS avg_memory_mi
    FROM (
        SELECT 
            *,
            extract(epoch FROM (till - since)) AS total_seconds
        FROM (
            SELECT 
                min(measured_at) AS since, 
                max(measured_at) AS till,
                sum(memory_mi_seconds) AS total_memory_mi_seconds
            FROM (
                SELECT
                    measured_at,
                    (memory_mi * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS memory_mi_seconds
                FROM kra_resourceusage
                WHERE container_id=262458
                WINDOW w AS (ORDER BY measured_at)
            ) AS weighted1
        ) AS aggr1
    ) AS aggr2
) AS pass1
LEFT JOIN LATERAL (
    SELECT
        *,
        sqrt(total_stddev_memory_mi2_seconds / total_seconds) AS memory_mi_stddev
    FROM (
        SELECT 
            *,
            extract(epoch FROM (till - since)) AS total_seconds
        FROM (
            SELECT 
                min(measured_at) AS since, 
                max(measured_at) AS till,
                sum(stddev_memory_mi2_seconds) AS total_stddev_memory_mi2_seconds
            FROM (
                SELECT
                    measured_at,
                    ((memory_mi - pass1.avg_memory_mi)^2 * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS stddev_memory_mi2_seconds
                FROM kra_resourceusage
                WHERE container_id=262458
                WINDOW w AS (ORDER BY measured_at)
            ) AS pass2_weighted1
        ) AS pass2_aggr1
    ) AS pass2_aggr2
) AS pass2 ON TRUE
;

-- Single container 2-passes (CLEANIZED)
SELECT * FROM (
    SELECT
        since,
        till,
        total_seconds,
        (total_memory_mi_seconds / total_seconds) AS avg_memory_mi
    FROM (
        SELECT 
            *,
            extract(epoch FROM (till - since)) AS total_seconds
        FROM (
            SELECT 
                min(measured_at) AS since, 
                max(measured_at) AS till,
                sum(memory_mi_seconds) AS total_memory_mi_seconds
            FROM (
                SELECT
                    measured_at,
                    (memory_mi * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS memory_mi_seconds
                FROM kra_resourceusage
                WHERE container_id=262458
                WINDOW w AS (ORDER BY measured_at)
            ) AS weighted1
        ) AS aggr1
    ) AS aggr2
) AS pass1
LEFT JOIN LATERAL (
    SELECT
        sqrt(total_stddev_memory_mi2_seconds / total_seconds) AS memory_mi_stddev
    FROM (
        SELECT 
            sum(stddev_memory_mi2_seconds) AS total_stddev_memory_mi2_seconds
        FROM (
            SELECT
                measured_at,
                ((memory_mi - avg_memory_mi)^2 * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS stddev_memory_mi2_seconds
            FROM kra_resourceusage
            WHERE container_id=262458
            WINDOW w AS (ORDER BY measured_at)
        ) AS pass2_weighted1
    ) AS pass2_aggr2
) AS pass2 ON TRUE
;

-- All containers 2-passes (CLEANIZED)
SELECT
    *
FROM kra_container AS c
LEFT JOIN LATERAL (
    SELECT * FROM (
        SELECT
            since,
            till,
            total_seconds,
            max_memory_mi,
            (total_memory_mi_seconds / total_seconds) AS avg_memory_mi
        FROM (
            SELECT 
                *,
                extract(epoch FROM (till - since)) AS total_seconds
            FROM (
                SELECT 
                    min(measured_at) AS since, 
                    max(measured_at) AS till,
                    max(memory_mi) AS max_memory_mi,
                    sum(memory_mi_seconds) AS total_memory_mi_seconds
                FROM (
                    SELECT
                        measured_at,
                        memory_mi,
                        (memory_mi * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS memory_mi_seconds
                    FROM kra_resourceusage
                    WHERE container_id = c.id
                    WINDOW w AS (ORDER BY measured_at)
                ) AS pass1q1
            ) AS pass1q2
        ) AS pass1q3
    ) AS pass1
    LEFT JOIN LATERAL (
        SELECT
            sqrt(total_stddev_memory_mi2_seconds / total_seconds) AS memory_mi_stddev
        FROM (
            SELECT 
                sum(stddev_memory_mi2_seconds) AS total_stddev_memory_mi2_seconds
            FROM (
                SELECT
                    ((memory_mi - avg_memory_mi)^2 * extract(epoch FROM (measured_at - lag(measured_at) OVER w))) AS stddev_memory_mi2_seconds
                FROM kra_resourceusage
                WHERE container_id = c.id
                WINDOW w AS (ORDER BY measured_at)
            ) AS pass2q1
        ) AS pass2q2
    ) AS pass2 ON TRUE
) AS summary ON TRUE
;


-- ResourceUsage buckets for multiple containers
SELECT
    "kra_resourceusage"."container_id",
    time_bucket('5434 seconds', "kra_resourceusage"."measured_at") AS "ts",
    MAX("kra_resourceusage"."memory_mi") AS "memory_mi",
    MAX("kra_resourceusage"."cpu_m_seconds") AS "cpu_m_seconds"
FROM "kra_resourceusage"
WHERE "kra_resourceusage"."container_id" IN (281770, 281766, 281780, 281774, 281789, 283592, 283674, 283676, 283686, 283683, 284484, 284500, 284498, 284483, 284494, 290202)
GROUP BY "kra_resourceusage"."container_id", "ts"
ORDER BY "kra_resourceusage"."container_id" ASC, "ts" ASC;
