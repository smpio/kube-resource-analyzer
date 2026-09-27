from types import SimpleNamespace
from unittest import TestCase, mock

from kra.collectors.metrics import CollectorThread


class ScrapNodeTests(TestCase):
    def test_requests_cadvisor_metrics_using_the_current_kubernetes_client_api(self):
        api_client = mock.Mock()
        api_client.call_api.return_value = ('metrics payload', 200, {})
        node = SimpleNamespace(metadata=SimpleNamespace(name='worker-1'))

        with mock.patch('kra.collectors.metrics.kubernetes.client.ApiClient',
                        return_value=api_client):
            result = CollectorThread(mock.Mock()).scrap_node(node)

        self.assertEqual(result, 'metrics payload')
        api_client.call_api.assert_called_once_with(
            '/api/v1/nodes/{node}/proxy/metrics/cadvisor', 'GET',
            path_params={'node': 'worker-1'},
            auth_settings=['BearerToken'],
            response_types_map={200: 'str'},
        )
