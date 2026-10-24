from kra import models


def get_containers_summary(container_ids=None):
    params = []
    container_filter = ''
    if container_ids is not None:
        container_ids = list(container_ids)
        if not container_ids:
            return models.Container.objects.none()
        container_filter = 'WHERE ru.container_id = ANY(%s)'
        params.append(container_ids)

    # Aggregate all selected containers together instead of running two
    # correlated history scans per container. Numeric second moments preserve
    # the time-weighted statistics without rereading samples for deviations.
    # OFFSET 0 keeps the history scan independent of the window's ordering:
    # batches use a sequential scan and sort, not random heap reads through
    # the (container_id, measured_at) index. It avoids materializing a second
    # full copy on disk; a selected workload can still use the ID index.
    # Keep fractional precision before subtracting large second moments.
    return models.Container.objects.raw(r"""
    WITH selected_usage AS (
        SELECT container_id, measured_at, memory_mi, cpu_m_seconds
        FROM %(ru_tblname)s AS ru
        %(container_filter)s
        OFFSET 0
    ), samples AS (
        SELECT ru.*, c.started_at,
            extract(epoch FROM (
                measured_at - lag(measured_at, 1, c.started_at) OVER w
            )) AS delta_seconds,
            cpu_m_seconds - lag(cpu_m_seconds, 1, 0::bigint) OVER w AS delta_cpu_m_seconds
        FROM selected_usage AS ru
        JOIN %(container_tblname)s AS c ON c.id = ru.container_id
        WINDOW w AS (PARTITION BY container_id ORDER BY measured_at)
    ), totals AS (
        SELECT container_id, min(started_at) AS since, max(measured_at) AS till,
            max(memory_mi) AS max_memory_mi,
            max(cpu_m_seconds) AS total_cpu_m_seconds,
            max(delta_cpu_m_seconds / nullif(delta_seconds, 0)) AS max_cpu_m,
            sum(memory_mi * delta_seconds) AS total_memory_mi_seconds,
            sum(memory_mi::numeric(80, 40) * memory_mi * delta_seconds) AS memory_second_moment,
            sum(delta_cpu_m_seconds::numeric(80, 40) * delta_cpu_m_seconds
                / nullif(delta_seconds, 0)) AS cpu_second_moment,
            sum(CASE WHEN delta_seconds <> 0 THEN delta_cpu_m_seconds ELSE 0 END) AS cpu_delta_total
        FROM samples
        GROUP BY container_id
        HAVING max(measured_at) > min(started_at)
    ), means AS (
        SELECT *, extract(epoch FROM (till - since)) AS total_seconds,
            total_memory_mi_seconds::numeric(80, 40) / extract(epoch FROM (till - since)) AS avg_memory_mi,
            total_cpu_m_seconds::numeric(80, 40) / extract(epoch FROM (till - since)) AS avg_cpu_m
        FROM totals
    )
    SELECT c.*, means.*,
        sqrt(greatest(0, memory_second_moment / total_seconds - avg_memory_mi * avg_memory_mi))
            AS stddev_memory_mi,
        sqrt(greatest(0, cpu_second_moment / total_seconds
            - 2 * avg_cpu_m * cpu_delta_total / total_seconds + avg_cpu_m * avg_cpu_m))
            AS stddev_cpu_m
    FROM means
    JOIN %(container_tblname)s AS c ON c.id = means.container_id
    """ % {
        'container_tblname': models.Container._meta.db_table,
        'ru_tblname': models.ResourceUsage._meta.db_table,
        'container_filter': container_filter,
    }, params=params)
