"""Component-owned Bilibili Web login and renewal; no browser cookie discovery."""
from __future__ import annotations

from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import hashlib
import http.cookiejar
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request
import uuid

from filelock import FileLock

from .common import ReaderError, read_json, write_json
from .jobs import resource_lock

PASSPORT = "https://passport.bilibili.com/x/passport-login/web"
NAV = "https://api.bilibili.com/x/web-interface/nav"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
AUTH_HOSTS = {"passport.bilibili.com", "www.bilibili.com", "account.bilibili.com", "api.bilibili.com", "passport.biligame.com"}
PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
JNrRuoEUXpabUzGB8QIDAQAB
-----END PUBLIC KEY-----"""


class AuthError(ReaderError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def account_marker(uid):
    return hashlib.sha256(str(uid).encode()).hexdigest()[:12]


def trusted_url(url):
    try:
        parsed = urlparse(url)
        allowed = parsed.scheme == "https" and parsed.hostname in AUTH_HOSTS and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except (ValueError, TypeError):
        allowed = False
    if not allowed:
        raise AuthError("BILIBILI_AUTH_REDIRECT_REFUSED", "Bilibili login refused an unexpected destination")
    return url


class _AuthRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _AuthCookies(HTTPCookieProcessor):
    def http_response(self, request, response):
        super().http_response(request, response)
        # Cross-domain login can issue Web credential pairs from Biligame's passport.
        if urlparse(request.full_url).hostname == "passport.biligame.com":
            for header in response.info().get_all("Set-Cookie", []):
                parsed = SimpleCookie()
                parsed.load(header)
                for name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"):
                    if name in parsed:
                        morsel = parsed[name]
                        try:
                            expires = int(parsedate_to_datetime(morsel["expires"]).timestamp()) if morsel["expires"] else None
                        except (ValueError, TypeError):
                            expires = None
                        self.cookiejar.set_cookie(_cookie(name, morsel.value, expires=expires))
        return response

    https_response = http_response


def _cookie(name, value, domain=".bilibili.com", path="/", expires=None, secure=True, rest=None):
    return http.cookiejar.Cookie(0, name, value, None, False, domain, True, domain.startswith("."),
                                path, True, secure, expires, expires is None, None, None, rest or {}, False)


def _jar(cookies=()):
    jar = http.cookiejar.MozillaCookieJar()
    for item in cookies:
        if item["domain"].lstrip(".") not in {"bilibili.com", *AUTH_HOSTS - {"passport.biligame.com"}}:
            continue
        jar.set_cookie(_cookie(item["name"], item["value"], item["domain"], item.get("path", "/"),
                               item.get("expires"), item.get("secure", True), item.get("rest")))
    return jar


def _cookies(jar):
    return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
             "expires": c.expires, "secure": c.secure, "rest": c._rest}
            for c in jar if c.domain.lstrip(".") == "bilibili.com" or c.domain.lstrip(".").endswith(".bilibili.com")]


def _cookie_value(jar, name):
    return next((c.value for c in jar if c.name == name and c.domain.lstrip(".").endswith("bilibili.com")), "")


def _export_cookies(path, jar):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cookies-", dir=path.parent)
    os.close(fd)
    try:
        jar.save(temporary, ignore_discard=True, ignore_expires=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _envelope(data):
    if not isinstance(data, dict) or "code" not in data:
        raise AuthError("BILIBILI_AUTH_BAD_RESPONSE", "Bilibili login returned an invalid response")
    code = data["code"]
    if code != 0:
        label = "BILIBILI_LOGIN_REQUIRED" if code == -101 else "BILIBILI_AUTH_API_ERROR"
        raise AuthError(label, f"Bilibili authentication returned code {code}")
    return data.get("data") or {}


class BiliSession:
    def __init__(self, cookies=()):
        self.jar = _jar(cookies)
        self.opener = build_opener(_AuthRedirect(), _AuthCookies(self.jar))
        self.last_set_cookie_names = set()

    def request(self, url, form=None, as_json=True):
        trusted_url(url)
        headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/", "Origin": "https://www.bilibili.com"}
        body = urlencode(form).encode() if form is not None else None
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            with self.opener.open(Request(url, data=body, headers=headers), timeout=15) as response:
                self.last_set_cookie_names = set()
                for header in response.headers.get_all("Set-Cookie", []):
                    parsed = SimpleCookie()
                    parsed.load(header)
                    self.last_set_cookie_names.update(parsed.keys())
                text = response.read().decode("utf-8")
            return json.loads(text) if as_json else text
        except AuthError:
            raise
        except (OSError, ValueError) as exc:
            raise AuthError("BILIBILI_AUTH_UNAVAILABLE", f"Bilibili authentication request unavailable ({type(exc).__name__})") from None


def _legacy_credentials(url, session):
    """Older QR responses carry cookie parameters, sometimes in a nested URL."""
    queue, seen = [url], set()
    while queue:
        candidate = queue.pop(0)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        trusted_url(candidate)
        query = parse_qs(urlparse(candidate).query)
        if query.get("SESSDATA"):
            expiry = query.get("Expires", [None])[0]
            expiry = int(expiry) if expiry and str(expiry).isdigit() else None
            for name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                if query.get(name):
                    session.jar.set_cookie(_cookie(name, query[name][0], expires=expiry))
            return True
        queue.extend(value for values in query.values() for value in values if value.startswith("https://") and "passport" in value)
    return False


def _correspond_path(timestamp):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_public_key(PUBLIC_KEY)
    return key.encrypt(f"refresh_{int(timestamp)}".encode(),
                       padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)).hex()


class BilibiliAuth:
    def __init__(self, config):
        self.options = config["bilibili_auth"]
        self.directory = Path(self.options["directory"])
        self.path = self.directory / "credential.json"
        self.cookies_file = self.directory / "cookies.txt"

    @contextmanager
    def _lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with resource_lock(self.directory, kind='account', timeout=30):
            yield

    def _load(self):
        if not self.path.is_file():
            return None
        try:
            record = read_json(self.path)
            if record.get("schema_version") != 1 or not _cookie_value(_jar(record["cookies"]), "SESSDATA"):
                raise ValueError()
            return record
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise AuthError("BILIBILI_AUTH_STORE_INVALID", "Bilibili credential store is unreadable; scan again to replace it") from None

    def _save(self, record):
        write_json(self.path, record)
        os.chmod(self.path, 0o600)
        _export_cookies(self.cookies_file, _jar(record["cookies"]))

    def _public(self, record, status="authenticated", **extra):
        return {"platform": "bilibili", "status": status,
                "authenticated": True if status == "authenticated" else None if status == "unavailable" else False,
                "requires_login": status == "login_required", "account_marker": record.get("account_marker") if record else None,
                "refresh_capable": bool(record and record.get("refresh_token") and _cookie_value(_jar(record["cookies"]), "bili_jct")),
                "verified_at": record.get("verified_at") if record else None,
                "last_refreshed_at": record.get("last_refreshed_at") if record else None, **extra}

    def _verify(self, session, expected=None):
        data = _envelope(session.request(NAV))
        if data.get("isLogin") is not True or not data.get("mid"):
            raise AuthError("BILIBILI_LOGIN_REQUIRED", "Bilibili session is no longer authenticated; scan again")
        marker = account_marker(data["mid"])
        if expected and marker != expected:
            raise AuthError("BILIBILI_AUTH_ACCOUNT_MISMATCH", "Bilibili returned a different account during credential renewal")
        return marker

    def start(self):
        if not self.options["enabled"]:
            raise AuthError("BILIBILI_AUTH_DISABLED", "Managed Bilibili login is disabled in config.json")
        session = BiliSession()
        data = _envelope(session.request(PASSPORT + "/qrcode/generate"))
        url, key = data.get("url"), data.get("qrcode_key")
        if not url or not key:
            raise AuthError("BILIBILI_AUTH_BAD_RESPONSE", "Bilibili did not return a login QR code")
        trusted_url(url)
        import qrcode
        login_id = "login_" + uuid.uuid4().hex
        with self._lock():
            image_path = self.directory / (login_id + ".png")
            qrcode.make(url).save(image_path)
            os.chmod(image_path, 0o600)
            expires = time.time() + 180
            write_json(self.directory / (login_id + ".json"), {"key": key, "expires_at": expires, "status": "waiting", "cookies": _cookies(session.jar)})
        return {"status": "waiting_scan", "login_id": login_id, "qr_image_path": str(image_path), "expires_at": expires,
                "message": "请用目标账号的哔哩哔哩 App 扫码并确认，再调用 poll。"}

    def _pending_path(self, login_id):
        if not isinstance(login_id, str) or not re.fullmatch(r"login_[a-f0-9]{32}", login_id):
            raise AuthError("BILIBILI_LOGIN_ID_INVALID", "Invalid Bilibili login id")
        return self.directory / (login_id + ".json")

    def poll(self, login_id, wait_seconds=0):
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= 20:
            raise ReaderError("wait_seconds must be an integer between 0 and 20")
        deadline = time.monotonic() + wait_seconds
        while True:
            result = self._poll_once(login_id)
            if result["status"] not in ("waiting", "scanned") or time.monotonic() >= deadline:
                return result
            time.sleep(min(2, max(0, deadline - time.monotonic())))

    def _poll_once(self, login_id):
        path = self._pending_path(login_id)
        with self._lock():
            if not path.is_file():
                raise AuthError("BILIBILI_LOGIN_NOT_FOUND", "Bilibili login id not found; start a new QR login")
            pending = read_json(path)
            if pending["status"] in ("authenticated", "expired"):
                return {"login_id": login_id, **pending}
            if time.time() >= pending["expires_at"]:
                write_json(path, {"status": "expired"})
                path.with_suffix(".png").unlink(missing_ok=True)
                return {"login_id": login_id, "status": "expired"}
            session = BiliSession(pending.get("cookies", []))
            data = pending.get("confirmed")
            if data is None:
                data = _envelope(session.request(PASSPORT + "/qrcode/poll?" + urlencode({"qrcode_key": pending["key"]})))
            code = data.get("code")
            if code in (86101, 86090):
                return {"login_id": login_id, "status": "waiting" if code == 86101 else "scanned"}
            if code == 86038:
                write_json(path, {"status": "expired"})
                path.with_suffix(".png").unlink(missing_ok=True)
                return {"login_id": login_id, "status": "expired"}
            if code != 0:
                raise AuthError("BILIBILI_AUTH_API_ERROR", f"Bilibili QR login returned code {code}")
            # A successful QR key may be consumed: preserve its response before further I/O.
            pending.update(confirmed=data, cookies=_cookies(session.jar))
            write_json(path, pending)
            redirect = data.get("url")
            if redirect and not all(_cookie_value(session.jar, name) for name in ("SESSDATA", "bili_jct", "DedeUserID")):
                trusted_url(redirect)
                if not _legacy_credentials(redirect, session):
                    try:
                        session.request(redirect, as_json=False)
                    finally:
                        pending["cookies"] = _cookies(session.jar)
                        write_json(path, pending)
            if not all(_cookie_value(session.jar, name) for name in ("SESSDATA", "bili_jct", "DedeUserID")):
                raise AuthError("BILIBILI_AUTH_INCOMPLETE", "QR confirmation returned incomplete cookies; start a new QR login")
            pending["cookies"] = _cookies(session.jar)
            write_json(path, pending)
            marker = self._verify(session)
            now = time.time()
            record = {"schema_version": 1, "cookies": _cookies(session.jar), "refresh_token": data.get("refresh_token", ""),
                      "account_marker": marker, "created_at": now, "verified_at": now, "last_refresh_check_at": 0}
            self._save(record)
            public = self._public(record)
            write_json(path, public)
            path.with_suffix(".png").unlink(missing_ok=True)
            return {"login_id": login_id, **public}

    def _confirm(self, record, session):
        old_token = record.get("pending_confirmation")
        if old_token:
            _envelope(session.request(PASSPORT + "/confirm/refresh", {"csrf": _cookie_value(session.jar, "bili_jct"), "refresh_token": old_token}))
            record.pop("pending_confirmation", None)
            self._save(record)

    def _renew(self, record, session, timestamp):
        csrf_path = _correspond_path(timestamp)
        html = session.request("https://www.bilibili.com/correspond/1/" + csrf_path, as_json=False)
        match = re.search(r'<div\s+id=[\"\x27]1-name[\"\x27][^>]*>([^<]+)</div>', html)
        if not match:
            raise AuthError("BILIBILI_REFRESH_CSRF_UNAVAILABLE", "Bilibili did not return its refresh CSRF token")
        previous = record["refresh_token"]
        data = _envelope(session.request(PASSPORT + "/cookie/refresh", {"csrf": _cookie_value(session.jar, "bili_jct"),
                         "refresh_csrf": match[1], "refresh_token": previous, "source": "main_web"}))
        if not data.get("refresh_token") or data.get("status", 0) != 0:
            raise AuthError("BILIBILI_AUTH_INCOMPLETE", "Bilibili credential refresh returned incomplete data")
        if not {"SESSDATA", "bili_jct", "DedeUserID"}.issubset(session.last_set_cookie_names):
            raise AuthError("BILIBILI_AUTH_INCOMPLETE", "Bilibili credential refresh did not issue complete cookies")
        if account_marker(_cookie_value(session.jar, "DedeUserID")) != record["account_marker"]:
            raise AuthError("BILIBILI_AUTH_ACCOUNT_MISMATCH", "Bilibili refresh cookies belong to another account")
        record.update(cookies=_cookies(session.jar), refresh_token=data["refresh_token"],
                      last_refreshed_at=time.time(), pending_confirmation=previous, pending_verification=True)
        # Persist the new session before confirming revocation of the old session.
        self._save(record)
        self._verify(session, record["account_marker"])
        record.pop("pending_verification", None)
        record["verified_at"] = time.time()
        record["cookies"] = _cookies(session.jar)
        self._confirm(record, session)

    def _maintain(self, record, check_now=False):
        session = BiliSession(record["cookies"])
        try:
            self._verify(session, record["account_marker"])
        except AuthError as exc:
            if exc.code == "BILIBILI_LOGIN_REQUIRED":
                return self._public(record, "login_required", code=exc.code)
            return self._public(record, "unavailable", code=exc.code)
        record["verified_at"] = time.time()
        record.pop("pending_verification", None)
        renewal = "not_due"
        try:
            self._confirm(record, session)
            due = time.time() - record.get("last_refresh_check_at", 0) >= self.options["check_interval_seconds"]
            if check_now or due:
                info = _envelope(session.request(PASSPORT + "/cookie/info?" + urlencode({"csrf": _cookie_value(session.jar, "bili_jct")})))
                if info.get("refresh"):
                    if not record.get("refresh_token"):
                        self._save(record)
                        return self._public(record, renewal="missing_refresh_token", message="需要重新扫码一次，才能获得自动续期凭据。")
                    self._renew(record, session, info.get("timestamp", int(time.time() * 1000)))
                    renewal = "refreshed"
                else:
                    renewal = "not_needed"
                record["last_refresh_check_at"] = time.time()
            self._save(record)
        except AuthError as exc:
            # A renewal/confirmation outage does not mean the verified account logged out.
            return self._public(record, "unavailable" if record.get("pending_verification") else "authenticated",
                                renewal="pending" if record.get("pending_confirmation") else "unavailable", renewal_code=exc.code)
        return self._public(record, renewal=renewal)

    def status(self, check_now=False):
        if not self.options["enabled"]:
            return {"platform": "bilibili", "status": "disabled", "authenticated": None, "requires_login": False}
        with self._lock():
            record = self._load()
            return self._maintain(record, check_now) if record else self._public(None, "login_required")

    def logout(self):
        with self._lock():
            self.path.unlink(missing_ok=True)
            self.cookies_file.unlink(missing_ok=True)
            for path in self.directory.glob("login_*"):
                if path.is_file() and re.fullmatch(r"login_[a-f0-9]{32}\.(json|png)", path.name):
                    path.unlink()
        return {"platform": "bilibili", "status": "logged_out", "authenticated": False,
                "message": "组件本地凭据已清除；没有调用平台的退出登录接口。"}

    @contextmanager
    def reader_profile(self, profile):
        """Keep account scope stable across renewal; isolate yt-dlp's cookie-file writes."""
        if not self.options["enabled"]:
            yield profile, profile, None
            return
        with self._lock():
            record = self._load()
            public = self._maintain(record) if record else self._public(None, "anonymous")
            if record and public["status"] == "login_required":
                raise AuthError("BILIBILI_LOGIN_REQUIRED", "Saved Bilibili session is invalid; use bilibili_login start to scan again")
            cache_profile = {**profile, "cookies_file": str(self.cookies_file) if record else None,
                             "auth_scope": record["account_marker"] if record else "anonymous"}
            if record:
                temporary = tempfile.TemporaryDirectory(prefix="reader-", dir=self.directory)
                snapshot = Path(temporary.name) / "cookies.txt"
                _export_cookies(snapshot, _jar(record["cookies"]))
                io_profile = {**cache_profile, "cookies_file": str(snapshot)}
            else:
                temporary, io_profile = None, cache_profile
        try:
            yield io_profile, cache_profile, public
        finally:
            if temporary:
                temporary.cleanup()


def login_action(config, action, login_id=None, wait_seconds=0):
    auth = BilibiliAuth(config)
    if action == "start":
        return auth.start()
    if action == "poll":
        return auth.poll(login_id, wait_seconds)
    if action in ("status", "refresh"):
        return auth.status(check_now=action == "refresh")
    if action == "logout":
        return auth.logout()
    raise ReaderError("Bilibili login action must be start, poll, status, refresh or logout")
