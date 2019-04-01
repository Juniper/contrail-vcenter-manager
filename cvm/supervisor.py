import gevent
import logging

from cvm.constants import SUPERVISOR_TIMEOUT, SUPERVISOR_INTERVAL

logger = logging.getLogger(__name__)


class Supervisor(object):
    def __init__(self, event_listener, esxi_api_client):
        self._event_listener = event_listener
        self._esxi_api_client = esxi_api_client
        self._greenlet = None

    def supervise(self):
        self._greenlet = gevent.spawn(self._event_listener.listen)
        while True:
            try:
                timer = gevent.Timeout(SUPERVISOR_TIMEOUT)
                timer.start()
                logger.info('Successful keep alive check: current time: %s', self._esxi_api_client.current_time())
                timer.close()
                gevent.sleep(SUPERVISOR_INTERVAL)
            except Exception, exc:
                logger.info('Failed keep alive check with exception: %s', exc, exc_info=True)
                logger.error('Renewing connection to ESXi...')
                self._renew_esxi_connection_retry()
                logger.error('Renewed connection to ESXi')
                logger.error('Respawing event listening greenlet')
                self._greenlet.kill(block=False)
                self._greenlet = gevent.spawn(self._event_listener.listen)
                logger.error('Respawned event listening greenlet')

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
