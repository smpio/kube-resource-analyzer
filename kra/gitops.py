import base64
import copy
import re

import requests
import yaml
from django.conf import settings
from kubernetes import client as kube_client

from kra.models import WorkloadKind


TRACKING_ID = 'argocd.argoproj.io/tracking-id'
ARGOCD_GROUP = 'argoproj.io'
ARGOCD_VERSION = 'v1alpha1'
ARGOCD_PLURAL = 'applications'
GITHUB_API_URL = 'https://api.github.com'
_GITHUB_REPO_RE = re.compile(r'^(?:git@github\.com:|https://github\.com/)([^/]+)/([^/]+?)(?:\.git)?$')
_BRANCH_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]*$')


class GitOpsError(Exception):
    pass


def apply_adjustment(adj, workload_obj):
    """Commit an Argo CD-managed adjustment, or return None for direct Kubernetes patching."""
    tracking_id = (getattr(workload_obj.metadata, 'annotations', None) or {}).get(TRACKING_ID)
    if not tracking_id:
        return None

    application_name = _application_name(tracking_id, adj.workload)
    application = kube_client.CustomObjectsApi().get_namespaced_custom_object(
        ARGOCD_GROUP, ARGOCD_VERSION, settings.ARGOCD_NAMESPACE, ARGOCD_PLURAL, application_name)
    source = _get_source(application)
    repository = _parse_github_repo(source['repoURL'])
    branch = _get_branch(source, repository)
    client = GitHubClient(settings.GITHUB_TOKEN)

    manifest_matches = 0
    matching_files = []
    for path in client.list_files(repository, branch, source['path']):
        content = client.get_file(repository, path, branch)
        found, updated = _update_manifest_resources(content, adj.workload, adj.containers.all())
        manifest_matches += found
        if updated is not None:
            matching_files.append((path, content, updated))

    if manifest_matches == 0:
        raise GitOpsError(
            f'No manifest for {adj.workload} found in Argo CD application {application_name}')
    if manifest_matches != 1:
        raise GitOpsError(
            f'Argo CD application {application_name} has {manifest_matches} manifests for '
            f'{adj.workload}; expected exactly one')
    if not matching_files:
        # The object is Argo-managed but its container has no resources in Git.
        # This is the deliberate direct-patch exception from the GitOps policy.
        return None

    path, original, updated = matching_files[0]
    if updated == original:
        raise GitOpsError(f'Git manifest {path} already contains the requested resources')

    commit_message = f'kra: adjust {adj.workload.namespace}/{adj.workload.name} resources (#{adj.id})'
    mode = settings.GITOPS_MODE
    if mode == 'direct':
        commit = client.commit_file(repository, branch, path, updated, commit_message)
        return _result(application_name, source, path, branch, commit, mode)
    if mode == 'pull_request':
        head = f'kra/adjustment-{adj.id}'
        commit = client.commit_file(repository, head, path, updated, commit_message, base_branch=branch)
        pull_request = client.create_pull_request(
            repository, title=commit_message, head=head, base=branch,
            body=_pull_request_body(adj, application_name, source, path))
        return _result(application_name, source, path, branch, commit, mode, pull_request)
    raise GitOpsError(f'Unsupported GITOPS_MODE {mode!r}; expected "direct" or "pull_request"')


def _application_name(tracking_id, workload):
    try:
        application_name, group_kind, namespace_name = tracking_id.split(':')
        group, kind = group_kind.split('/')
        namespace, name = namespace_name.split('/')
    except ValueError as err:
        raise GitOpsError(f'Malformed Argo CD tracking-id on {workload}: {tracking_id!r}') from err
    expected_group = 'batch' if workload.kind in (WorkloadKind.CronJob, WorkloadKind.Job) else 'apps'
    if (group, kind, namespace, name) != (expected_group, workload.kind.name, workload.namespace, workload.name):
        raise GitOpsError(f'Argo CD tracking-id does not identify {workload}: {tracking_id!r}')
    return application_name


