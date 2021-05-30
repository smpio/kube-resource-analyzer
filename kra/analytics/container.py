from kra import models


def get_containers_summary():
    return models.Container.objects.raw(r"""
    SELECT
        *
    FROM %(container_tblname)s AS c
    LEFT JOIN LATERAL (
        SELECT * FROM (
            SELECT
                since,
                till,
                total_seconds,
                total_cpu_m_seconds,
                max_memory_mi,
                total_memory_mi_seconds,
                (total_memory_mi_seconds / total_seconds) AS avg_memory_mi,
                (total_cpu_m_seconds / total_seconds) AS avg_cpu_m
            FROM (
                SELECT
                    *,
                    (
                        CASE
                            WHEN till IS NULL
                                THEN NULL
                            WHEN till <> since
                                THEN extract(epoch FROM (till - since))
                                ELSE 30
                            END
                    ) AS total_seconds
                FROM (
                    SELECT
                        min(measured_at) AS since,
                        max(measured_at) AS till,
                        max(cpu_m) AS max_cpu_m,
                        max(cpu_m_seconds) AS total_cpu_m_seconds,
                        max(memory_mi) AS max_memory_mi,
                        sum(memory_mi_seconds) AS total_memory_mi_seconds
                    FROM (
                        SELECT
                            *,
                            memory_mi * interval_seconds AS memory_mi_seconds,
                            cpu_m_seconds / interval_seconds AS cpu_m
                        FROM (
                            SELECT
                                measured_at,
                                cpu_m_seconds,
                                memory_mi,
                                (
                                    CASE
                                        WHEN lag(measured_at) OVER w IS NOT NULL
                                            THEN extract(epoch FROM (measured_at - lag(measured_at) OVER w))
                                            ELSE 30
                                    END
                                ) AS interval_seconds
                            FROM %(ru_tblname)s
                            WHERE container_id = c.id
                            WINDOW w AS (ORDER BY measured_at)
                        ) AS pass1q0
                    ) AS pass1q1
                ) AS pass1q2
            ) AS pass1q3
        ) AS pass1
        LEFT JOIN LATERAL (
            SELECT
                sqrt(total_stddev_memory_mi2_seconds / total_seconds) AS memory_mi_stddev,
                sqrt(total_stddev_cpu_m2_seconds / total_seconds) AS cpu_m_stddev
            FROM (
                SELECT
                    sum(stddev_memory_mi2_seconds) AS total_stddev_memory_mi2_seconds,
                    sum(stddev_cpu_m2_seconds) AS total_stddev_cpu_m2_seconds
                FROM (
                    SELECT
                        ((memory_mi - avg_memory_mi)^2 * interval_seconds) AS stddev_memory_mi2_seconds,
                        ((cpu_m_seconds / interval_seconds - avg_cpu_m)^2 * interval_seconds) AS stddev_cpu_m2_seconds
                    FROM (
                        SELECT
                            cpu_m_seconds,
                            memory_mi,
                            (
                                CASE
                                    WHEN lag(measured_at) OVER w IS NOT NULL
                                        THEN extract(epoch FROM (measured_at - lag(measured_at) OVER w))
                                        ELSE 30
                                END
                            ) AS interval_seconds
                        FROM %(ru_tblname)s
                        WHERE container_id = c.id
                        WINDOW w AS (ORDER BY measured_at)
                    ) AS pass2q0
                ) AS pass2q1
            ) AS pass2q2
        ) AS pass2 ON TRUE
    ) AS summary ON TRUE
    WHERE total_seconds IS NOT NULL
    """ % {
        'container_tblname': models.Container._meta.db_table,
        'ru_tblname': models.ResourceUsage._meta.db_table,
    })
