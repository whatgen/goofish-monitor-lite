"""Password-protected LAN settings page for the monitor."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG = Path(os.environ.get("GOOFISH_CONFIG", "/app/private/config.local.json"))
PASSWORD_FILE = Path(os.environ.get("GOOFISH_ADMIN_PASSWORD_FILE", "/app/private/admin_password.hash"))
PAGE = Path(__file__).with_name("admin.html")
SCRIPT = Path(__file__).with_name("admin.js")
LOCK = threading.Lock()
SESSIONS: dict[str, tuple[float, str]] = {}
ATTEMPTS: dict[str, list[float]] = {}


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        scheme, salt, _digest = stored.strip().split("$", 2)
        return scheme == "scrypt" and hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), stored.strip())
    except (ValueError, TypeError):
        return False


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def terms(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("关键词或排除词格式有误")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item.strip()) > 80:
            raise ValueError("单个词不能超过 80 字")
        word = item.strip()
        if word and word not in result:
            result.append(word)
    if len(result) > 30:
        raise ValueError("每项最多 30 个词")
    return result


def validate(products: object) -> list[dict]:
    if not isinstance(products, list) or not 1 <= len(products) <= 30:
        raise ValueError("请保留 1 至 30 条搜索")
    cleaned = []
    for index, item in enumerate(products, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条搜索格式有误")
        name, keyword = item.get("name"), item.get("keyword")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError(f"第 {index} 条：名称请填写 1 至 80 字")
        if not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 80:
            raise ValueError(f"第 {index} 条：搜索关键词请填写 1 至 80 字")
        try:
            prices = [item[key] for key in ("min_price", "target_price", "max_results")]
            if any(isinstance(value, bool) or not isinstance(value, int) for value in prices):
                raise ValueError
            low, high, count = prices
        except (KeyError, ValueError):
            raise ValueError(f"第 {index} 条：价格和结果数必须是整数") from None
        if not 0 <= low <= high <= 1000000:
            raise ValueError(f"第 {index} 条：价格范围无效")
        if not 1 <= count <= 100:
            raise ValueError(f"第 {index} 条：最多检查结果应在 1 至 100 之间")
        cleaned_item = dict(item)
        cleaned_item.update({
            "name": name.strip(), "keyword": keyword.strip(),
            "min_price": low, "target_price": high, "max_results": count,
            "required_any_terms": terms(item.get("required_any_terms", [])),
            "exclude_terms": terms(item.get("exclude_terms", [])),
        })
        cleaned.append(cleaned_item)
    return cleaned


class Handler(BaseHTTPRequestHandler):
    server_version = "GoofishSettings"

    def log_message(self, fmt, *args):
        print("admin: " + fmt % args, flush=True)

    def send_json(self, code: int, value: object, cookie: str | None = None):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100000:
                raise ValueError("请求内容过大或为空")
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError("请求格式有误")
            return value
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("请求格式有误") from exc

    def session(self) -> tuple[str, str] | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            sid = cookie["sid"].value
        except (KeyError, ValueError):
            return None
        with LOCK:
            record = SESSIONS.get(sid)
            if not record or record[0] < time.time():
                SESSIONS.pop(sid, None)
                return None
            return sid, record[1]

    def authorized_write(self) -> tuple[str, str] | None:
        session = self.session()
        if not session or not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session[1]):
            self.send_json(403, {"error": "登录已过期，请刷新页面"})
            return None
        return session

    def do_GET(self):
        if self.path in ("/", "/admin.js"):
            is_script = self.path == "/admin.js"
            body = (SCRIPT if is_script else PAGE).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8" if is_script else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/products":
            session = self.session()
            if not session:
                return self.send_json(401, {"error": "请先登录"})
            try:
                raw = CONFIG.read_bytes()
                self.send_json(200, {"products": json.loads(raw)["products"], "revision": revision(raw), "csrf": session[1]})
            except (OSError, ValueError, KeyError):
                self.send_json(500, {"error": "读取设置失败"})
        else:
            self.send_json(404, {"error": "页面不存在"})

    def do_POST(self):
        if self.path == "/api/login":
            ip = self.client_address[0]
            with LOCK:
                ATTEMPTS[ip] = [t for t in ATTEMPTS.get(ip, []) if t > time.time() - 900]
                if len(ATTEMPTS[ip]) >= 5:
                    return self.send_json(429, {"error": "尝试次数过多，请 15 分钟后再试"})
            try:
                password = self.read_body().get("password")
                stored = PASSWORD_FILE.read_text(encoding="utf-8")
            except (OSError, ValueError):
                return self.send_json(400, {"error": "登录请求无效"})
            if not isinstance(password, str) or not password_matches(password, stored):
                with LOCK:
                    ATTEMPTS[ip].append(time.time())
                return self.send_json(401, {"error": "密码错误"})
            sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            with LOCK:
                ATTEMPTS.pop(ip, None)
                SESSIONS[sid] = (time.time() + 12 * 3600, csrf)
            self.send_json(200, {"csrf": csrf}, f"sid={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")
            return
        session = self.authorized_write()
        if not session:
            return
        if self.path == "/api/logout":
            with LOCK:
                SESSIONS.pop(session[0], None)
            self.send_json(200, {"ok": True}, "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        else:
            self.send_json(404, {"error": "接口不存在"})

    def do_PUT(self):
        if self.path != "/api/products":
            return self.send_json(404, {"error": "接口不存在"})
        if not self.authorized_write():
            return
        try:
            data = self.read_body()
            products = validate(data.get("products"))
            with LOCK:
                raw = CONFIG.read_bytes()
                if data.get("revision") != revision(raw):
                    return self.send_json(409, {"error": "设置已被修改，请刷新后再编辑"})
                config = json.loads(raw)
                config["products"] = products
                encoded = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
                original = CONFIG.stat()
                fd, temp = tempfile.mkstemp(prefix=".config-", dir=CONFIG.parent)
                try:
                    with os.fdopen(fd, "wb") as out:
                        os.fchown(out.fileno(), original.st_uid, original.st_gid)
                        os.fchmod(out.fileno(), 0o600 | (original.st_mode & 0o060))
                        out.write(encoded)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(temp, CONFIG)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
            self.send_json(200, {"products": products, "revision": revision(encoded)})
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})


def serve() -> None:
    if not PASSWORD_FILE.is_file():
        raise SystemExit(f"Admin password hash file missing: {PASSWORD_FILE}")
    server = ThreadingHTTPServer(("0.0.0.0", 9087), Handler)
    server.daemon_threads = True
    print("Settings page listening on port 9087", flush=True)
    server.serve_forever()