def _get_source(application):
    spec = application.get('spec') or {}
    if spec.get('sources'):
        raise GitOpsError('Argo CD multi-source Applications are not supported')
    source = spec.get('source') or {}
    if not source.get('repoURL') or source.get('path') is None:
        raise GitOpsError('Argo CD Application must define spec.source.repoURL and spec.source.path')
    if source.get('chart') or source.get('helm') or source.get('kustomize'):
        raise GitOpsError('Only plain YAML Argo CD sources are supported')
    return source


def _parse_github_repo(repo_url):
    match = _GITHUB_REPO_RE.fullmatch(repo_url)
    if not match:
        raise GitOpsError(f'Only GitHub repositories are supported, got {repo_url!r}')
    return match.group(1), match.group(2)


def _get_branch(source, repository):
    revision = source.get('targetRevision') or 'HEAD'
    if revision == 'HEAD':
        return GitHubClient(settings.GITHUB_TOKEN).default_branch(repository)
    if revision.startswith('refs/heads/'):
        revision = revision.removeprefix('refs/heads/')
    if not _BRANCH_RE.fullmatch(revision) or revision.startswith('refs/'):
        raise GitOpsError(f'Argo CD targetRevision must be a branch, got {revision!r}')
    return revision


def update_manifest_resources(content, workload, container_adjustments):
    """Return updated YAML only if this file declares the requested container resources."""
    _, updated = _update_manifest_resources(content, workload, container_adjustments)
    return updated


def _update_manifest_resources(content, workload, container_adjustments):
    """Return (contains_workload, updated_content)."""
    try:
        documents = list(yaml.safe_load_all(content))
    except yaml.YAMLError as err:
        raise GitOpsError(f'Cannot parse YAML manifest: {err}') from err
    matching = [doc for doc in documents if _is_workload_document(doc, workload)]
    if not matching:
        return False, None
    if len(matching) != 1:
        raise GitOpsError(f'Manifest contains {len(matching)} declarations for {workload}')

    document = matching[0]
    containers = _document_containers(document, workload.kind)
    by_name = {container.get('name'): container for container in containers}
    adjustments = {adjustment.container_name: adjustment for adjustment in container_adjustments}
    missing = sorted(set(adjustments) - set(by_name))
    if missing:
        raise GitOpsError(f'Manifest for {workload} has no containers: {", ".join(missing)}')
    has_resources = [by_name[name].get('resources') is not None for name in adjustments]
    if not any(has_resources):
        return True, None
    if not all(has_resources):
        raise GitOpsError(f'Manifest for {workload} has resources only on part of adjusted containers')

    for name, adjustment in adjustments.items():
        resources = by_name[name]['resources']
        if not isinstance(resources, dict):
            raise GitOpsError(f'Manifest resources for {workload}/{name} is not a mapping')
        resources = by_name[name]['resources'] = copy.deepcopy(resources)
        if adjustment.new_memory_limit_mi is not None:
            resources.setdefault('limits', {})['memory'] = f'{adjustment.new_memory_limit_mi}Mi'
        if adjustment.new_cpu_request_m is not None:
            resources.setdefault('requests', {})['cpu'] = f'{adjustment.new_cpu_request_m}m'
    return True, yaml.safe_dump_all(documents, allow_unicode=True, sort_keys=False)


def _is_workload_document(document, workload):
    if not isinstance(document, dict):
        return False
    metadata = document.get('metadata') or {}
    return (document.get('kind') == workload.kind.name and
            metadata.get('name') == workload.name and
            metadata.get('namespace', workload.namespace) == workload.namespace)


def _document_containers(document, kind):
    path = ['spec', 'template', 'spec', 'containers']
    if kind == WorkloadKind.CronJob:
        path = ['spec', 'jobTemplate', 'spec', 'template', 'spec', 'containers']
    current = document
    try:
        for key in path:
            current = current[key]
    except (KeyError, TypeError) as err:
        raise GitOpsError(f'Manifest for {kind.name} has no pod containers') from err
    if not isinstance(current, list):
        raise GitOpsError(f'Manifest containers for {kind.name} is not a list')
    return current


