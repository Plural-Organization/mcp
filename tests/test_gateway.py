# pyright: basic
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn
import websockets
from starlette.testclient import TestClient

from plural_mcp.app import create_app
from plural_mcp.hosts import DECLINED, OFFLINE, Hosts
from plural_mcp.mcp import TOOL

SECRET = "s" * 32
URL = f"/i/{SECRET}"
NOTE = "Goal: move the billing page to the new API. Left: the invoice PDF."


def rpc(method: str, **params: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


def call(**arguments: Any) -> dict[str, Any]:
    return rpc("tools/call", name=TOOL, arguments=arguments)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Hosts(answer_timeout_s=2.0)))


def test_it_introduces_itself_in_the_version_the_client_asks_for(client: TestClient) -> None:
    reply = client.post(URL, json=rpc("initialize", protocolVersion="2025-03-26"))
    assert reply.status_code == 200
    assert reply.json()["result"]["protocolVersion"] == "2025-03-26"
    newer = client.post(URL, json=rpc("initialize", protocolVersion="1999-01-01"))
    assert newer.json()["result"]["protocolVersion"] == "2025-06-18"


def test_it_lists_its_one_tool_even_when_no_host_is_connected(client: TestClient) -> None:
    reply = client.post(URL, json=rpc("tools/list"))
    assert [tool["name"] for tool in reply.json()["result"]["tools"]] == [TOOL]


def test_a_notification_gets_no_body_and_a_batch_gets_a_list(client: TestClient) -> None:
    note = client.post(URL, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202
    batch = client.post(URL, json=[rpc("ping"), rpc("tools/list")])
    assert len(batch.json()) == 2


def test_an_unknown_method_and_bad_json_are_errors(client: TestClient) -> None:
    assert client.post(URL, json=rpc("nope")).json()["error"]["code"] == -32601
    assert client.post(URL, content=b"{not json").status_code == 400


def test_a_short_secret_and_a_get_are_refused(client: TestClient) -> None:
    assert client.post("/i/short", json=rpc("ping")).status_code == 404
    assert client.get(URL).status_code == 405


def test_a_call_with_no_host_connected_says_so(client: TestClient) -> None:
    reply = client.post(URL, json=call(context=NOTE))
    assert reply.json()["result"]["isError"] is True
    assert reply.json()["result"]["content"][0]["text"] == OFFLINE


def test_a_call_without_context_or_over_the_limit_is_an_error_the_model_can_read(
    client: TestClient,
) -> None:
    missing = client.post(URL, json=call(title="x"))
    assert missing.json()["result"]["isError"] is True
    long = client.post(URL, json=call(context="x" * 20_001))
    assert "limit" in long.json()["result"]["content"][0]["text"]


def test_a_body_over_the_limit_is_refused(client: TestClient) -> None:
    assert client.post(URL, content=b"x" * (256 * 1024 + 1)).status_code == 413


@pytest.fixture
async def live() -> AsyncIterator[str]:
    """The gateway on a real port, for the tests that need a host connected over a socket."""
    server = uvicorn.Server(
        uvicorn.Config(create_app(Hosts(answer_timeout_s=5.0)), port=0, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    await task


async def chat_calls(address: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as http:
        reply = await http.post(
            f"http://{address}{URL}",
            json=call(context=NOTE, title="Billing page!", source="Claude"),
        )
    return reply.json()


async def test_the_host_is_asked_and_its_answer_reaches_the_chat(live: str) -> None:
    async with websockets.connect(f"ws://{live}/host") as host:
        await host.send(json.dumps({"type": "hello", "secret": SECRET}))
        assert json.loads(await host.recv())["type"] == "ready"
        for accept in (True, False):
            chat = asyncio.create_task(chat_calls(live))
            offer = json.loads(await host.recv())
            assert offer["type"] == "offer"
            assert offer["context"] == NOTE
            assert offer["source"] == "Claude"
            assert offer["title"] == "Billing page"
            await host.send(json.dumps({"type": "answer", "id": offer["id"], "accepted": accept}))
            result = (await chat)["result"]
            assert result["isError"] is not accept
            if not accept:
                assert result["content"][0]["text"] == DECLINED


async def test_a_host_that_goes_away_leaves_the_chat_with_an_error(live: str) -> None:
    async with websockets.connect(f"ws://{live}/host") as host:
        await host.send(json.dumps({"type": "hello", "secret": SECRET}))
        await host.recv()
    await asyncio.sleep(0.2)
    result = (await chat_calls(live))["result"]
    assert result["content"][0]["text"] == OFFLINE


async def test_a_host_with_a_short_secret_is_turned_away(live: str) -> None:
    async with websockets.connect(f"ws://{live}/host") as host:
        await host.send(json.dumps({"type": "hello", "secret": "short"}))
        with pytest.raises(websockets.ConnectionClosed):
            await host.recv()
