"""Local-only dashboard server: history, stats, live status. Binds 127.0.0.1, stdlib only.

Binding to loopback is not by itself a security boundary. Every web page the
user has open can also reach 127.0.0.1, and a page that resolves its own domain
to 127.0.0.1 (DNS rebinding) is treated by the browser as same-origin, so it
could read responses too. Since this API hands out every transcript the user has
ever dictated, and accepts writes to the dictionary that rewrite all future
dictations, three checks guard it:

  * a random per-launch token, sent as a header that a cross-origin page cannot
    set without triggering a preflight this server never answers,
  * the Host header must name loopback and our port, which is what stops DNS
    rebinding, and
  * any Origin header must be our own.
"""

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from .history import History

PREFERRED_PORT = 47747
DASHBOARD = Path(__file__).parent / "dashboard.html"
TOKEN_HEADER = "X-Momito-Token"
MAX_BODY = 64 * 1024  # nothing this API accepts is remotely this big
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")

# default-src 'none' means a transcript that somehow escaped escaping still
# cannot pull in a remote script or beacon anything out.
CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; connect-src 'self'; form-action 'none'; base-uri 'none'"
)

StatusFn = Callable[[], dict]


class DashboardServer:
    """Serves the dashboard page and a small JSON API for it."""

    def __init__(
        self,
        history: History,
        status: StatusFn,
        on_open: Optional[Callable[[], None]] = None,
    ) -> None:
        self.history = history
        self.status = status
        self.on_open = on_open
        self.token = secrets.token_urlsafe(24)
        self._server: Optional[ThreadingHTTPServer] = None
        self.port = 0

    def start(self) -> None:
        handler = self._make_handler()
        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", PREFERRED_PORT), handler)
        except OSError:
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        """The dashboard URL, token included: the page has no other way to get it."""
        return f"{self.origin}/?t={self.token}"

    def _make_handler(self) -> type:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # keep the app log quiet

            # --- gatekeeping ---

            def _host_ok(self) -> bool:
                host = self.headers.get("Host", "")
                name, _, port = host.rpartition(":")
                if not name:  # no port at all
                    name, port = host, ""
                return name in LOOPBACK_HOSTS and port == str(outer.port)

            def _origin_ok(self) -> bool:
                origin = self.headers.get("Origin")
                if origin in (None, "", "null"):
                    return True  # same-origin GETs and our own page send nothing
                parsed = urlparse(origin)
                return parsed.hostname in ("127.0.0.1", "localhost", "::1") and (
                    parsed.port == outer.port
                )

            def _token_ok(self, query: str) -> bool:
                sent = self.headers.get(TOKEN_HEADER) or parse_qs(query).get("t", [""])[0]
                return hmac.compare_digest(sent, outer.token)

            def _allowed(self, query: str = "") -> bool:
                """Every request passes through here before anything is read or written."""
                if not self._host_ok() or not self._origin_ok():
                    self._json({"error": "forbidden"}, 403)
                    return False
                if not self._token_ok(query):
                    self._json({"error": "unauthorized"}, 401)
                    return False
                return True

            # --- responses ---

            def _send(self, body: bytes, code: int, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                if code >= 400:
                    # we answer some errors (403, 401, 413) without reading the
                    # request body, so those bytes are still in the socket. On a
                    # keep-alive connection the next request would start reading
                    # mid-body and desync, so hang up instead. send_header sets
                    # close_connection for us when it sees this.
                    self.send_header("Connection", "close")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, payload: Any, code: int = 200) -> None:
                self._send(json.dumps(payload).encode("utf-8"), code, "application/json")

            def _body(self) -> Optional[dict]:
                """Parsed JSON body, or None after already answering with an error."""
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._json({"error": "bad content-length"}, 400)
                    return None
                if length > MAX_BODY:
                    self._json({"error": "body too large"}, 413)
                    return None
                try:
                    data = json.loads(self.rfile.read(length) or b"{}")
                except Exception:
                    self._json({"error": "malformed json"}, 400)
                    return None
                if not isinstance(data, dict):
                    self._json({"error": "expected a json object"}, 400)
                    return None
                return data

            def _entry_id(self, data: dict) -> Optional[int]:
                try:
                    return int(data["id"])
                except (KeyError, TypeError, ValueError):
                    self._json({"error": "id must be a number"}, 400)
                    return None

            # --- routes ---

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if not self._allowed(parsed.query):
                    return
                if parsed.path == "/":
                    self._send(DASHBOARD.read_bytes(), 200, "text/html; charset=utf-8")
                    return
                if parsed.path == "/api/status":
                    self._json(outer.status())
                elif parsed.path == "/api/stats":
                    self._json(outer.history.stats())
                elif parsed.path == "/api/history":
                    q = parse_qs(parsed.query).get("q", [""])[0]
                    self._json([
                        {
                            "id": e.id,
                            "ts": e.ts,
                            "text": e.text,
                            "app": e.app_name,
                            "chars": e.chars,
                            "words": e.words,
                            "seconds": e.seconds,
                        }
                        for e in outer.history.entries(search=q)
                    ])
                elif parsed.path == "/api/replacements":
                    self._json([
                        {"id": r.id, "spoken": r.spoken, "written": r.written}
                        for r in outer.history.replacements()
                    ])
                else:
                    self._json({"error": "not found"}, 404)

            def end_headers(self) -> None:
                # a request line too broken to parse never sets self.path, and
                # BaseHTTPRequestHandler still ends up here sending its 400
                if getattr(self, "path", "").split("?")[0] == "/":
                    self.send_header("Content-Security-Policy", CSP)
                super().end_headers()

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if not self._allowed(parsed.query):
                    return
                data = self._body()
                if data is None:
                    return
                path = parsed.path
                if path == "/api/delete":
                    entry_id = self._entry_id(data)
                    if entry_id is None:
                        return
                    outer.history.delete(entry_id)
                    self._json({"ok": True})
                elif path == "/api/clear":
                    outer.history.clear()
                    self._json({"ok": True})
                elif path == "/api/replacements/add":
                    spoken = str(data.get("spoken", "")).strip()
                    written = str(data.get("written", "")).strip()
                    if not spoken or not written:
                        self._json({"error": "both fields are required"}, 400)
                        return
                    r = outer.history.add_replacement(spoken, written)
                    self._json({"ok": True, "id": r.id})
                elif path == "/api/replacements/delete":
                    entry_id = self._entry_id(data)
                    if entry_id is None:
                        return
                    outer.history.delete_replacement(entry_id)
                    self._json({"ok": True})
                elif path == "/api/open":
                    if outer.on_open:
                        outer.on_open()
                    self._json({"ok": outer.on_open is not None})
                else:
                    self._json({"error": "not found"}, 404)

        return Handler
