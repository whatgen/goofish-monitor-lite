import http.cookiejar
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import admin_ui


class AdminUITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        admin_ui.CONFIG = Path(self.temp.name) / "config.json"
        admin_ui.PASSWORD_FILE = Path(self.temp.name) / "password.hash"
        admin_ui.PASSWORD_FILE.write_text(admin_ui.password_hash("test-password"))
        admin_ui.CONFIG.write_text(json.dumps({
            "notifications": {"bark_url": "secret-not-for-browser"},
            "products": [{"name": "OWC", "keyword": "OWC 1M2", "min_price": 600,
                          "target_price": 800, "max_results": 20,
                          "required_any_terms": ["OWC"], "exclude_terms": []}],
        }))
        admin_ui.SESSIONS.clear()
        admin_ui.ATTEMPTS.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), admin_ui.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.root = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, method="GET", body=None, csrf=""):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.root + path, data=data, method=method,
                          headers={"Content-Type": "application/json", "X-CSRF-Token": csrf})
        try:
            result = self.opener.open(request)
        except HTTPError as error:
            result = error
        return result.status, json.loads(result.read())

    def test_login_edit_and_preserve_private_notification(self):
        self.assertEqual(self.call("/api/products")[0], 401)
        self.assertEqual(self.call("/api/login", "POST", {"password": "wrong"})[0], 401)
        code, login = self.call("/api/login", "POST", {"password": "test-password"})
        self.assertEqual(code, 200)
        code, current = self.call("/api/products")
        self.assertEqual(code, 200)
        self.assertNotIn("secret-not-for-browser", json.dumps(current))
        items = current["products"]
        items[0]["target_price"] = 750
        self.assertEqual(self.call("/api/products", "PUT", {"products": items, "revision": current["revision"]})[0], 403)
        code, saved = self.call("/api/products", "PUT", {"products": items, "revision": current["revision"]}, login["csrf"])
        self.assertEqual(code, 200)
        self.assertEqual(saved["products"][0]["target_price"], 750)
        self.assertEqual(json.loads(admin_ui.CONFIG.read_text())["notifications"]["bark_url"], "secret-not-for-browser")
        self.assertEqual(self.call("/api/products", "PUT", {"products": items, "revision": current["revision"]}, login["csrf"])[0], 409)

    def test_password_change_requires_current_password_and_revokes_sessions(self):
        _, login = self.call("/api/login", "POST", {"password": "test-password"})
        body = {"current_password": "test-password", "new_password": "new-password-long"}
        self.assertEqual(self.call("/api/password", "POST", body)[0], 403)
        bad = {**body, "current_password": "incorrect"}
        self.assertEqual(self.call("/api/password", "POST", bad, login["csrf"])[0], 400)
        self.assertEqual(self.call("/api/password", "POST", body, login["csrf"])[0], 200)
        self.assertEqual(self.call("/api/products")[0], 401)
        self.assertEqual(self.call("/api/login", "POST", {"password": "test-password"})[0], 401)
        self.assertEqual(self.call("/api/login", "POST", {"password": "new-password-long"})[0], 200)
        self.assertEqual(admin_ui.PASSWORD_FILE.stat().st_mode & 0o777, 0o600)

    def test_status_image_and_login_actions_require_authentication(self):
        for path in ("/api/status", "/api/login-image"):
            self.assertEqual(self.call(path)[0], 401)
        self.assertEqual(self.call("/api/xianyu/login", "POST", {})[0], 403)
        _, login = self.call("/api/login", "POST", {"password": "test-password"})
        self.assertEqual(self.call("/api/xianyu/login", "POST", {})[0], 403)

    def test_filter_edit_preserves_bark_and_rejects_stale_write(self):
        _, login = self.call("/api/login", "POST", {"password": "test-password"})
        _, current = self.call("/api/products")
        body = {"products": current["products"], "revision": current["revision"],
                "filters": {"global_exclude_terms": ["仅售包装盒"], "suspicious_terms": ["置换"]}}
        self.assertEqual(self.call("/api/products", "PUT", body, login["csrf"])[0], 200)
        config = json.loads(admin_ui.CONFIG.read_text())
        self.assertEqual(config["filters"]["global_exclude_terms"], ["仅售包装盒"])
        self.assertEqual(config["notifications"]["bark_url"], "secret-not-for-browser")
        self.assertEqual(self.call("/api/products", "PUT", body, login["csrf"])[0], 409)

    def test_invalid_price_is_rejected(self):
        code, login = self.call("/api/login", "POST", {"password": "test-password"})
        self.assertEqual(code, 200)
        _, current = self.call("/api/products")
        items = current["products"]
        items[0]["min_price"] = 900
        code, _ = self.call("/api/products", "PUT", {"products": items, "revision": current["revision"]}, login["csrf"])
        self.assertEqual(code, 400)
        self.assertEqual(json.loads(admin_ui.CONFIG.read_text())["products"][0]["min_price"], 600)


if __name__ == "__main__":
    unittest.main()
