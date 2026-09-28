"""One browser owner; the web server can request login without restarting it."""
from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
from playwright.async_api import async_playwright

from goofish_monitor import GoofishMonitor, LOGIN_SELECTORS, GOOFISH_HOME


def stamp():
    return datetime.now().isoformat(timespec="seconds")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
    os.replace(temp, path)


class MonitorService:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.lock = threading.RLock()
        self.command = None
        self.image = None
        self.state = {"phase": "starting", "message": "正在启动监控", "keyword": "",
                      "last_success": None, "last_count": 0, "next_run": None,
                      "login_expires": None, "notification": "尚未发送登录提醒"}
        self.incident_path = self.config_path.parent / "login_incident.json"
        try:
            self.incident = json.loads(self.incident_path.read_text())
        except (OSError, ValueError):
            self.incident = {}
        self.last_notify_attempt = 0

    def update(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)
            self.state["updated_at"] = stamp()

    def snapshot(self):
        with self.lock:
            return {**self.state, "has_login_image": self.image is not None,
                    "login_pending": self.command == "login"}

    def request(self, command):
        with self.lock:
            if command == "login" and (self.command == "login" or self.state["phase"] == "login_waiting"):
                return
            self.command = command

    def take_command(self):
        with self.lock:
            command, self.command = self.command, None
            return command

    def set_image(self, image):
        with self.lock:
            self.image = image

    async def notify_login(self, config):
        if self.incident.get("sent") or time.time() - self.last_notify_attempt < 300:
            return
        url = config.get("notifications", {}).get("bark_url")
        if not url:
            self.update(notification="尚未配置 Bark，无法发送登录提醒")
            return
        self.last_notify_attempt = time.time()
        if not self.incident.get("since"):
            self.incident = {"since": stamp(), "sent": False}
        try:
            await asyncio.to_thread(self.send_login_notification, url)
            self.incident["sent"] = True
            self.incident["sent_at"] = stamp()
            atomic_json(self.incident_path, self.incident)
            self.update(notification="已通过 Bark 提醒重新登录")
        except Exception:
            self.update(notification="Bark 提醒发送失败，5 分钟后重试")

    @staticmethod
    def send_login_notification(url):
        result = requests.post(url, json={
            "title": "闲鱼登录已失效，监控已暂停",
            "body": "请打开闲鱼监控管理页，点击「扫码登录」。登录验证成功后会自动继续监控。",
            "group": "闲鱼监控状态", "level": "timeSensitive",
        }, timeout=12)
        result.raise_for_status()
        if result.json().get("code") != 200:
            raise RuntimeError("Bark rejected notification")

    async def login_visible(self, page):
        if any(x in page.url for x in ("passport.goofish.com", "login.taobao.com")):
            return True
        for selector in LOGIN_SELECTORS:
            if await page.locator(selector).first.is_visible():
                return True
        return False

    async def login_image(self, page):
        # Capture only the official QR panel where possible (no SMS form/phone data).
        for frame in page.frames:
            if "passport.goofish.com" in frame.url or "login.taobao.com" in frame.url:
                qr = frame.locator(".qrcode-login").first
                if await qr.is_visible():
                    return await qr.screenshot(timeout=5000)
        dialog = page.locator("iframe#alibaba-login-box, iframe[src*='passport.goofish.com']").first
        if await dialog.is_visible():
            return await dialog.screenshot(timeout=5000)
        return None

    async def verified_search(self, monitor, page):
        """Cookies alone are not evidence that the server accepts this login."""
        keyword = monitor.products[0]["keyword"]
        response = await monitor.goto_and_capture_search(page, GOOFISH_HOME + "search?" + urlencode({"q": keyword}))
        await monitor.assert_page_usable(page)
        if not response:
            return False
        data = await response.json()
        return isinstance(data.get("data", {}).get("resultList"), list) and any(
            str(x).startswith("SUCCESS") for x in data.get("ret", []))

    async def login_flow(self, monitor, context, page):
        self.set_image(None)
        self.update(phase="login_waiting", message="正在打开闲鱼官方登录页面…", next_run=None,
                    login_expires=int(time.time() + 300))
        try:
            await page.goto(GOOFISH_HOME, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            for label in ("登录", "登录/注册", "亲，请登录", "立即登录"):
                button = page.get_by_text(label, exact=True).first
                if await button.is_visible():
                    await button.click(timeout=5000)
                    break
            if not await self.login_visible(page):
                # Search also triggers the site's own login dialog when necessary.
                await page.goto(GOOFISH_HOME + "search?q=OWC", wait_until="domcontentloaded", timeout=45000)
            deadline = time.time() + 300
            while time.time() < deadline:
                if self.take_command() == "cancel":
                    self.update(phase="login_required", message="已取消扫码，监控保持暂停")
                    return False
                # Only operate the official login mode switch, never CAPTCHA controls.
                for frame in page.frames:
                    if "login" not in frame.url and "passport" not in frame.url:
                        continue
                    for selector in (".icon-qrcode", ".login-switch .icon-qrcode", "[title='扫码登录']"):
                        switch = frame.locator(selector).first
                        if await switch.is_visible():
                            await switch.click(timeout=2000)
                            break
                visible = await self.login_visible(page)
                if visible:
                    self.set_image(await self.login_image(page))
                    self.update(message="用闲鱼 App 扫描页面中的二维码，并在手机上确认。二维码过期时请重新生成。")
                else:
                    self.update(message="正在验证登录和搜索权限…")
                    if await self.verified_search(monitor, page):
                        state = await context.storage_state()
                        atomic_json(monitor.storage_state, state)
                        self.incident = {}
                        atomic_json(self.incident_path, {})
                        self.update(phase="ready", message="登录验证成功，正在恢复监控", login_expires=None,
                                    notification="登录已恢复")
                        return True
                    self.update(message="尚未通过搜索验证；若出现安全验证，请在官方闲鱼页面完成后重试。")
                    self.set_image(None)
                await asyncio.sleep(3)
            self.update(phase="login_required", message="本次扫码已超时，请重新生成二维码")
            return False
        except Exception:
            self.update(phase="login_required", message="无法完成网页登录，请重新生成二维码；如遇安全验证，请先在闲鱼 App 完成验证")
            return False
        finally:
            self.set_image(None)
            self.update(login_expires=None)

    async def run(self):
        # The management server survives browser errors. Only this worker owns Chromium.
        while True:
            try:
                await self.run_browser()
            except Exception as exc:
                print(f"Monitor worker failed: {type(exc).__name__}", flush=True)
                self.set_image(None)
                self.update(phase="error", message="浏览器暂时不可用，60 秒后重试；管理页仍可使用", next_run=None)
                await asyncio.sleep(60)

    async def run_browser(self):
        monitor = GoofishMonitor(self.config_path)
        monitor.service = self
        async with async_playwright() as p:
            context = await monitor.new_persistent_context(p)
            page = await context.new_page()
            paused = bool(self.incident.get("since"))
            due = 0
            try:
                while True:
                    command = self.take_command()
                    if command == "login":
                        paused = not await self.login_flow(monitor, context, page)
                        due = 0
                    if paused:
                        if self.state["phase"] != "login_required":
                            self.update(phase="login_required", message="闲鱼需要重新登录，监控已暂停", next_run=None)
                        await self.notify_login(monitor.config)
                    elif time.time() >= due:
                        self.update(phase="searching", message="正在搜索闲鱼商品", next_run=None)
                        try:
                            candidates = await monitor.run_round(page)
                            await monitor.notify_many(candidates)
                            atomic_json(monitor.storage_state, await context.storage_state())
                            runtime = monitor.config.get("runtime", {})
                            due = time.time() + max(30, int(runtime.get("interval_seconds", 90))) + random.randint(0, max(0, int(runtime.get("jitter_seconds", 30))))
                            self.update(phase="waiting", message="监控正常，等待下一轮搜索", last_success=stamp(),
                                        last_count=len(candidates), next_run=int(due), keyword="")
                        except RuntimeError as exc:
                            if "Login required" in str(exc) or "Risk control" in str(exc):
                                paused = True
                                self.update(phase="login_required", message="闲鱼要求登录或安全验证，监控已暂停", next_run=None)
                                await self.notify_login(monitor.config)
                            else:
                                raise
                        except Exception as exc:
                            due = time.time() + 120
                            self.update(phase="error", message="本轮搜索或通知失败，2 分钟后重试", next_run=int(due))
                            print(f"Round error: {type(exc).__name__}", flush=True)
                    await asyncio.sleep(1)
            finally:
                await context.close()


SERVICE = MonitorService(os.environ.get("GOOFISH_CONFIG", "/app/private/config.local.json"))
