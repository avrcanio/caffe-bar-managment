import json
import os
from pathlib import Path
from urllib.parse import urljoin

import requests
from requests.utils import cookiejar_from_dict, dict_from_cookiejar


class RemarisConnector:
    def __init__(self, base_url=None, username=None, password=None, session=None):
        self.base_url = (base_url or os.getenv("REMARIS_BASE_URL") or "https://mozart.remaris.hr").rstrip("/")
        self.username = username or os.getenv("REMARIS_USERNAME")
        self.password = password or os.getenv("REMARIS_PASSWORD")
        self.session = session or requests.Session()
        self.cookie_path = Path(
            os.getenv("REMARIS_COOKIE_PATH", "/srv/mozzart/.remaris_cookies.json")
        )
        self.cookie_readonly = False
        self.raw_cookie_header = None
        self._load_cookies()

    def login(self, skip_if_cookie=False):
        if skip_if_cookie and self._has_auth_cookies():
            self._prime_app_context()
            return None
        if self.cookie_readonly and self._has_auth_cookies() and not (
            self.username and self.password
        ):
            self._prime_app_context()
            return None
        if not self.username or not self.password:
            raise ValueError("Missing REMARIS_USERNAME or REMARIS_PASSWORD")

        # Ensure we start from a clean session when using credentials.
        self.session.cookies.clear()
        self.raw_cookie_header = None
        self.cookie_readonly = False

        # Prime session cookies.
        self.session.get(urljoin(self.base_url + "/", "Account/Logon"))

        response = self.session.post(
            urljoin(self.base_url + "/", "Account/Logon?ReturnUrl=%2f"),
            data={
                "UserName": self.username,
                "Password": self.password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
        )
        self.raw_cookie_header = None
        self.cookie_readonly = False
        self._prime_app_context()
        self._save_cookies()
        return response

    def post_json(self, path, payload, referer_path):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "ajax-request": "AJAX-REQUEST",
            "Origin": self.base_url,
            "Referer": urljoin(self.base_url + "/", referer_path.lstrip("/")),
        }
        if self.raw_cookie_header:
            headers["Cookie"] = self.raw_cookie_header
        response = self.session.post(
            urljoin(self.base_url + "/", path.lstrip("/")),
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        self._save_cookies()
        return response.json()

    def get_html(self, path, referer_path=None):
        headers = {}
        if referer_path:
            headers["Referer"] = urljoin(self.base_url + "/", referer_path.lstrip("/"))
        if self.raw_cookie_header:
            headers["Cookie"] = self.raw_cookie_header
        response = self.session.get(
            urljoin(self.base_url + "/", path.lstrip("/")),
            headers=headers,
        )
        response.raise_for_status()
        self._save_cookies()
        return response.text

    def _load_cookies(self):
        cookie_str = self._load_cookie_from_db()
        if cookie_str:
            data = self._cookie_dict_from_string(cookie_str)
            if data:
                self.session.cookies.update(cookiejar_from_dict(data))
                if not (self.username and self.password):
                    self.raw_cookie_header = cookie_str
                    if data.get("AppContext"):
                        self.cookie_readonly = True
            return
        if not self.cookie_path.exists():
            return
        try:
            data = json.loads(self.cookie_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self.session.cookies.update(cookiejar_from_dict(data))
            if data:
                self.raw_cookie_header = "; ".join(
                    f"{key}={value}" for key, value in data.items()
                )

    def _save_cookies(self):
        if self.cookie_readonly:
            return
        try:
            data = dict_from_cookiejar(self.session.cookies)
            self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            self.cookie_path.write_text(
                json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            return

    def _has_auth_cookies(self):
        data = dict_from_cookiejar(self.session.cookies)
        return bool(data.get("Esc_Auth") and data.get("ASP.NET_SessionId"))

    def _has_app_context(self):
        data = dict_from_cookiejar(self.session.cookies)
        return bool(data.get("AppContext"))

    def _prime_app_context(self):
        if self._has_app_context():
            return None
        headers = {"Referer": urljoin(self.base_url + "/", "/")}
        if self.raw_cookie_header:
            headers["Cookie"] = self.raw_cookie_header
        try:
            response = self.session.get(
                urljoin(self.base_url + "/", "WarehouseTransfer"),
                headers=headers,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None
        self._save_cookies()
        return response

    def _cookie_dict_from_string(self, cookie_str):
        data = {}
        for part in cookie_str.split("; "):
            if not part or "=" not in part:
                continue
            key, value = part.split("=", 1)
            data[key] = value
        return data

    def _load_cookie_from_db(self):
        try:
            from configuration.models import RemarisCookie
        except Exception:
            return None
        try:
            cookie = RemarisCookie.objects.order_by("-updated_at").first()
        except Exception:
            return None
        if not cookie or not cookie.cookie:
            return None
        return cookie.cookie
