import enum
import random
import logging

import kubernetes
from urllib3.exceptions import ReadTimeoutError

log = logging.getLogger(__name__)


class EventType(enum.Enum):
    ADDED = 'ADDED'
    MODIFIED = 'MODIFIED'
    DELETED = 'DELETED'
    BOOKMARK = 'BOOKMARK'
    ERROR = 'ERROR'


# See this for alternative solution:
# https://github.com/kubernetes/client-go/blob/a3f022a93c931347796775a33996b14fc3c61ab3/tools/cache/reflector.go
class KubeWatcher:
    min_watch_timeout = 5 * 60

    def __init__(self, list_func):
        self.list_func = list_func
        self.resource_version = None
        self.db = {}

    def run(self):
        while True:
            try:
                obj_list = self.list_func()

                if not self.resource_version:
                    yield from self.handle_initial(obj_list)
                else:
                    yield from self.handle_restart(obj_list)

                self.resource_version = obj_list.metadata.resource_version

                while True:
                    for event in self._safe_stream():
                        try:
                            event_type = EventType(event['type'])
                        except ValueError:
                            raise Exception('Unknown event type: %s', event['type'])
                        obj = event['object']
                        self.handle_event(event_type, obj)
                        self.resource_version = obj.metadata.resource_version
                        yield event_type, obj
            except RestartWatchException:
                pass

    def _safe_stream(self):
        timeout = random.randint(self.min_watch_timeout, self.min_watch_timeout * 2)

        log.info('Watching events since version %s, timeout %d seconds', self.resource_version, timeout)

        kwargs = {
            'timeout_seconds': timeout,
            '_request_timeout': timeout + 10,
        }
        if self.resource_version:
            kwargs['resource_version'] = self.resource_version

        w = kubernetes.watch.Watch()
        gen = w.stream(self.list_func, **kwargs)
        while True:
            try:
                val = next(gen)
            except StopIteration:
                log.info('Watch connection closed')
                break
            except ReadTimeoutError:
                log.info('Watch timeout')
                break
            except ValueError:
                # workaround for the bug https://github.com/kubernetes-client/python-base/issues/57
                log.info('The resourceVersion for the provided watch is too old. Restarting watch')
                raise RestartWatchException()
            yield val

    def handle_event(self, event_type, obj):
        if event_type in (EventType.ADDED, EventType.MODIFIED):
            self.db[obj.metadata.uid] = obj
        elif event_type == EventType.DELETED:
            del self.db[obj.metadata.uid]
        elif event_type == EventType.ERROR:
            raise Exception(obj)
        else:
            raise Exception('Unsupported event type: %s', event_type)

    def handle_initial(self, obj_list):
        for obj in self._depaginate(obj_list):
            self.db[obj.metadata.uid] = obj
            yield EventType.ADDED, obj

    def handle_restart(self, obj_list):
        alive_uids = set()

        for obj in self._depaginate(obj_list):
            alive_uids.add(obj.metadata.uid)
            db_obj = self.db[obj.metadata.uid]
            self.db[obj.metadata.uid] = obj
            if db_obj is None:
                yield EventType.ADDED, obj
            elif db_obj.metadata.resource_version != obj.metadata.resource_version:
                yield EventType.MODIFIED, obj

        for uid in self.db.keys():
            if uid not in alive_uids:
                obj = self.db[uid]
                del self.db[uid]
                yield EventType.DELETED, obj

    def _depaginate(self, obj_list):
        # TODO:
        return obj_list.items


class RestartWatchException(Exception):
    pass


def watch(list_func):
    return KubeWatcher(list_func).run()
