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
