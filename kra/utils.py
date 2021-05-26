import re

cgroup_re = re.compile(r'/pod([\w\-]+)/(\w+)$')


def parse_cgroup(cgroup):
    """
    :param cgroup: str
    :return: (pod_uid, container_runtime_id)
    """
    match = cgroup_re.search(cgroup)
    if not match:
        return None, None
    return match.group(1), match.group(2)
