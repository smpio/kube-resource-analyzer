import datetime
import math
import random
import uuid
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from kra import models
from kra.analytics.container import get_containers_summary


class ContainerAnalyticsTests(TestCase):
    def setUp(self):
        self.started_at = timezone.now().replace(microsecond=0)
        self.pod = models.Pod.objects.create(
            uid=str(uuid.uuid4()), namespace='test', name='analytics', started_at=self.started_at,
        )

    def container(self, samples):
        c = models.Container.objects.create(
            pod=self.pod, name='main', runtime_id=uuid.uuid4().hex, started_at=self.started_at,
        )
        models.ResourceUsage.objects.bulk_create([
            models.ResourceUsage(container=c, measured_at=self.started_at + datetime.timedelta(seconds=seconds),
                                 memory_mi=memory, cpu_m_seconds=cpu)
            for seconds, memory, cpu in samples
        ])
        return c

    def assert_statistics(self, c, samples):
        result = list(get_containers_summary([c.id]))[0]
        duration = Decimal(samples[-1][0])
        intervals = []
        previous_time = previous_cpu = 0
        for seconds, memory, cpu in samples:
            dt = Decimal(seconds - previous_time)
            intervals.append((dt, Decimal(memory), Decimal(cpu - previous_cpu) / dt))
            previous_time, previous_cpu = seconds, cpu
        avg_memory = sum(dt * memory for dt, memory, _ in intervals) / duration
        avg_cpu = Decimal(max(cpu for _, _, cpu in samples)) / duration
        memory_variance = sum(dt * (memory - avg_memory) ** 2 for dt, memory, _ in intervals) / duration
        cpu_variance = sum(dt * (cpu - avg_cpu) ** 2 for dt, _, cpu in intervals) / duration
        expected = {
            'max_memory_mi': max(memory for _, memory, _ in samples),
            'max_cpu_m': max(cpu for _, _, cpu in intervals),
            'avg_memory_mi': avg_memory, 'avg_cpu_m': avg_cpu,
            'stddev_memory_mi': memory_variance.sqrt(), 'stddev_cpu_m': cpu_variance.sqrt(),
            'total_seconds': duration, 'total_cpu_m_seconds': max(cpu for _, _, cpu in samples),
            'total_memory_mi_seconds': avg_memory * duration,
        }
        for name, value in expected.items():
            with self.subTest(statistic=name):
                self.assertAlmostEqual(float(getattr(result, name)), float(value), places=7)
        self.assertEqual(result.pk, c.pk)
        self.assertEqual(result.since, c.started_at)
        self.assertEqual(result.till, self.started_at + datetime.timedelta(seconds=samples[-1][0]))

    def test_uneven_intervals_preserve_time_weighted_statistics(self):
        samples = [(60, 100, 6000), (180, 200, 42000), (200, 50, 45000)]
        self.assert_statistics(self.container(samples), samples)

    def test_varied_histories_match_independent_weighted_reference(self):
        rng = random.Random(42)
        for _ in range(12):
            seconds = cpu = 0
            samples = []
            for _ in range(8):
                seconds += rng.randint(1, 300)
                cpu += rng.randint(0, 100_000)
                samples.append((seconds, rng.randint(0, 20_000), cpu))
            self.assert_statistics(self.container(samples), samples)

    def test_counter_decrease_preserves_existing_cpu_mean_and_deviation(self):
        samples = [(60, 100, 6000), (120, 200, 3000)]
        self.assert_statistics(self.container(samples), samples)

    def test_large_constant_values_have_zero_deviation(self):
        samples = [(60 * n, 2_000_000_000, 60 * n * 10**15) for n in range(1, 4)]
        self.assert_statistics(self.container(samples), samples)

    def test_small_deviation_with_large_baselines_does_not_cancel(self):
        samples = [(60, 1_999_999_999, 60 * 10**15), (180, 2_000_000_000, 180 * 10**15 + 60)]
        self.assert_statistics(self.container(samples), samples)

    def test_batch_and_filtered_results_agree_and_omit_missing_history(self):
        first = self.container([(60, 100, 6000), (120, 200, 18000)])
        second = self.container([(20, 10, 400), (60, 30, 1200)])
        self.container([])
        batch = {c.pk: c for c in get_containers_summary()}
        self.assertEqual(set(batch), {first.pk, second.pk})
        for c in get_containers_summary([first.id]):
            self.assertEqual(c.pk, first.pk)
            for field in ['avg_memory_mi', 'stddev_memory_mi', 'avg_cpu_m', 'stddev_cpu_m']:
                self.assertEqual(getattr(c, field), getattr(batch[c.pk], field))

    def test_empty_selection_does_not_query_or_scan_all_history(self):
        self.container([(60, 100, 6000)])
        with self.assertNumQueries(0):
            self.assertEqual(list(get_containers_summary([])), [])

    def test_sample_at_start_does_not_divide_by_zero(self):
        c = self.container([(0, 100, 0), (60, 200, 6000)])
        result = list(get_containers_summary([c.id]))[0]
        self.assertEqual(result.avg_memory_mi, 200)
        self.assertEqual(result.avg_cpu_m, 100)
        self.assertEqual(result.stddev_cpu_m, 0)
        self.assertTrue(math.isfinite(result.stddev_memory_mi))

    def test_zero_duration_history_is_omitted(self):
        self.container([(0, 100, 0)])
        self.assertEqual(list(get_containers_summary()), [])
