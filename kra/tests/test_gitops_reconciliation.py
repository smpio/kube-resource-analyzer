import importlib
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase as DBTestCase, override_settings
from django.utils import timezone
from kubernetes import client

from kra import gitops, models

reconciliation = importlib.import_module('kra.tasks.reconcile_gitops_adjustments')

RESULT = {
    'target': 'git', 'mode': 'direct', 'application': 'my-app',
    'repo_url': 'git@github.com:acme/config.git', 'branch': 'main',
    'path': 'manifests/api.yaml', 'commit': 'change', 'sync_status': 'awaiting_argo_sync',
}
APPLICATION = {
    'spec': {'source': {
        'repoURL': RESULT['repo_url'], 'targetRevision': 'main', 'path': 'manifests'}},
    'status': {'sync': {'status': 'Synced', 'revision': 'change'}, 'health': {'status': 'Healthy'}},
}


@override_settings(GITHUB_TOKEN='test-token')
class SyncConfirmationTests(SimpleTestCase):
    def setUp(self):
        self.application = deepcopy(APPLICATION)
        patcher = mock.patch.object(gitops.kube_client, 'CustomObjectsApi')
        self.api = patcher.start().return_value
        self.api.get_namespaced_custom_object.return_value = self.application
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(gitops, 'GitHubClient')
        self.github = patcher.start().return_value
        self.addCleanup(patcher.stop)

    def test_waits_for_sync_and_health(self):
        for sync, health in [('OutOfSync', 'Healthy'), ('Synced', 'Progressing'), ('Unknown', 'Healthy')]:
            with self.subTest(sync=sync, health=health):
                self.application['status']['sync']['status'] = sync
                self.application['status']['health']['status'] = health
                self.assertIsNone(gitops.synced_revision(RESULT))
        self.github._request.assert_not_called()

    def test_confirms_the_exact_commit(self):
        self.assertEqual(gitops.synced_revision(RESULT), 'change')
        self.github._request.assert_not_called()

    def test_accepts_a_later_revision_containing_the_change(self):
        self.application['status']['sync']['revision'] = 'later'
        self.github._request.return_value = {'status': 'ahead'}
        self.assertEqual(gitops.synced_revision(RESULT), 'later')
        self.github._request.assert_called_once_with('GET', '/repos/acme/config/compare/change...later')

    def test_rejects_old_or_diverged_revisions(self):
        self.application['status']['sync']['revision'] = 'other'
        for status in ['behind', 'diverged']:
            self.github._request.return_value = {'status': status}
            self.assertIsNone(gitops.synced_revision(RESULT))

    def test_rejects_a_different_application_source(self):
        self.application['spec']['source']['path'] = 'other'
        with self.assertRaisesRegex(gitops.GitOpsError, 'source changed'):
            gitops.synced_revision(RESULT)

    def test_handles_squash_merged_prs_and_waits_for_merge(self):
        result = {**RESULT, 'mode': 'pull_request', 'pull_request': 17}
        self.github._request.return_value = {'merged': False}
        self.assertIsNone(gitops.synced_revision(result))
        self.application['status']['sync']['revision'] = 'squash'
        self.github._request.return_value = {'merged': True, 'merge_commit_sha': 'squash'}
        self.assertEqual(gitops.synced_revision(result), 'squash')


