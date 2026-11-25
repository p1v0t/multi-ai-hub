"""Real loopback requests; never use external accounts or credentials."""
import http.client
import json
import threading
import unittest
from local_http import LocalError, LocalHandler, LocalServer


class Probe(LocalHandler):
    calls = 0
    def do_GET(self):
        try:
            self.guard(api=True)
            self.send_json({"ok": True})
        except LocalError as exc:
            self.send_json({"error": str(exc)}, exc.status)

    def do_POST(self):
        try:
            self.guard(api=True, mutation=True)
            data = self.read_json()
            Probe.calls += 1
            self.send_json(data)
        except LocalError as exc:
            self.send_json({"error": str(exc)}, exc.status)


class HttpSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer(("127.0.0.1", 0), Probe)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def request(self, method="POST", headers=None, body='{"confirm":true}'):
        h = {"X-Local-Token": self.server.local_token, "Origin": self.origin, "Content-Type": "application/json"}
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        c.request(method, "/api/test", body=body, headers=h)
        r = c.getresponse(); status, result, hdr = r.status, r.read(), dict(r.getheaders()); c.close()
        return status, result, hdr

    def test_allowed_local_json(self):
        self.assertEqual(self.request()[0], 200)

    def test_external_origin_cannot_mutate(self):
        before = Probe.calls
        self.assertEqual(self.request(headers={"Origin": "https://example.invalid"})[0], 403)
        self.assertEqual(Probe.calls, before)

    def test_arbitrary_host_rejected_on_reads(self):
        self.assertEqual(self.request("GET", {"Host": "example.invalid"})[0], 403)

    def test_token_required_on_reads(self):
        self.assertEqual(self.request("GET", {"X-Local-Token": ""})[0], 403)

    def test_plain_text_post_rejected(self):
        self.assertEqual(self.request(headers={"Content-Type": "text/plain"})[0], 415)

    def test_cross_site_blocked_even_with_token(self):
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_invalid_and_large_lengths_rejected(self):
        for length in ("-1", "bad", "1000001"):
            with self.subTest(length=length):
                self.assertIn(self.request(headers={"Content-Length": length})[0], (400, 413))

    def test_transfer_encoding_rejected(self):
        self.assertEqual(self.request(headers={"Transfer-Encoding": "chunked"})[0], 400)

    def test_nonobject_json_rejected(self):
        self.assertEqual(self.request(body="[]")[0], 400)

    def test_bad_json_rejected(self):
        self.assertEqual(self.request(body="{")[0], 400)

    def test_hardening_headers(self):
        headers = self.request()[2]
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_nonloopback_bind_rejected(self):
        with self.assertRaises(ValueError):
            LocalServer(("0.0.0.0", 0), Probe)


if __name__ == "__main__":
    unittest.main()
