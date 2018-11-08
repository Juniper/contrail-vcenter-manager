import gevent
import logging

from cvm.constants import SUPERVISOR_TIMEOUT

logger = logging.getLogger(__name__)


class Supervisor(object):
    def __init__(self, event_listener, esxi_api_client):
        self._event_listener = event_listener
        self._esxi_api_client = esxi_api_client
        self._to_supervisor = gevent.queue.Queue()
        self._greenlet = None

    def supervise(self):
        self._greenlet = gevent.spawn(self._event_listener.listen, self._to_supervisor)
        while True:
            try:
                self._to_supervisor.get()
                logger.info('GOT MESSAGE FROM LISTENER GREENLET: BEFORE')
                self._to_supervisor.get(timeout=SUPERVISOR_TIMEOUT)
                logger.info('GOT MESSAGE FROM LISTENER GREENLET: AFTER')
            except Exception:
                logger.error('Events listener greenlets hanged on WaitForUpdatesEX calls')
                logger.info('Renewing connection to ESXi...')
                self._renew_esxi_connection_retry()
                logger.info('Renewed connection to ESXi')
                logger.info('Respawing event handling greenlet')
                self._greenlet.kill(block=False)
                self._greenlet = gevent.spawn(self._event_listener.listen, self._to_supervisor)
                logger.info('Respawned event handling greenlet')

    def _renew_esxi_connection_retry(self):
        i = 1
        while True:
            try:
                self._esxi_api_client.renew_connection()
                break
            except Exception:
                logger.error('Error during renewing connection to ESXi')
                gevent.sleep(2 * i)
                logger.error('Retrying to renew connection to ESXi...')
            i += 1
