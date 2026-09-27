from django.test import RequestFactory, SimpleTestCase
from rest_framework.request import Request

from utils.django.views import SchemaGenerator


class OpenAPISchemaTests(SimpleTestCase):
    def test_schema_has_unique_operation_ids(self):
        request = Request(RequestFactory().get('/swagger.json'))
        schema = SchemaGenerator().get_schema(request=request)
        operation_ids = [
            operation['operationId']
            for path in schema['paths'].values()
            for operation in path.values()
            if isinstance(operation, dict) and 'operationId' in operation
        ]

        self.assertEqual(schema['openapi'], '3.0.2')
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
