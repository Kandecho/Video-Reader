from __future__ import annotations

import json
from email.message import Message
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request

from PIL import Image

from video_reader import bilibili_auth as authmod
from video_reader.bilibili_auth import AuthError, BilibiliAuth, account_marker
from video_reader.common import ReaderError, read_json, settings, write_json


def nav(uid=10001):
    return {"code": 0, "data": {"isLogin": True, "mid": uid}}


def cookie_set(sess="session-old", csrf="csrf-old", uid="10001"):
    return [{"name": n, "value": v, "domain": ".bilibili.com", "path": "/", "expires": int(time.time()) + 90000, "secure": True}
            for n, v in (("SESSDATA", sess), ("bili_jct", csrf), ("DedeUserID", uid))]


class Script:
    def __init__(self, testcase, steps):
        self.testcase, self.steps, self.calls = testcase, list(steps), []

    def session(self, cookies=()):
        script = self
        class Session:
            def __init__(self):
                self.jar = authmod._jar(cookies)
                self.last_set_cookie_names = set()

            def request(self, url, form=None, as_json=True):
                script.calls.append((url, form))
                script.testcase.assertTrue(script.steps, "Unexpected authentication request")
                expected, body, updates = script.steps.pop(0)
                script.testcase.assertIn(expected, url)
                self.last_set_cookie_names = {item["name"] for item in updates}
                for cookie in authmod._jar(updates):
                    self.jar.set_cookie(cookie)
                if callable(body):
                    return body(self, form)
                if isinstance(body, Exception):
                    raise body
                return body
        return Session()


class BilibiliAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = settings(self.root / "config.json")
        self.auth = BilibiliAuth(self.config)

    def record(self, uid=10001, checked=0):
        record = {"schema_version": 1, "cookies": cookie_set(uid=str(uid)), "refresh_token": "refresh-old",
                  "account_marker": account_marker(uid), "created_at": time.time(), "verified_at": time.time(),
                  "last_refresh_check_at": checked}
        self.auth.directory.mkdir(parents=True, exist_ok=True)
        self.auth._save(record)
        return record

    def script(self, steps):
        script = Script(self, steps)
        patcher = patch.object(authmod, "BiliSession", side_effect=script.session)
        patcher.start()
        self.addCleanup(patcher.stop)
        return script

    def pending(self):
        login_id = "login_" + "a" * 32
        self.auth.directory.mkdir(parents=True, exist_ok=True)
        write_json(self.auth.directory / (login_id + ".json"), {"key": "qr-secret", "status": "waiting", "expires_at": time.time() + 180, "cookies": []})
        return login_id

    def test_start_renders_local_qr_and_returns_no_raw_key(self):
        script = self.script([("/qrcode/generate", {"code": 0, "data": {"url": "https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=qr-secret", "qrcode_key": "qr-secret"}}, [])])
        result = self.auth.start()
        with Image.open(result["qr_image_path"]) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 200)
        self.assertNotIn("qr-secret", json.dumps(result))
        self.assertEqual(len(script.calls), 1)
        self.assertEqual(read_json(self.auth._pending_path(result["login_id"]))["key"], "qr-secret")

    def test_legacy_qr_is_persisted_and_verified_not_just_present(self):
        login_id = self.pending()
        url = "https://passport.biligame.com/crossDomain?" + urlencode({"SESSDATA": "session-old", "bili_jct": "csrf-old", "DedeUserID": "10001"})
        script = self.script([("/qrcode/poll", {"code": 0, "data": {"code": 0, "url": url, "refresh_token": "refresh-old"}}, []),
                              ("/nav", nav(), [])])
        result = self.auth.poll(login_id)
        self.assertTrue(result["authenticated"])
        self.assertTrue(result["refresh_capable"])
        self.assertEqual(self.auth._load()["refresh_token"], "refresh-old")
        self.assertNotIn("session-old", json.dumps(result))
        self.assertNotIn("refresh-old", json.dumps(self.auth.poll(login_id)))
        self.assertEqual(len(script.calls), 2)
        self.assertTrue(self.auth.cookies_file.is_file())

    def test_modern_cross_domain_receives_cookies_then_verifies(self):
        login_id = self.pending()
        script = self.script([("/qrcode/poll", {"code": 0, "data": {"code": 0, "url": "https://passport.biligame.com/x/passport-login/web/crossDomain?ticket=private", "refresh_token": "refresh-old"}}, []),
                              ("/crossDomain?", "ok", cookie_set()), ("/nav", nav(), [])])
        self.assertTrue(self.auth.poll(login_id)["authenticated"])
        self.assertEqual(len(script.calls), 3)

    def test_cross_domain_passport_cookie_headers_are_collected(self):
        headers = Message()
        headers.add_header("Set-Cookie", "SESSDATA=passport-issued; Domain=.bilibili.com; Path=/; Secure")
        class Response:
            def info(self):
                return headers
        jar = authmod._jar()
        processor = authmod._AuthCookies(jar)
        processor.http_response(Request("https://passport.biligame.com/x/passport-login/web/crossDomain?ticket=fixture"), Response())
        self.assertEqual(authmod._cookie_value(jar, "SESSDATA"), "passport-issued")

    def test_consumed_qr_can_resume_after_verification_network_failure(self):
        login_id = self.pending()
        script = self.script([("/qrcode/poll", {"code": 0, "data": {"code": 0, "refresh_token": "refresh-old"}}, cookie_set()),
                              ("/nav", AuthError("BILIBILI_AUTH_UNAVAILABLE", "offline"), []), ("/nav", nav(), [])])
        with self.assertRaises(AuthError):
            self.auth.poll(login_id)
        self.assertIn("confirmed", read_json(self.auth._pending_path(login_id)))
        self.assertTrue(self.auth.poll(login_id)["authenticated"])
        self.assertEqual(sum("/qrcode/poll" in url for url, _ in script.calls), 1)

    def test_expiry_and_invalid_ids_do_not_make_requests(self):
        login_id = self.pending()
        pending = read_json(self.auth._pending_path(login_id))
        pending["expires_at"] = time.time() - 1
        write_json(self.auth._pending_path(login_id), pending)
        self.script([])
        self.assertEqual(self.auth.poll(login_id)["status"], "expired")
        with self.assertRaises(AuthError):
            self.auth.poll("../credential")
        with self.assertRaises(ReaderError):
            self.auth.poll(login_id, True)

    def test_login_rejects_untrusted_cookie_redirect(self):
        login_id = self.pending()
        self.script([("/qrcode/poll", {"code": 0, "data": {"code": 0, "url": "https://evil.example/crossDomain", "refresh_token": "secret"}}, [])])
        with self.assertRaisesRegex(AuthError, "unexpected destination"):
            self.auth.poll(login_id)
        self.assertFalse(self.auth.path.exists())
        for url in ("http://passport.bilibili.com/", "https://api.bilibili.com.evil.example/", "https://api.bilibili.com:8000/", "https://user@api.bilibili.com/"):
            with self.assertRaises(AuthError):
                authmod.trusted_url(url)

    def test_file_exists_but_revoked_cookie_requires_scan(self):
        original = self.record()
        self.script([("/nav", {"code": -101, "data": {"isLogin": False}}, [])])
        result = self.auth.status()
        self.assertEqual(result["status"], "login_required")
        self.assertFalse(result["authenticated"])
        self.assertTrue(result["requires_login"])
        self.assertEqual(self.auth._load(), original)

    def test_network_failure_is_unknown_and_preserves_credentials(self):
        original = self.record()
        self.script([("/nav", AuthError("BILIBILI_AUTH_UNAVAILABLE", "offline"), [])])
        result = self.auth.status()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["authenticated"])
        self.assertFalse(result["requires_login"])
        self.assertEqual(self.auth._load(), original)

    def test_renewal_rotates_all_credentials_before_confirming_old_token(self):
        self.record()
        def new_nav(session, form):
            saved = self.auth._load()
            self.assertEqual(saved["refresh_token"], "refresh-new")
            self.assertTrue(saved["pending_verification"])
            return nav()
        def confirm(session, form):
            self.assertEqual(form, {"csrf": "csrf-new", "refresh_token": "refresh-old"})
            self.assertEqual(self.auth._load()["pending_confirmation"], "refresh-old")
            return {"code": 0}
        script = self.script([("/nav", nav(), []), ("/cookie/info", {"code": 0, "data": {"refresh": True, "timestamp": 1790000000000}}, []),
                              ("/correspond/1/", '<div id="1-name">refresh-csrf</div>', []),
                              ("/cookie/refresh", {"code": 0, "data": {"status": 0, "refresh_token": "refresh-new"}}, cookie_set("session-new", "csrf-new")),
                              ("/nav", new_nav, []), ("/confirm/refresh", confirm, [])])
        result = self.auth.status()
        self.assertEqual(result["renewal"], "refreshed")
        saved = self.auth._load()
        self.assertEqual(saved["refresh_token"], "refresh-new")
        self.assertNotIn("pending_confirmation", saved)
        self.assertNotIn("pending_verification", saved)
        self.assertEqual(script.steps, [])

    def test_confirmation_failure_keeps_new_session_and_retries_next_use(self):
        self.record()
        script = self.script([("/nav", nav(), []), ("/cookie/info", {"code": 0, "data": {"refresh": True}}, []),
                              ("/correspond/1/", '<div id="1-name">refresh-csrf</div>', []),
                              ("/cookie/refresh", {"code": 0, "data": {"refresh_token": "refresh-new"}}, cookie_set("session-new", "csrf-new")),
                              ("/nav", nav(), []), ("/confirm/refresh", AuthError("BILIBILI_AUTH_UNAVAILABLE", "offline"), []),
                              ("/nav", nav(), []), ("/confirm/refresh", {"code": 0}, []),
                              ("/cookie/info", {"code": 0, "data": {"refresh": False}}, [])])
        first = self.auth.status()
        self.assertTrue(first["authenticated"])
        self.assertEqual(first["renewal"], "pending")
        self.assertEqual(self.auth._load()["refresh_token"], "refresh-new")
        self.assertTrue(self.auth.status()["authenticated"])
        self.assertNotIn("pending_confirmation", self.auth._load())
        self.assertEqual(sum("/cookie/refresh" in url for url, _ in script.calls), 1)

    def test_new_session_survives_network_failure_before_post_refresh_validation(self):
        self.record()
        self.script([("/nav", nav(), []), ("/cookie/info", {"code": 0, "data": {"refresh": True}}, []),
                     ("/correspond/1/", '<div id="1-name">refresh-csrf</div>', []),
                     ("/cookie/refresh", {"code": 0, "data": {"refresh_token": "refresh-new"}}, cookie_set("session-new", "csrf-new")),
                     ("/nav", AuthError("BILIBILI_AUTH_UNAVAILABLE", "offline"), []),
                     ("/nav", nav(), []), ("/confirm/refresh", {"code": 0}, []), ("/cookie/info", {"code": 0, "data": {"refresh": False}}, [])])
        first = self.auth.status()
        self.assertIsNone(first["authenticated"])
        self.assertEqual(self.auth._load()["refresh_token"], "refresh-new")
        self.assertTrue(self.auth.status()["authenticated"])

    def test_malformed_refresh_does_not_replace_working_credentials(self):
        self.record()
        self.script([("/nav", nav(), []), ("/cookie/info", {"code": 0, "data": {"refresh": True}}, []),
                     ("/correspond/1/", '<div id="1-name">refresh-csrf</div>', []),
                     ("/cookie/refresh", {"code": 0, "data": {"refresh_token": "bad-refresh"}}, [])])
        self.assertEqual(self.auth.status()["renewal"], "unavailable")
        self.assertEqual(self.auth._load()["refresh_token"], "refresh-old")

    def test_refresh_cannot_silently_switch_accounts(self):
        self.record()
        self.script([("/nav", nav(), []), ("/cookie/info", {"code": 0, "data": {"refresh": True}}, []),
                     ("/correspond/1/", '<div id="1-name">refresh-csrf</div>', []),
                     ("/cookie/refresh", {"code": 0, "data": {"refresh_token": "bad-refresh"}}, cookie_set("other-session", "other-csrf", "20002"))])
        result = self.auth.status()
        self.assertEqual(result["renewal_code"], "BILIBILI_AUTH_ACCOUNT_MISMATCH")
        self.assertEqual(self.auth._load()["account_marker"], account_marker(10001))
        self.assertEqual(self.auth._load()["refresh_token"], "refresh-old")

    def test_live_verification_is_fresh_but_renewal_check_is_throttled(self):
        self.record()
        script = self.script([("/nav", nav(), []), ("/cookie/info", {"code": 0, "data": {"refresh": False}}, []), ("/nav", nav(), [])])
        self.assertTrue(self.auth.status()["authenticated"])
        self.assertTrue(self.auth.status()["authenticated"])
        self.assertEqual(len(script.calls), 3)

    def test_downloader_snapshot_is_temporary_and_account_scope_is_stable(self):
        self.record(checked=time.time())
        self.script([("/nav", nav(), []), ("/nav", nav(), []), ("/nav", nav(20002), [])])
        profile = self.config["platforms"]["bilibili"]
        with self.auth.reader_profile(profile) as (io, cache1, public):
            snapshot = Path(io["cookies_file"])
            self.assertNotEqual(snapshot, self.auth.cookies_file)
            snapshot.write_text("downloader rewrote its private file", encoding="utf-8")
            self.assertTrue(public["authenticated"])
        self.assertFalse(snapshot.exists())
        self.assertEqual(authmod._cookie_value(authmod._jar(self.auth._load()["cookies"]), "SESSDATA"), "session-old")
        record = self.auth._load()
        record["cookies"] = cookie_set("rotated", "rotated-csrf")
        self.auth._save(record)
        with self.auth.reader_profile(profile) as (_, cache2, _):
            self.assertEqual(cache1, cache2)
        self.record(uid=20002, checked=time.time())
        with self.auth.reader_profile(profile) as (_, cache3, _):
            self.assertNotEqual(cache1["auth_scope"], cache3["auth_scope"])

    def test_logout_only_removes_local_state(self):
        self.record()
        self.pending()
        self.script([])
        self.assertEqual(self.auth.logout()["status"], "logged_out")
        self.assertFalse(self.auth.path.exists())
        self.assertEqual(list(self.auth.directory.glob("login_*")), [])

    def test_mcp_login_returns_native_png_without_secret_fields(self):
        from video_reader.mcp_server import bilibili_login
        image_path = self.root / "qr.png"
        Image.new("RGB", (220, 220), "white").save(image_path)
        with patch.object(authmod, "login_action", return_value={"status": "waiting_scan", "qr_image_path": str(image_path), "login_id": "opaque"}):
            blocks = bilibili_login("start")
        self.assertEqual([b.type for b in blocks], ["text", "image"])
        self.assertEqual(blocks[1].mimeType, "image/png")


if __name__ == "__main__":
    unittest.main(verbosity=2)
