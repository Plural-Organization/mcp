# plural-mcp

The MCP gateway of [Plural](https://github.com/Plural-Organization/Plural). A chat service
(Claude, ChatGPT, Grok) is connected to it as a custom connector, and its one tool,
`add_data_to_session`, sends a hand-over note of the chat to a Plural session. The session's host
sees it first and may decline.

```
chat service --HTTPS POST /i/<secret>--> plural-mcp <--WebSocket /host-- Plural host
```

- The host connects out, so it needs no public address. It says which secret it answers for.
- The connector address is `https://<this service>/i/<secret>`. The secret is made by the host and
  never leaves the machine except in that address.
- The gateway keeps nothing. It holds a note only while the host looks at it, never logs bodies,
  and keys hosts by a hash of the secret.
- A host that is not connected gets an error back to the model, not a stored message.

## Run

```
uv sync
uv run plural-mcp          # PORT=8080
uv run pytest && uv run ruff check . && uv run pyright
```

`GET /healthz` for a health check. The wire protocol with the host is three JSON messages:
`{"type":"hello","secret"}` from the host, then `{"type":"offer","id","source","title","context"}`
from the gateway and `{"type":"answer","id","accepted"}` back.
