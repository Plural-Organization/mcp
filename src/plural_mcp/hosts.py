"""The hosts that are connected to the gateway, found by their secret."""

import asyncio
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Any, Final, cast

from starlette.websockets import WebSocket, WebSocketDisconnect

MIN_SECRET_CHARS: Final = 20
ANSWER_TIMEOUT_S: Final = 110.0
MAX_OPEN_OFFERS: Final = 4

OFFLINE: Final = "Plural is not running on the other side. Start it and try again."
BUSY: Final = "Plural is still looking at an earlier message. Try again in a minute."
SLOW: Final = "The host did not answer in time, so nothing was added."
DECLINED: Final = "The host did not accept it, so nothing was added."


def _object(text: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(text)
    except ValueError:
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def key_of(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass(slots=True)
class Link:
    socket: WebSocket
    open: dict[str, asyncio.Future[bool]] = field(default_factory=dict[str, asyncio.Future[bool]])


class Hosts:
    def __init__(self, *, answer_timeout_s: float = ANSWER_TIMEOUT_S) -> None:
        self._links: dict[str, Link] = {}
        self._timeout = answer_timeout_s

    @property
    def count(self) -> int:
        return len(self._links)

    async def offer(self, secret: str, source: str, title: str, context: str) -> tuple[bool, str]:
        """Put a chat's context in front of the host with this secret and wait for its answer."""
        link = self._links.get(key_of(secret))
        if link is None:
            return False, OFFLINE
        if len(link.open) >= MAX_OPEN_OFFERS:
            return False, BUSY
        offer_id = secrets.token_hex(8)
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        link.open[offer_id] = future
        message = {
            "type": "offer",
            "id": offer_id,
            "source": source,
            "title": title,
            "context": context,
        }
        try:
            await link.socket.send_text(json.dumps(message))
            accepted = await asyncio.wait_for(future, self._timeout)
        except TimeoutError:
            return False, SLOW
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            return False, OFFLINE
        finally:
            link.open.pop(offer_id, None)
        return (True, "") if accepted else (False, DECLINED)

    async def serve(self, socket: WebSocket) -> None:
        """A host connects, says which secret it answers for, and then answers offers."""
        await socket.accept()
        try:
            hello = _object(await asyncio.wait_for(socket.receive_text(), 10.0))
        except (TimeoutError, WebSocketDisconnect):
            await socket.close(1008)
            return
        secret = hello.get("secret")
        if hello.get("type") != "hello" or not isinstance(secret, str):
            await socket.close(1008)
            return
        if len(secret) < MIN_SECRET_CHARS:
            await socket.close(1008)
            return
        key = key_of(secret)
        link = Link(socket)
        previous = self._links.get(key)
        self._links[key] = link
        if previous is not None:
            await previous.socket.close(1000)
        await socket.send_text(json.dumps({"type": "ready"}))
        try:
            while True:
                message = _object(await socket.receive_text())
                waiting = link.open.get(str(message.get("id")))
                if waiting is not None and not waiting.done():
                    waiting.set_result(message.get("accepted") is True)
        except WebSocketDisconnect:
            pass
        finally:
            if self._links.get(key) is link:
                del self._links[key]
            for waiting in link.open.values():
                if not waiting.done():
                    waiting.cancel()
