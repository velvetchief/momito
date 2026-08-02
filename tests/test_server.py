"""Dashboard server tests, mostly about who is allowed to talk to it.

The API hands out every transcript the user has ever dictated and accepts
dictionary writes that rewrite all future ones. Any web page the user has open
can reach 127.0.0.1, so these checks are the whole boundary.
"""

import http.client
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

import pytest

from momito.history import History
from momito.server import MAX_BODY, TOKEN_HEADER, DashboardServer


class Client:
    def __init__(self, server: DashboardServer) -> None:
        self.server = server

    def __call__(
        self,
        path: str = "/api/status",
        method: str = "GET",
        body: Optional[bytes] = None,
        token: Optional[str] = "valid",
        host: Optional[str] = None,
        origin: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, bytes, Dict[str, str]]:
        port = self.server.port
        sent: Dict[str, str] = {"Host": host if host is not None else f"127.0.0.1:{port}"}
        if token == "valid":
            sent[TOKEN_HEADER] = self.server.token
        elif token is not None:
            sent[TOKEN_HEADER] = token
        if origin is not None:
            sent["Origin"] = origin
        sent.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=sent)
            resp = conn.getresponse()
            return resp.status, resp.read(), dict(resp.getheaders())
        finally:
            conn.close()

    def json(self, path: str, **kw: Any) -> Any:
        status, body, _ = self(path, **kw)
        assert status == 200, (status, body)
        return json.loads(body)


@pytest.fixture()
def store(tmp_path: Path) -> History:
    return History(db_path=tmp_path / "history.db")


@pytest.fixture()
def server(store: History) -> Iterator[DashboardServer]:
    srv = DashboardServer(store, lambda: {"app": "momito", "state": "idle"})
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture()
def get(server: DashboardServer) -> Client:
    return Client(server)


# --- the token ---


def test_valid_token_is_let_through(get: Client) -> None:
    assert get.json("/api/status")["app"] == "momito"


def test_no_token_is_unauthorized(get: Client) -> None:
    status, _, _ = get("/api/status", token=None)
    assert status == 401


def test_wrong_token_is_unauthorized(get: Client) -> None:
    status, _, _ = get("/api/status", token="guessed-it")
    assert status == 401


def test_token_may_arrive_in_the_query_string(get: Client, server: DashboardServer) -> None:
    """The page itself is loaded by URL, before any JS can set a header."""
    status, body, _ = get(f"/?t={server.token}", token=None)
    assert status == 200
    assert b"Momito" in body


def test_writes_need_the_token_too(get: Client, store: History) -> None:
    status, _, _ = get(
        "/api/replacements/add",
        method="POST",
        body=b'{"spoken": "evil", "written": "rm -rf /"}',
        token=None,
    )
    assert status == 401
    assert store.replacement_pairs() == []


# --- Host and Origin ---


def test_foreign_host_header_is_forbidden(get: Client, server: DashboardServer) -> None:
    """This is the DNS rebinding case: the browser sends the attacker's name."""
    status, _, _ = get("/api/status", host=f"evil.example.com:{server.port}")
    assert status == 403


def test_wrong_port_in_host_is_forbidden(get: Client, server: DashboardServer) -> None:
    status, _, _ = get("/api/status", host=f"127.0.0.1:{server.port + 1}")
    assert status == 403


def test_localhost_host_is_fine(get: Client, server: DashboardServer) -> None:
    status, _, _ = get("/api/status", host=f"localhost:{server.port}")
    assert status == 200


def test_cross_origin_is_forbidden(get: Client) -> None:
    status, _, _ = get("/api/status", origin="http://evil.example.com")
    assert status == 403


def test_cross_origin_is_forbidden_even_with_the_token(get: Client, server: DashboardServer) -> None:
    status, _, _ = get(
        "/api/replacements/add",
        method="POST",
        body=b'{"spoken": "a", "written": "b"}',
        origin="https://evil.example.com",
    )
    assert status == 403


def test_our_own_origin_is_fine(get: Client, server: DashboardServer) -> None:
    status, _, _ = get("/api/status", origin=server.origin)
    assert status == 200


def test_host_is_checked_before_the_token(get: Client, server: DashboardServer) -> None:
    status, _, _ = get("/api/status", host="evil.example.com", token=None)
    assert status == 403


# --- bodies ---


def test_malformed_json_is_a_400_not_a_crash(get: Client) -> None:
    status, body, _ = get("/api/delete", method="POST", body=b"{not json")
    assert status == 400
    assert json.loads(body)["error"] == "malformed json"


def test_json_that_is_not_an_object_is_a_400(get: Client) -> None:
    status, body, _ = get("/api/delete", method="POST", body=b"[1,2,3]")
    assert status == 400


