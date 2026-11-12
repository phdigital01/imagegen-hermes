"""The ``local`` provider against a real HTTP server that speaks the OpenAI images API.

The server is ``http.server`` on a loopback port, so the transport runs for real: the request
that leaves, the answers it accepts, and what happens when the server is off.
"""
from __future__ import annotations

import base64
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imagegen_engine import gen_service, host_llm, local_api, plugin_api, providers_catalog, store
from imagegen_engine.capabilities import resolve_capabilities

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_PNG_B64 = base64.b64encode(_PNG).decode()


def _use_address(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    monkeypatch.setattr(host_llm, "setting", lambda key, default=None: address if key == "local_server_url" else default)
    monkeypatch.setattr(local_api, "_cache", {"root": "", "models": [], "at": 0.0, "failed_at": 0.0,
                                              "thread": None, "waited": False})


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Dict[str, Any]:
    """A local image server; ``state["answer"]`` is what the next generation gets."""
    state: Dict[str, Any] = {"posts": [], "headers": [], "status": 200,
                             "answer": {"data": [{"b64_json": _PNG_B64}]}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 — http.server name
            state["headers"].append(dict(self.headers))
            if self.path == "/v1/models":
                self._send(200, json.dumps({"object": "list", "data": [{"id": "sd-test"}, {"id": "flux:test"}]}).encode())
            elif self.path == "/files/out.png":
                self._send(200, _PNG, "image/png")
            else:
                self._send(404, b"{}")

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append((self.path, body))
            self._send(state["status"], json.dumps(state["answer"]).encode())

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["httpd"] = httpd
    state["address"] = f"http://127.0.0.1:{httpd.server_port}"
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    _use_address(monkeypatch, state["address"])
    yield state
    httpd.shutdown()
    httpd.server_close()


def _dead_address() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


def test_generation_sends_model_prompt_and_pixel_size_and_costs_nothing(server: Dict[str, Any]) -> None:
    # Already over the monthly limit: a free local image must still go through.
    store.reserve_spend("fal", "fal-ai/flux-2-pro", 0.5)
    store.set_budget(0.1)

    result = gen_service.generate_text_to_image("local", "flux:test", "a red bicycle", aspect_ratio="16:9")

    assert server["posts"] == [("/v1/images/generations", {
        "model": "flux:test", "prompt": "a red bicycle", "n": 1, "size": "1024x576", "response_format": "b64_json"})]
    assert result["images"] == [f"data:image/png;base64,{_PNG_B64}"]
    assert (result["provider"], result["model"], result["cost_estimate"]) == ("local", "flux:test", 0.0)
    assert store.budget_status()["spentThisMonth"] == 0.5


def test_pixel_size_follows_the_format_in_multiples_of_64() -> None:
    assert local_api.pixel_size("1K", "3:2") == {"width": 1024, "height": 704}
    assert local_api.pixel_size("512px", "3:4") == {"width": 384, "height": 512}
    assert local_api.pixel_size("unknown", "bad") == {"width": 1024, "height": 1024}


def test_an_image_link_is_read_only_from_the_same_server(server: Dict[str, Any]) -> None:
    server["answer"] = {"data": [{"url": "/files/out.png"}]}
    assert local_api.generate("sd-test", "a mug")["images"] == [f"data:image/png;base64,{_PNG_B64}"]

    server["answer"] = {"data": [{"url": "http://elsewhere.invalid/out.png"}]}
    with pytest.raises(RuntimeError) as other_host:
        local_api.generate("sd-test", "a mug")
    assert other_host.value.code == "provider.failed" and "another address" in str(other_host.value)

    server["answer"] = {"data": []}
    with pytest.raises(RuntimeError) as empty:
        local_api.generate("sd-test", "a mug")
    assert empty.value.code == "model.no_image"


def test_a_server_error_names_the_address_and_is_not_sent_again(server: Dict[str, Any]) -> None:
    server["status"], server["answer"] = 500, {"error": {"message": "model not loaded"}}

    with pytest.raises(RuntimeError) as exc_info:
        gen_service.generate_text_to_image("local", "sd-test", "a mug")

    assert exc_info.value.code == "provider.failed"
    assert f"{server['address']} returned HTTP 500: model not loaded" in str(exc_info.value)
    assert len(server["posts"]) == 1


def test_a_server_that_is_off_fails_with_its_address(monkeypatch: pytest.MonkeyPatch) -> None:
    address = _dead_address()
    _use_address(monkeypatch, address)

    with pytest.raises(RuntimeError) as exc_info:
        local_api.generate("sd-test", "a mug")

    assert exc_info.value.code == "provider.failed"
    assert f"Local server at {address} did not answer (connection refused); the request was not sent again" in str(
        exc_info.value)


def test_references_are_refused_and_nothing_is_sent(server: Dict[str, Any]) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        gen_service.generate_text_to_image(
            "local", "sd-test", "a mug", reference_images=[f"data:image/png;base64,{_PNG_B64}"])

    assert exc_info.value.code == "refs.model_unsupported"
    assert server["posts"] == []
    caps = resolve_capabilities("local", "sd-test")
    assert (caps["maxReferences"], caps["referenceImages"], caps["edit"], caps["negativeMode"]) == (0, False, False, "unsupported")


def test_the_token_travels_only_as_a_bearer_header(server: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGEGEN_LOCAL_SERVER_KEY", "local-token")

    assert local_api.fetch_models() == ["sd-test", "flux:test"]

    assert server["headers"][-1].get("Authorization") == "Bearer local-token"


def test_provider_list_carries_the_server_models_and_the_chat_can_use_them(server: Dict[str, Any]) -> None:
    entry = next(p for p in providers_catalog._list_providers() if p["name"] == "local")

    assert (entry["configured"], entry["available"]) == (True, True)
    assert [m["id"] for m in entry["models"]] == ["sd-test", "flux:test"]
    assert entry["models"][0]["resolutionOptions"] == ["512px", "768px", "1K", "2K"]
    assert entry["models"][0]["capabilities"]["maxReferences"] == 0
    # No other provider has a key in this environment: the chat provider lands on the local server.
    assert providers_catalog.resolve_target() == ("local", "sd-test")
    assert providers_catalog.resolve_target("flux:test") == ("local", "flux:test")


def test_no_address_means_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_address(monkeypatch, "")

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a request left without an address")

    monkeypatch.setattr(local_api._opener, "open", refuse)
    entry = next(p for p in providers_catalog._list_providers() if p["name"] == "local")

    assert (entry["configured"], entry["available"], entry["models"]) == (False, False, [])
    with pytest.raises(RuntimeError) as exc_info:
        local_api.generate("sd-test", "a mug")
    assert exc_info.value.code == "provider.unavailable"


def test_routes_do_not_wait_for_a_server_that_is_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    app = FastAPI()
    app.include_router(plugin_api.router)
    with TestClient(app) as client:
        client.get("/providers")  # warm the catalog, with no address yet
        _use_address(monkeypatch, _dead_address())

        started = time.perf_counter()
        providers = client.get("/providers").json()["providers"]
        elapsed = time.perf_counter() - started

        assert elapsed < 0.3
        assert next(p for p in providers if p["name"] == "local")["models"] == []
        started = time.perf_counter()
        status = {row["name"]: row for row in client.get("/providers/status").json()["providers"]}
        assert time.perf_counter() - started < 0.3
        assert (status["local"]["configured"], status["local"]["available"]) == (True, False)
        assert client.post("/providers/test", json={"provider": "local"}).json()["error"] == "unreachable"


def test_connection_test_reports_the_model_count(server: Dict[str, Any]) -> None:
    app = FastAPI()
    app.include_router(plugin_api.router)
    with TestClient(app) as client:
        assert client.post("/providers/test", json={"provider": "local"}).json() == {
            "ok": True, "provider": "local", "models": 2}


def test_a_failed_connection_test_takes_the_server_off_the_list_at_once(server: Dict[str, Any]) -> None:
    app = FastAPI()
    app.include_router(plugin_api.router)
    with TestClient(app) as client:
        def listed() -> bool:
            rows = client.get("/providers/status").json()["providers"]
            return next(row for row in rows if row["name"] == "local")["available"]

        assert listed() is True
        server["httpd"].shutdown()
        server["httpd"].server_close()

        assert client.post("/providers/test", json={"provider": "local"}).json()["error"] == "unreachable"
        # Without this the list kept the server as answering until its next background refresh.
        assert listed() is False
