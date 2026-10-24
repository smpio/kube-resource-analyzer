from datetime import timedelta

from django.utils import timezone


# Events and kubelet timestamps have different precision and reporting latency.
# A later restart must not promote all earlier child OOMs in the same container.
CRITICAL_OOM_WINDOW = timedelta(seconds=10)


def as_aware_datetime(value):
    # The SDK returns aware datetimes, but USE_TZ=False returns naive DB values.
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_default_timezone())
    return value


def is_critical_oom(container, happened_at):
    return (
        container.oom_killed_at is not None
        and abs(as_aware_datetime(container.oom_killed_at) - as_aware_datetime(happened_at)) <= CRITICAL_OOM_WINDOW
    )


def record_oom_termination(container, terminated):
    """Called while the pod collector holds this container's database row lock."""
    if terminated.reason != 'OOMKilled' or terminated.finished_at is None:
        return

    container.oom_killed_at = terminated.finished_at
    container.save(update_fields=['oom_killed_at'])

    events = container.oomevent_set.filter(
        is_critical=False,
        happened_at__gte=terminated.finished_at - CRITICAL_OOM_WINDOW,
        happened_at__lte=terminated.finished_at + CRITICAL_OOM_WINDOW,
    )
    for event in events:
        event.is_critical = True
        event.save(update_fields=['is_critical'])