def test_oversized_body_is_rejected_before_it_is_read(get: Client) -> None:
    status, body, _ = get(
        "/api/delete",
        method="POST",
        headers={"Content-Length": str(MAX_BODY + 1)},
    )
    assert status == 413


def test_unparseable_content_length_is_a_400(get: Client) -> None:
    status, _, _ = get("/api/delete", method="POST", headers={"Content-Length": "twelve"})
    assert status == 400


def test_non_numeric_id_is_a_400(get: Client) -> None:
    status, body, _ = get("/api/delete", method="POST", body=b'{"id": "abc"}')
    assert status == 400
    assert json.loads(body)["error"] == "id must be a number"


def test_missing_id_is_a_400(get: Client) -> None:
    status, _, _ = get("/api/delete", method="POST", body=b"{}")
    assert status == 400


def test_replacement_needs_both_fields(get: Client) -> None:
    status, _, _ = get(
        "/api/replacements/add", method="POST", body=b'{"spoken": "  ", "written": "x"}'
    )
    assert status == 400


def test_a_rejected_post_hangs_up_instead_of_desyncing(server: DashboardServer) -> None:
    """401, 403 and 413 are all answered without reading the request body, so
    those bytes are still sitting in the socket. On a keep-alive connection the
    next request would start reading mid-body, so the server has to close."""
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request(
            "POST",
            "/api/delete",
            body=b'{"id": 1}',
            headers={"Host": f"127.0.0.1:{server.port}"},  # no token
        )
        resp = conn.getresponse()
        assert resp.status == 401
        resp.read()
        assert resp.will_close
    finally:
        conn.close()


def test_a_successful_response_keeps_the_connection(get: Client) -> None:
    _, _, headers = get("/api/status")
    assert headers.get("Connection", "keep-alive") != "close"


# --- the API actually working ---


def test_history_round_trip(get: Client, store: History) -> None:
    store.add("hello there world", app_name="Notes", seconds=2.0)
    entries = get.json("/api/history")
    assert len(entries) == 1
    assert entries[0]["text"] == "hello there world"
    assert entries[0]["app"] == "Notes"
    assert entries[0]["words"] == 3
    assert entries[0]["chars"] == 17


def test_history_search(get: Client, store: History) -> None:
    store.add("buy schnauzer treats")
    store.add("meeting at noon")
    assert len(get.json("/api/history?q=schnauzer")) == 1


def test_delete_removes_the_entry(get: Client, store: History) -> None:
    entry = store.add("delete me")
    status, _, _ = get("/api/delete", method="POST", body=json.dumps({"id": entry.id}).encode())
    assert status == 200
    assert store.entries() == []


def test_clear_empties_history(get: Client, store: History) -> None:
    store.add("one")
    status, _, _ = get("/api/clear", method="POST", body=b"{}")
    assert status == 200
    assert store.entries() == []


def test_replacements_add_and_delete(get: Client, store: History) -> None:
    status, body, _ = get(
        "/api/replacements/add", method="POST", body=b'{"spoken": "teh", "written": "the"}'
    )
    assert status == 200
    new_id = json.loads(body)["id"]
    assert store.replacement_pairs() == [("teh", "the")]
    get("/api/replacements/delete", method="POST", body=json.dumps({"id": new_id}).encode())
    assert store.replacement_pairs() == []


def test_open_reports_whether_a_window_exists(store: History) -> None:
    opened = []
    srv = DashboardServer(store, lambda: {"app": "momito"}, on_open=lambda: opened.append(1))
    srv.start()
    try:
        status, body, _ = Client(srv)("/api/open", method="POST", body=b"{}")
        assert status == 200 and json.loads(body)["ok"] is True
        assert opened == [1]
    finally:
        srv.stop()


def test_unknown_paths_are_404(get: Client) -> None:
    assert get("/api/nope")[0] == 404
    assert get("/api/nope", method="POST", body=b"{}")[0] == 404


# --- headers ---


def test_security_headers_on_every_response(get: Client) -> None:
    _, _, headers = get("/api/status")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_csp_on_the_page_only(get: Client, server: DashboardServer) -> None:
    _, _, page = get(f"/?t={server.token}", token=None)
    assert "default-src 'none'" in page["Content-Security-Policy"]
    _, _, api = get("/api/status")
    assert "Content-Security-Policy" not in api


def test_each_launch_gets_a_fresh_token(store: History) -> None:
    a = DashboardServer(store, lambda: {})
    b = DashboardServer(store, lambda: {})
    assert a.token != b.token
    assert len(a.token) >= 24
