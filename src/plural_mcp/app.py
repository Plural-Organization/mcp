from typing import Final

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from plural_mcp.hosts import MIN_SECRET_CHARS, Hosts
from plural_mcp.mcp import answer

MAX_BODY_BYTES: Final = 256 * 1024


def create_app(hosts: Hosts | None = None) -> Starlette:
    hosts = hosts or Hosts()

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def metrics(_: Request) -> JSONResponse:
        return JSONResponse({"hosts": hosts.count})

    async def mcp(request: Request) -> Response:
        """The address a chat service is connected to: /i/<secret>."""
        secret = str(request.path_params["secret"])
        if len(secret) < MIN_SECRET_CHARS:
            return JSONResponse({"error": "not found"}, 404)
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY_BYTES:
                return JSONResponse({"error": "too large"}, 413)

        async def deliver(source: str, title: str, context: str) -> tuple[bool, str]:
            return await hosts.offer(secret, source, title, context)

        status, reply = await answer(bytes(body), deliver)
        return JSONResponse(reply, status) if reply is not None else Response(status_code=status)

    async def not_allowed(_: Request) -> Response:
        return Response(status_code=405, headers={"allow": "POST"})

    async def host_socket(socket: WebSocket) -> None:
        await hosts.serve(socket)

    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/metrics", metrics),
            Route("/i/{secret}", mcp, methods=["POST"]),
            Route("/i/{secret}", not_allowed, methods=["GET", "DELETE"]),
            WebSocketRoute("/host", host_socket),
        ]
    )
