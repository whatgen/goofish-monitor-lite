import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor_service import MonitorService


class ServiceTest(unittest.TestCase):
    def test_incident_alert_deduplicates_across_restarts_and_failure_retries(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'config.json'
            config = {'notifications': {'bark_url': 'https://example.invalid/secret'}}
            service = MonitorService(path)
            with patch.object(service, 'send_login_notification', side_effect=RuntimeError('offline')):
                asyncio.run(service.notify_login(config))
            self.assertFalse(service.incident.get('sent', False))
            service.last_notify_attempt = 0
            with patch.object(service, 'send_login_notification') as notify:
                asyncio.run(service.notify_login(config))
                asyncio.run(service.notify_login(config))
                self.assertEqual(notify.call_count, 1)
            restarted = MonitorService(path)
            with patch.object(restarted, 'send_login_notification') as notify:
                asyncio.run(restarted.notify_login(config))
                notify.assert_not_called()
            self.assertNotIn('secret', json.dumps(service.snapshot()))

    def test_duplicate_login_commands_and_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            service = MonitorService(Path(root) / 'config.json')
            service.request('login')
            service.request('login')
            self.assertEqual(service.take_command(), 'login')
            self.assertIsNone(service.take_command())
            service.update(phase='login_waiting')
            service.request('login')
            self.assertIsNone(service.take_command())
            service.request('cancel')
            self.assertEqual(service.take_command(), 'cancel')

class SearchVerificationTest(unittest.IsolatedAsyncioTestCase):
    async def test_stale_cookie_or_failed_api_is_not_login_success(self):
        from unittest.mock import AsyncMock, Mock
        with tempfile.TemporaryDirectory() as root:
            service = MonitorService(Path(root) / 'config.json')
            monitor = Mock(products=[{'keyword': 'OWC'}])
            monitor.assert_page_usable = AsyncMock()
            response = Mock()
            response.json = AsyncMock(return_value={'ret': ['FAIL_SYS_SESSION_EXPIRED'], 'data': {}})
            monitor.goto_and_capture_search = AsyncMock(return_value=response)
            self.assertFalse(await service.verified_search(monitor, Mock()))
            response.json = AsyncMock(return_value={'ret': ['SUCCESS::调用成功'], 'data': {'resultList': []}})
            self.assertTrue(await service.verified_search(monitor, Mock()))
