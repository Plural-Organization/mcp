"""The MCP side: what a chat service (Claude, ChatGPT, Grok) sees when it is connected."""

import json
from collections.abc import Awaitable, Callable
from typing import Any, Final, cast

from plural_mcp import __version__

TOOL: Final = "add_data_to_session"
PROTOCOLS: Final = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_CONTEXT_CHARS: Final = 20_000
LABEL_CHARS: Final = 40

DESCRIPTION: Final = (
    "Send the context of this conversation to the Plural session it is connected to, so the people "
    "there can carry on the work. Write it as a hand-over note and pass it as `context`: the goal, "
    "what was decided, where things stand, what is left, the files, commands and names that "
    "matter, and the last few messages nearly word for word. Leave out passwords, keys and tokens. "
    "Keep it under 15000 characters. The host of the session sees it first and may decline."
)

SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "context": {
            "type": "string",
            "description": "The hand-over note, as plain text or markdown.",
            "minLength": 1,
            "maxLength": MAX_CONTEXT_CHARS,
        },
        "title": {
            "type": "string",
            "description": "A short title for the topic of the conversation.",
            "maxLength": 80,
        },
        "source": {
            "type": "string",
            "description": "Which assistant sends this, for example Claude or ChatGPT.",
            "maxLength": LABEL_CHARS,
        },
    },
    "required": ["context"],
    "additionalProperties": False,
}

# What a tool call asks of the host: (source, title, context) -> (accepted, why not)
Deliver = Callable[[str, str, str], Awaitable[tuple[bool, str]]]


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text(message: str, *, failed: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": failed}


def label(text: str, fallback: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " .@#-_" else " " for c in text)
    cleaned = " ".join(cleaned.split())[:LABEL_CHARS].strip()
    return cleaned if cleaned and cleaned[0].isalnum() else fallback


async def answer(raw: bytes, deliver: Deliver) -> tuple[int, Any]:
    """Answer one JSON-RPC body (a request, a notification or a batch): a status and JSON."""
    try:
        message = json.loads(raw)
    except ValueError:
        return 400, error(None, -32700, "parse error")
    items = cast(list[Any], message) if isinstance(message, list) else [message]
    answers = [reply for item in items if (reply := await _one(item, deliver)) is not None]
    if not answers:
        return 202, None
    return 200, answers if isinstance(message, list) else answers[0]


async def _one(item: Any, deliver: Deliver) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return error(None, -32600, "invalid request")
    request = cast(dict[str, Any], item)
    if "id" not in request:
        return None
    request_id = request["id"]
    raw_params = request.get("params")
    params = cast(dict[str, Any], raw_params) if isinstance(raw_params, dict) else {}
    match request.get("method"):
        case "initialize":
            wanted = params.get("protocolVersion")
            return _result(
                request_id,
                {
                    "protocolVersion": wanted if wanted in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "plural", "version": __version__},
                },
            )
        case "ping":
            return _result(request_id, {})
        case "tools/list":
            tool = {"name": TOOL, "description": DESCRIPTION, "inputSchema": SCHEMA}
            return _result(request_id, {"tools": [tool]})
        case "tools/call":
            return _result(request_id, await _call(params, deliver))
        case _:
            return error(request_id, -32601, "method not found")


async def _call(params: dict[str, Any], deliver: Deliver) -> dict[str, Any]:
    if params.get("name") != TOOL:
        return _text(f"there is no tool {params.get('name')!r}", failed=True)
    raw_arguments = params.get("arguments")
    arguments = cast(dict[str, Any], raw_arguments) if isinstance(raw_arguments, dict) else {}
    context = arguments.get("context")
    if not isinstance(context, str) or not context.strip():
        return _text("`context` is missing: pass the hand-over note as text", failed=True)
    if len(context) > MAX_CONTEXT_CHARS:
        return _text(
            f"the note is {len(context)} characters and the limit is {MAX_CONTEXT_CHARS}. "
            "Write a shorter one and call the tool again",
            failed=True,
        )
    source = label(str(arguments.get("source") or ""), "Chat")
    title = label(str(arguments.get("title") or ""), "untitled")
    accepted, why = await deliver(source, title, context.strip())
    if accepted:
        return _text("Added to the Plural session. Its agent will read it.")
    return _text(why, failed=True)
