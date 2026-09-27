import importlib
from types import SimpleNamespace
from unittest import TestCase, mock

from kra.models import WorkloadKind
from kra.tasks.apply_adjustment import _apply_adjustment, _get_json_patch_op

apply_adjustment_module = importlib.import_module('kra.tasks.apply_adjustment')


class GetJsonPatchOpTests(TestCase):
    def test_preserves_existing_resource_fields(self):
        resources = SimpleNamespace(to_dict=lambda: {
            'limits': {'memory': '256Mi', 'cpu': '500m'},
            'requests': {'memory': '128Mi', 'cpu': '100m'},
            'claims': [{'name': 'gpu'}],
        })
        container = SimpleNamespace(resources=resources)
        adjustment = SimpleNamespace(new_memory_limit_mi=512, new_cpu_request_m=200)

        patch = _get_json_patch_op(0, WorkloadKind.Deployment, container, adjustment)

        self.assertEqual(patch['op'], 'replace')
        self.assertEqual(patch['value'], {
            'limits': {'memory': '512Mi', 'cpu': '500m'},
            'requests': {'memory': '128Mi', 'cpu': '200m'},
            'claims': [{'name': 'gpu'}],
        })

    def test_adds_resources_when_the_container_has_none(self):
        container = SimpleNamespace(resources=None)
        adjustment = SimpleNamespace(new_memory_limit_mi=64, new_cpu_request_m=None)

        patch = _get_json_patch_op(2, WorkloadKind.Deployment, container, adjustment)

        self.assertEqual(patch['op'], 'add')
        self.assertEqual(patch['value'], {'limits': {'memory': '64Mi'}})

    def test_leaves_an_unspecified_dimension_unchanged(self):
        resources = SimpleNamespace(to_dict=lambda: {
            'limits': {'memory': '256Mi'},
            'requests': {'cpu': '100m'},
        })
        container = SimpleNamespace(resources=resources)
        adjustment = SimpleNamespace(new_memory_limit_mi=None, new_cpu_request_m=250)

        patch = _get_json_patch_op(0, WorkloadKind.Deployment, container, adjustment)

        self.assertEqual(patch['value'], {
            'limits': {'memory': '256Mi'},
            'requests': {'cpu': '250m'},
        })

    def test_applies_only_adjusted_containers(self):
        resources = SimpleNamespace(to_dict=lambda: {
            'limits': {'memory': '256Mi', 'cpu': '500m'},
            'requests': {'memory': '128Mi', 'cpu': '100m'},
        })
        adjusted_container = SimpleNamespace(name='app', resources=resources)
        untouched_container = SimpleNamespace(name='sidecar', resources=resources)
        container_adjustment = SimpleNamespace(
            container_name='app', new_memory_limit_mi=512, new_cpu_request_m=200)
        workload = SimpleNamespace(
            kind=WorkloadKind.Deployment, name='test', namespace='experiments')
        adjustment = SimpleNamespace(
            id=42, workload=workload,
            containers=SimpleNamespace(all=lambda: [container_adjustment]),
            save=mock.Mock())
        patch_func = mock.Mock()
        workload_obj = SimpleNamespace(metadata=SimpleNamespace(resource_version='101'))

        with mock.patch.object(apply_adjustment_module.kube, 'get_workload_obj',
                               return_value=workload_obj), \
                mock.patch.object(apply_adjustment_module.kube, 'get_workload_containers_from_obj',
                                  return_value=[adjusted_container, untouched_container]), \
                mock.patch.dict(apply_adjustment_module.kube.patch_funcs,
                                {WorkloadKind.Deployment: patch_func}), \
                mock.patch.object(apply_adjustment_module, '_verify_adjustment', return_value='102'):
            result = _apply_adjustment(adjustment)

        patch_func.assert_called_once_with('test', 'experiments', [{
            'op': 'test',
            'path': '/metadata/resourceVersion',
            'value': '101',
        }, {
            'op': 'replace',
            'path': '/spec/template/spec/containers/0/resources',
            'value': {
                'limits': {'memory': '512Mi', 'cpu': '500m'},
                'requests': {'memory': '128Mi', 'cpu': '200m'},
            },
        }])
        self.assertEqual(result, {
            'target': 'kubernetes', 'containers': ['app'],
            'resource_version': '102', 'verified': True,
        })
        adjustment.save.assert_called_once_with(update_fields=['resource_version'])

    def test_rejects_an_adjustment_for_a_missing_container(self):
        container = SimpleNamespace(name='app', resources=None)
        container_adjustment = SimpleNamespace(
            container_name='gone', new_memory_limit_mi=512, new_cpu_request_m=200)
        workload = SimpleNamespace(
            kind=WorkloadKind.Deployment, name='test', namespace='experiments')
        adjustment = SimpleNamespace(
            id=42, workload=workload,
            containers=SimpleNamespace(all=lambda: [container_adjustment]),
            save=mock.Mock())
        workload_obj = SimpleNamespace(metadata=SimpleNamespace(resource_version='101'))

        with mock.patch.object(apply_adjustment_module.kube, 'get_workload_obj',
                               return_value=workload_obj), \
                mock.patch.object(apply_adjustment_module.kube, 'get_workload_containers_from_obj',
                                  return_value=[container]):
            with self.assertRaisesRegex(ValueError, 'Containers not found.*gone'):
                _apply_adjustment(adjustment)
