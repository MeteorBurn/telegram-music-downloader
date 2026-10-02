import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from telethon import errors

import web_auth
from web_auth import AuthFlowError, TelegramAuthService, mask_phone


class FakeClient:
    def __init__(self, authorized=False, sign_in_errors=()):
        self.authorized = authorized
        self.connected = False
        self.sign_in_errors = list(sign_in_errors)
        self.calls = []
        self.disconnects = 0

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True
        self.calls.append("connect")

    async def disconnect(self):
        self.connected = False
        self.disconnects += 1

    async def is_user_authorized(self):
        return self.authorized

    async def get_me(self):
        return SimpleNamespace(
            id=1, first_name="Ann", last_name="", username="ann", phone="79991234567"
        )

    async def send_code_request(self, phone):
        self.calls.append(("send_code_request", phone))
        return SimpleNamespace(phone_code_hash="hash1")

    async def sign_in(self, **kwargs):
        self.calls.append(("sign_in", kwargs))
        if self.sign_in_errors:
            raise self.sign_in_errors.pop(0)
        self.authorized = True
        return await self.get_me()

    async def log_out(self):
        self.authorized = False
        self.calls.append("log_out")


class WebAuthTests(unittest.IsolatedAsyncioTestCase):
    def make(self, **client_kwargs):
        self.client = FakeClient(**client_kwargs)
        return TelegramAuthService("unused.yaml", client_factory=lambda _config: self.client)

    def setUp(self):
        # The default factory path builds ConfigLoader; tests bypass it.
        self._orig = web_auth.ConfigLoader
        web_auth.ConfigLoader = lambda path: SimpleNamespace()
        self.addCleanup(setattr, web_auth, "ConfigLoader", self._orig)

    async def test_happy_path_phone_code_authorized(self):
        service = self.make()
        status = await service.send_code("+7 (999) 123-45-67")
        self.assertEqual(status["state"], "code_sent")
        self.assertEqual(status["phone_masked"], "+79*******67")
        self.assertIn(("send_code_request", "+79991234567"), self.client.calls)
        self.assertTrue(self.client.connected)

        status = await service.submit_code("1-2 3 4 5")
        self.assertEqual(status["state"], "authorized")
        self.assertEqual(status["user"]["username"], "ann")
        self.assertEqual(
            self.client.calls[-1],
            ("sign_in", {"phone": "+79991234567", "code": "12345", "phone_code_hash": "hash1"}),
        )
        self.assertFalse(self.client.connected)
        self.assertEqual(service.cached_status(), status)

    async def test_two_factor_path(self):
        service = self.make(sign_in_errors=[errors.SessionPasswordNeededError(None)])
        await service.send_code("+79991234567")
        self.assertEqual((await service.submit_code("12345"))["state"], "password_needed")
        self.assertTrue(self.client.connected)
        status = await service.submit_password("secret")
        self.assertEqual(status["state"], "authorized")
        self.assertEqual(self.client.calls[-1], ("sign_in", {"password": "secret"}))
        self.assertFalse(self.client.connected)

    async def test_invalid_code_stays_code_sent(self):
        service = self.make(sign_in_errors=[errors.PhoneCodeInvalidError(None)])
        await service.send_code("+79991234567")
        with self.assertRaises(AuthFlowError) as ctx:
            await service.submit_code("00000")
        self.assertEqual(ctx.exception.code, "invalid_code")
        self.assertEqual((await service.status())["state"], "code_sent")
        self.assertTrue(self.client.connected)

    async def test_expired_code_resets(self):
        service = self.make(sign_in_errors=[errors.PhoneCodeExpiredError(None)])
        await service.send_code("+79991234567")
        with self.assertRaises(AuthFlowError) as ctx:
            await service.submit_code("12345")
        self.assertEqual(ctx.exception.code, "code_expired")
        self.assertEqual(service.cached_status()["state"], "unauthorized")
        self.assertFalse(self.client.connected)

    async def test_submit_without_pending_login(self):
        service = self.make()
        for call in (service.submit_code("12345"), service.submit_password("x")):
            with self.assertRaises(AuthFlowError) as ctx:
                await call
            self.assertEqual(ctx.exception.code, "no_pending_login")

    async def test_invalid_phone_does_not_touch_client(self):
        service = self.make()
        with self.assertRaises(AuthFlowError) as ctx:
            await service.send_code("12ab")
        self.assertEqual(ctx.exception.code, "invalid_phone")
        self.assertEqual(self.client.calls, [])

    async def test_idle_status_disconnects(self):
        service = self.make(authorized=True)
        status = await service.status()
        self.assertEqual(status["state"], "authorized")
        self.assertFalse(self.client.connected)
        self.assertEqual(self.client.disconnects, 1)

    async def test_flood_wait_reports_seconds(self):
        service = self.make()
        self.client.send_code_request = self._raise(errors.FloodWaitError(None, 42))
        with self.assertRaises(AuthFlowError) as ctx:
            await service.send_code("+79991234567")
        self.assertEqual(ctx.exception.code, "flood_wait")
        self.assertIn("42", ctx.exception.message)

    @staticmethod
    def _raise(exc):
        async def raiser(*args, **kwargs):
            raise exc

        return raiser

    def test_mask_never_leaks_digits(self):
        masked = mask_phone("+79991234567")
        self.assertEqual(masked, "+79*******67")
        self.assertNotIn("9912345", masked)
        self.assertEqual(mask_phone("1234"), "****")
        self.assertIsNone(mask_phone(None))


if __name__ == "__main__":
    unittest.main()
