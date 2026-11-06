# OOM collection and notifications

The OOM collector consumes NodeOOM Events from
[kube-oom-monitor](https://github.com/smpio/kube-oom-monitor/blob/master/docs/event-format.md).
It parses `pid`, `proc`, `taskcg`, and `oomcg`, resolves the victim container, stores
an OOMEvent, and queues a `ContainerOOM` Warning Event for the Pod through Celery.

## Identity and cgroup paths

`kra.utils.parse_cgroup` supports cgroupfs paths and systemd slice/scope paths,
including `cri-containerd-<id>.scope` and Pod UIDs encoded with underscores.
Resolution uses both Pod UID and container runtime ID. Cgroup v2 alone does not
imply a specific path layout. Host/root cgroups may not identify a Kubernetes Pod;
inspect the raw NodeOOM rather than inventing a container match.

## Serialization and criticality

Only JSON-compatible reference fields cross the Celery boundary. Kubernetes SDK
models may contain in-cluster token-refresh callbacks that cannot be pickled.
The worker constructs V1ObjectReference and CoreV1Event. A stored OOMEvent does not
prove that the Celery task was accepted or that Kubernetes received ContainerOOM.
Notification timestamps are normalized to timezone-aware RFC3339 values, including
objects loaded from a database configured with USE_TZ=False.

An OOM is critical when kubelet reports OOMKilled for the same Pod UID and container
runtime ID within ten seconds of its timestamp. Either delivery order is supported:
the Pod collector records oom_killed_at and may promote an existing event later,
producing an additional CRITICAL notification. A later unrelated restart must not
reclassify an older child-process OOM. Missing kubelet history cannot be recovered
reliably from restart count alone. See the [README](../README.md) for required migrations.

Pod revision labels must fit Pod.spec_hash; truncating or rejecting long StatefulSet
controller-revision-hash values can silently reduce coverage. Standalone Pods still
receive OOM records and notifications, but do not generate workload recommendations.

## Delivery and troubleshooting

The watcher skips the initial Event list. The collector retries a missing Container
lookup, but does not provide durable replay of every failed handler or historical
Event. Check each stage separately: NodeOOM, Pod/container registration, OOMEvent,
Celery task, then ContainerOOM. Empty logs from a replacement Pod do not establish
that an earlier notification error was fixed.

Deploy a worker that accepts JSON reference dictionaries before collectors that
send them. The notification worker also accepts references queued by the previous
implementation during that transition. Keep schema migrations consistent with the
collector version.

## Verification

Use the [development environment](../DEVELOPMENT.md) and run:

```sh
python manage.py test kra.tests
```

Parser fixtures should cover cgroupfs and systemd layouts, UID normalization, and
host/global paths. Notification tests need the actual Kombu round trip and Event
payload, not just serialization of an arbitrary dict. Criticality tests must cover
both status/event delivery orders, child-process OOM, and delayed unrelated restarts.

For node upgrades, verify the full chain on an isolated bounded workload using the
actual node image and cgroup layout. Observe child-process and main-process cases
separately. Passing tests on one cgroupfs node does not validate systemd/global OOM
or another Kubernetes/node version.
