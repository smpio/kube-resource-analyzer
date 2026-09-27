from types import SimpleNamespace
from unittest import TestCase, mock

from django.test import override_settings

from kra import gitops
from kra.models import WorkloadKind
from kra.tasks.apply_adjustment import _apply_adjustment


def workload():
    return SimpleNamespace(kind=WorkloadKind.Deployment, namespace='default', name='api')


def adjustment(name='app', memory=512, cpu=200):
    return SimpleNamespace(container_name=name, new_memory_limit_mi=memory, new_cpu_request_m=cpu)


MANIFEST = '''\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: default
spec:
  template:
    spec:
      containers:
      - name: app
        image: example/api:v1
        resources:
          limits:
            cpu: 500m
            memory: 256Mi
          requests:
            memory: 64Mi
            cpu: 100m
'''


class ManifestUpdateTests(TestCase):
    def test_updates_only_requested_resource_dimensions(self):
        updated = gitops.update_manifest_resources(MANIFEST, workload(), [adjustment()])

        self.assertIn('memory: 512Mi', updated)
        self.assertIn('cpu: 200m', updated)
        self.assertIn('cpu: 500m', updated)
        self.assertIn('memory: 64Mi', updated)
        self.assertIn('image: example/api:v1', updated)

    def test_returns_none_when_resources_are_not_declared(self):
        manifest = MANIFEST.replace('        resources:\n          limits:\n            cpu: 500m\n            memory: 256Mi\n          requests:\n            memory: 64Mi\n            cpu: 100m\n', '')

        self.assertIsNone(gitops.update_manifest_resources(manifest, workload(), [adjustment()]))

    def test_rejects_missing_adjusted_container(self):
        with self.assertRaisesRegex(gitops.GitOpsError, 'no containers: missing'):
            gitops.update_manifest_resources(MANIFEST, workload(), [adjustment(name='missing')])


class ArgoResolutionTests(TestCase):
    def test_parses_and_validates_tracking_id(self):
        self.assertEqual(
            gitops._application_name('my-app:apps/Deployment:default/api', workload()), 'my-app')

    def test_rejects_tracking_id_for_a_different_workload(self):
        with self.assertRaisesRegex(gitops.GitOpsError, 'does not identify'):
            gitops._application_name('my-app:apps/Deployment:default/other', workload())

    @override_settings(GITHUB_TOKEN='test-token')
    def test_direct_mode_reports_git_target(self):
        adj = SimpleNamespace(
            id=9, workload=workload(), containers=SimpleNamespace(all=lambda: [adjustment()]))
        workload_obj = SimpleNamespace(metadata=SimpleNamespace(annotations={
            gitops.TRACKING_ID: 'my-app:apps/Deployment:default/api'}))
        application = {'spec': {'source': {
            'repoURL': 'git@github.com:acme/config.git', 'path': 'manifests', 'targetRevision': 'main'}}}
        client = mock.Mock()
        client.list_files.return_value = ['manifests/api.yaml']
        client.get_file.return_value = MANIFEST
        client.commit_file.return_value = {'sha': 'abc123'}

        with mock.patch.object(gitops.kube_client, 'CustomObjectsApi') as custom_api, \
                mock.patch.object(gitops, 'GitHubClient', return_value=client):
            custom_api.return_value.get_namespaced_custom_object.return_value = application
            result = gitops.apply_adjustment(adj, workload_obj)

        self.assertEqual(result['target'], 'git')
        self.assertEqual(result['mode'], 'direct')
        self.assertEqual(result['sync_status'], 'awaiting_argo_sync')
        client.commit_file.assert_called_once()

    @override_settings(GITHUB_TOKEN='test-token', GITOPS_MODE='pull_request')
    def test_pull_request_mode_creates_adjustment_branch_and_pr(self):
        adj = SimpleNamespace(
            id=9, workload=workload(), containers=SimpleNamespace(all=lambda: [adjustment()]))
        workload_obj = SimpleNamespace(metadata=SimpleNamespace(annotations={
            gitops.TRACKING_ID: 'my-app:apps/Deployment:default/api'}))
        application = {'spec': {'source': {
            'repoURL': 'git@github.com:acme/config.git', 'path': 'manifests', 'targetRevision': 'main'}}}
        client = mock.Mock()
        client.list_files.return_value = ['manifests/api.yaml']
        client.get_file.return_value = MANIFEST
        client.commit_file.return_value = {'sha': 'abc123'}
        client.create_pull_request.return_value = {'number': 17, 'html_url': 'https://github.com/acme/config/pull/17'}

        with mock.patch.object(gitops.kube_client, 'CustomObjectsApi') as custom_api, \
                mock.patch.object(gitops, 'GitHubClient', return_value=client):
            custom_api.return_value.get_namespaced_custom_object.return_value = application
            result = gitops.apply_adjustment(adj, workload_obj)

        self.assertEqual(result['mode'], 'pull_request')
        self.assertEqual(result['pull_request'], 17)
        self.assertEqual(result['sync_status'], 'awaiting_pull_request_merge')
        self.assertEqual(client.commit_file.call_args.args[1], 'kra/adjustment-9')
        self.assertEqual(client.commit_file.call_args.kwargs['base_branch'], 'main')

    @override_settings(GITHUB_TOKEN='test-token')
    def test_does_not_fall_back_to_cluster_when_manifest_is_missing(self):
        adj = SimpleNamespace(
            id=9, workload=workload(), containers=SimpleNamespace(all=lambda: [adjustment()]))
        workload_obj = SimpleNamespace(metadata=SimpleNamespace(annotations={
            gitops.TRACKING_ID: 'my-app:apps/Deployment:default/api'}))
        application = {'spec': {'source': {
            'repoURL': 'git@github.com:acme/config.git', 'path': 'manifests', 'targetRevision': 'main'}}}
        client = mock.Mock()
        client.list_files.return_value = ['manifests/other.yaml']
        client.get_file.return_value = MANIFEST.replace('name: api', 'name: other')

        with mock.patch.object(gitops.kube_client, 'CustomObjectsApi') as custom_api, \
                mock.patch.object(gitops, 'GitHubClient', return_value=client):
            custom_api.return_value.get_namespaced_custom_object.return_value = application
            with self.assertRaisesRegex(gitops.GitOpsError, 'No manifest'):
                gitops.apply_adjustment(adj, workload_obj)


class ApplyAdjustmentGitOpsTests(TestCase):
    def test_returns_gitops_result_without_a_kubernetes_patch(self):
        workload_obj = SimpleNamespace()
        adj = SimpleNamespace(workload=workload())
        expected = {'target': 'git', 'sync_status': 'awaiting_argo_sync'}

        with mock.patch('kra.tasks.apply_adjustment.kube.get_workload_obj', return_value=workload_obj), \
                mock.patch('kra.tasks.apply_adjustment.gitops.apply_adjustment', return_value=expected), \
                mock.patch('kra.tasks.apply_adjustment.kube.patch_funcs') as patch_funcs:
            self.assertEqual(_apply_adjustment(adj), expected)

        patch_funcs.__getitem__.assert_not_called()
