import re

cgroup_re = re.compile(r'/pod([\w\-]+)/(\w+)$')
systemd_cgroup_re = re.compile(
    r'/kubepods(?:-(?:burstable|besteffort))?-pod([\w\-]+)\.slice/'
    r'cri-containerd-([a-fA-F0-9]+)\.scope$'
)


def parse_cgroup(cgroup):
    """
    :param cgroup: str
    :return: (pod_uid, container_runtime_id)
    """
    match = cgroup_re.search(cgroup)
    if not match:
        match = systemd_cgroup_re.search(cgroup)
    if not match:
        return None, None
    return match.group(1).replace('_', '-'), match.group(2)