class GitOpsReconciliationTests(DBTestCase):
    def setUp(self):
        self.workload = models.Workload.objects.create(
            kind=models.WorkloadKind.Deployment, namespace='default', name='api')
        self.summary = models.Summary.objects.create(
            workload=self.workload, container_name='app', memory_limit_mi=256,
            max_memory_mi=465, avg_memory_mi=200, stddev_memory_mi=10,
            cpu_request_m=100, max_cpu_m=100, avg_cpu_m=100, stddev_cpu_m=0)
        self.suggestion = models.Suggestion.objects.create(
            summary=self.summary, new_memory_limit_mi=512, priority=256)
        self.result = models.OperationResult.objects.create(finished_at=timezone.now(), data=deepcopy(RESULT))
        self.adjustment = models.Adjustment.objects.create(
            workload=self.workload, scheduled_for=timezone.now(), result=self.result)
        models.ContainerAdjustment.objects.create(
            adjustment=self.adjustment, container_name='app', new_memory_limit_mi=512)
        self.obj = SimpleNamespace(
            metadata=SimpleNamespace(resource_version='102', annotations={
                gitops.TRACKING_ID: 'my-app:apps/Deployment:default/api'}),
            spec=SimpleNamespace(template=SimpleNamespace(spec=SimpleNamespace(containers=[
                client.V1Container(name='app', resources=client.V1ResourceRequirements(
                    limits={'memory': '512Mi'}, requests={'cpu': '100m'})),
            ]))))
        patches = [
            mock.patch.object(reconciliation, 'get_lock', side_effect=lambda *a: nullcontext(True)),
            mock.patch.object(reconciliation.gitops, 'synced_revision', return_value='later'),
            mock.patch.object(reconciliation.kube, 'get_workload_obj', return_value=self.obj),
        ]
        self.mocks = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)

    def reconcile(self):
        reconciliation.reconcile_adjustment(self.adjustment.id)
        self.summary.refresh_from_db()
        self.result.refresh_from_db()

    def test_updates_summary_removes_fulfilled_suggestion_and_is_idempotent(self):
        self.reconcile()
        self.assertEqual(self.summary.memory_limit_mi, 512)
        self.assertFalse(models.Suggestion.objects.filter(summary=self.summary).exists())
        self.assertEqual(self.result.data['sync_status'], 'synced')
        self.assertEqual(self.result.data['synced_revision'], 'later')
        self.assertEqual(self.result.data['resource_version'], '102')
        self.assertTrue(self.result.data['verified'])
        self.reconcile()
        self.assertEqual(self.mocks[1].call_count, 1)

    def test_waiting_sync_keeps_summary_and_suggestion(self):
        self.mocks[1].return_value = None
        self.reconcile()
        self.assertEqual(self.summary.memory_limit_mi, 256)
        self.assertTrue(models.Suggestion.objects.filter(pk=self.suggestion.pk).exists())
        self.assertEqual(self.result.data['sync_status'], 'awaiting_argo_sync')

    def test_live_resource_mismatch_cannot_complete_an_adjustment(self):
        self.obj.spec.template.spec.containers[0].resources.limits['memory'] = '256Mi'
        with self.assertRaisesRegex(ValueError, 'memory limit was not applied'):
            self.reconcile()
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.memory_limit_mi, 256)
        self.assertTrue(models.Suggestion.objects.filter(pk=self.suggestion.pk).exists())

    def test_keeps_unfulfilled_cpu_recommendation_and_other_containers(self):
        self.summary.avg_cpu_m = self.summary.max_cpu_m = 200
        self.summary.save()
        sidecar = models.Summary.objects.create(
            workload=self.workload, container_name='sidecar', memory_limit_mi=64,
            max_memory_mi=80, avg_memory_mi=60, stddev_memory_mi=0,
            cpu_request_m=10, max_cpu_m=10, avg_cpu_m=10, stddev_cpu_m=0)
        other = models.Suggestion.objects.create(summary=sidecar, new_memory_limit_mi=88, priority=24)
        self.reconcile()
        suggestion = models.Suggestion.objects.get(summary=self.summary)
        self.assertIsNone(suggestion.new_memory_limit_mi)
        self.assertEqual(suggestion.new_cpu_request_m, 200)
        self.assertEqual(self.summary.cpu_request_m, 100)
        self.assertTrue(models.Suggestion.objects.filter(pk=other.pk).exists())

    def test_preserves_a_newer_memory_recommendation(self):
        self.summary.max_memory_mi = 600
        self.summary.save()
        self.reconcile()
        suggestion = models.Suggestion.objects.get(summary=self.summary)
        self.assertEqual(suggestion.new_memory_limit_mi, 660)

    def test_rejects_a_workload_managed_by_another_application(self):
        self.obj.metadata.annotations[gitops.TRACKING_ID] = 'other:apps/Deployment:default/api'
        with self.assertRaisesRegex(gitops.GitOpsError, 'original Application'):
            self.reconcile()
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.memory_limit_mi, 256)

    def test_recalculation_failure_rolls_back_the_summary_and_result(self):
        with mock.patch.object(reconciliation, 'make_suggestion', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                self.reconcile()
        self.summary.refresh_from_db()
        self.result.refresh_from_db()
        self.assertEqual(self.summary.memory_limit_mi, 256)
        self.assertEqual(self.result.data['sync_status'], 'awaiting_argo_sync')
        self.assertTrue(models.Suggestion.objects.filter(pk=self.suggestion.pk).exists())

    def test_failed_check_is_retried_by_next_scan(self):
        self.mocks[1].side_effect = [RuntimeError('API unavailable'), 'later']
        with self.assertLogs(reconciliation.log, level='ERROR'):
            reconciliation.reconcile_gitops_adjustments()
        self.result.refresh_from_db()
        self.assertEqual(self.result.data['sync_status'], 'awaiting_argo_sync')
        reconciliation.reconcile_gitops_adjustments()
        self.result.refresh_from_db()
        self.assertEqual(self.result.data['sync_status'], 'synced')
