"""Loopback HTTP guard. No credentials are embedded in the source tree."""
import base64
import hashlib
import hmac
import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class LocalError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, handler):
        if address[0] != "127.0.0.1":
            raise ValueError("Only IPv4 loopback is supported")
        self.local_token = secrets.token_urlsafe(32)
        super().__init__(address, handler)


class LocalHandler(BaseHTTPRequestHandler):
    server_version = "LocalApp"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, fmt, *args):
        # Paths, query strings, transcripts and authentication never go to logs.
        pass

    def guard(self, api=False, mutation=False):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get_all("Host") != [host]:
            raise LocalError("Host rejeitado.", 403)
        origin = self.headers.get("Origin")
        if origin is not None and origin != "http://" + host:
            raise LocalError("Origem rejeitada.", 403)
        site = self.headers.get("Sec-Fetch-Site", "")
        if site in ("cross-site", "same-site"):
            raise LocalError("Pedido externo rejeitado.", 403)
        if api or mutation:
            token = self.headers.get("X-Local-Token", "")
            if not hmac.compare_digest(token.encode(), self.server.local_token.encode()):
                raise LocalError("Reabra a página local para autenticar.", 403)
        if mutation:
            if origin != "http://" + host:
                raise LocalError("Origem obrigatória para alterações.", 403)
            if self.headers.get_content_type() != "application/json":
                raise LocalError("Envie application/json.", 415)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1 or not lengths[0].isdigit() or self.headers.get("Transfer-Encoding"):
            raise LocalError("Comprimento inválido.")
        length = int(lengths[0])
        if not 0 < length <= 1_000_000:
            raise LocalError("Pedido vazio ou grande demais.", 413)
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete")
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise LocalError("JSON inválido.") from None
        if not isinstance(data, dict):
            raise LocalError("O pedido precisa ser um objeto JSON.")
        return data

    def serve_html(self, path):
        html = path.read_text(encoding="utf-8")
        html = html.replace("__LOCAL_TOKEN_JSON__", json.dumps(self.server.local_token))
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        hashes = ["'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'" for s in scripts]
        csp = "default-src 'none'; script-src " + " ".join(hashes) + "; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        raw = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        self.wfile.write(raw)