def _result(application_name, source, path, branch, commit, mode, pull_request=None):
    result = {
        'target': 'git', 'mode': mode, 'application': application_name,
        'repo_url': source['repoURL'], 'path': path, 'branch': branch,
        'commit': commit['sha'],
        'sync_status': 'awaiting_argo_sync' if mode == 'direct' else 'awaiting_pull_request_merge',
    }
    if pull_request:
        result.update(pull_request_url=pull_request['html_url'], pull_request=pull_request['number'])
    return result


def _pull_request_body(adj, application_name, source, path):
    return (f'Created by KRA adjustment #{adj.id}.\n\nArgo CD application: `{application_name}`\n'
            f'Source: `{source["repoURL"]}:{path}`\n'
            f'Workload: `{adj.workload.namespace}/{adj.workload.name}`')


class GitHubClient:
    def __init__(self, token):
        if not token:
            raise GitOpsError('GITHUB_TOKEN is not configured for GitOps adjustments')
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {token}',
            'X-GitHub-Api-Version': '2026-03-10',
        })

    def _request(self, method, path, **kwargs):
        response = self.session.request(method, f'{GITHUB_API_URL}{path}', timeout=30, **kwargs)
        if not response.ok:
            raise GitOpsError(f'GitHub API {method} {path} failed ({response.status_code}): {response.text[:500]}')
        return response.json()

    def default_branch(self, repository):
        return self._request('GET', f'/repos/{repository[0]}/{repository[1]}')['default_branch']

    def list_files(self, repository, branch, source_path):
        commit = self._request('GET', f'/repos/{repository[0]}/{repository[1]}/commits/{branch}')
        tree = self._request('GET', f'/repos/{repository[0]}/{repository[1]}/git/trees/{commit["commit"]["tree"]["sha"]}',
                             params={'recursive': '1'})
        if tree.get('truncated'):
            raise GitOpsError('GitHub repository tree is truncated; cannot safely locate manifest')
        prefix = source_path.strip('/')
        if prefix:
            prefix += '/'
        return [entry['path'] for entry in tree['tree'] if entry['type'] == 'blob' and
                entry['path'].startswith(prefix) and entry['path'].lower().endswith(('.yaml', '.yml'))]

    def get_file(self, repository, path, branch):
        data = self._request('GET', f'/repos/{repository[0]}/{repository[1]}/contents/{path}', params={'ref': branch})
        return base64.b64decode(data['content']).decode('utf-8')

    def commit_file(self, repository, branch, path, content, message, base_branch=None):
        if base_branch:
            self._request('POST', f'/repos/{repository[0]}/{repository[1]}/git/refs',
                          json={'ref': f'refs/heads/{branch}', 'sha': self._ref_sha(repository, base_branch)})
        base_sha = self._ref_sha(repository, branch)
        base_commit = self._request('GET', f'/repos/{repository[0]}/{repository[1]}/git/commits/{base_sha}')
        blob = self._request('POST', f'/repos/{repository[0]}/{repository[1]}/git/blobs',
                             json={'content': content, 'encoding': 'utf-8'})
        tree = self._request('POST', f'/repos/{repository[0]}/{repository[1]}/git/trees', json={
            'base_tree': base_commit['tree']['sha'],
            'tree': [{'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']}],
        })
        commit = self._request('POST', f'/repos/{repository[0]}/{repository[1]}/git/commits',
                               json={'message': message, 'tree': tree['sha'], 'parents': [base_sha]})
        self._request('PATCH', f'/repos/{repository[0]}/{repository[1]}/git/refs/heads/{branch}',
                      json={'sha': commit['sha'], 'force': False})
        return commit

    def _ref_sha(self, repository, branch):
        return self._request('GET', f'/repos/{repository[0]}/{repository[1]}/git/ref/heads/{branch}')['object']['sha']

    def create_pull_request(self, repository, **data):
        return self._request('POST', f'/repos/{repository[0]}/{repository[1]}/pulls', json=data)
