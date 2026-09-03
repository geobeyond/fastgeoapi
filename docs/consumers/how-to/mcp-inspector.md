---
icon: material/magnify
---

# :material-magnify: Verifying with the MCP Inspector

The [MCP Inspector](https://modelcontextprotocol.io/docs/2026-07-28/tools/inspector)
is the reference tool for testing MCP servers, maintained by the protocol
project itself. That makes it the most neutral check available for this
server: it exercises the same discovery, OAuth and protocol negotiation
any conformant client would, with none of our code involved on the
client side.

Everything on this page was run against the live deployment before being
written down.

## Requirements

- **Node 22.19.0 or newer** — older versions print `EBADENGINE` warnings
  and may misbehave.
- Use `@latest` explicitly. A bare
  `npx @modelcontextprotocol/inspector` can resolve a cached **v1**,
  which has different flags (it fails with _"Arguments cannot be passed
  to a URL-based MCP server"_) and receives security fixes only.

## Browser UI

```bash
npx -y @modelcontextprotocol/inspector@latest \
  --server-url https://fastgeoapi.fly.dev/mcp/ --transport http
```

The command prints a URL with a one-time session token; open it, and the
Inspector runs the OAuth flow when the server answers its first `401`:

1. it follows the `WWW-Authenticate` challenge to our protected-resource
   metadata (RFC 9728), then to the authorization-server metadata
   (RFC 8414);
2. it registers itself through **dynamic client registration** — no
   pre-configuration on our side, which is itself part of what is being
   verified;
3. the browser lands on the upstream identity provider's login page.
   **This is correct behaviour**: the Inspector talks only to our
   embedded authorization server, which fronts the IdP. Sign in with the
   credentials you were given;
4. after the callback, the Connection Info panel shows the registered
   client, the granted scopes and the token state — and the tools tab
   lists the generated OGC API tools.

## Command line

The CLI is the same client without the browser chrome, useful for quick
checks and scripting. The first call needs the interactive OAuth dance
(it opens your browser, callback on `http://127.0.0.1:6276/oauth/callback`):

```bash
npx -y @modelcontextprotocol/inspector@latest --cli \
  https://fastgeoapi.fly.dev/mcp/ --transport http \
  --method tools/list
```

Later calls reuse the login automatically — the token lives in
`~/.mcp-inspector/storage/oauth.json` and the same command finds it, so
no browser opens the second time:

```bash
npx -y @modelcontextprotocol/inspector@latest --cli \
  https://fastgeoapi.fly.dev/mcp/ --transport http \
  --method tools/call --tool-name getLandingPage --tool-arg f=json
```

To discard the stored login and start over, add `--relogin`.

!!! warning "`--use-stored-auth` does not work in Inspector 2.2.0"

    The upstream documentation suggests `--use-stored-auth` for reusing a
    stored login. As of 2.2.0 it fails with a self-contradictory
    `no_stored_token` error that lists the very server it claims not to
    find: the flag's lookup reads tokens from a legacy location in the
    state file, while the CLI's own OAuth flow stores them under a newer
    per-issuer shape. You do not need the flag against this server —
    plain re-runs (above) and `--stored-auth-only` (below) both read the
    store correctly.

### In CI, or anywhere non-interactive

```bash
npx -y @modelcontextprotocol/inspector@latest --cli \
  https://fastgeoapi.fly.dev/mcp/ --transport http \
  --stored-auth-only --method tools/list
```

`--stored-auth-only` never opens a browser: with a stored token it lists
the tools; without one it fails fast with
`{"error":{"code":"auth_required"}}` — against this server that answer
comes back in about a second, and it doubles as a cheap probe that the
discovery chain (`401` → PRM → AS metadata) is intact. Both outcomes
were exercised against the live deployment.

## What to expect from this server

| Behaviour                                                                                  | Why                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| First request answers `401` with a `WWW-Authenticate` challenge                            | RFC 6750 semantics; this is what triggers the Inspector's OAuth flow                                                                                                        |
| Login page belongs to the upstream IdP, not to fastgeoapi                                  | The embedded authorization server proxies any OIDC provider; the client never sees it directly                                                                              |
| Both protocol eras work                                                                    | The server negotiates the sessionless `2026-07-28` protocol and the legacy `initialize` handshake down to `2024-11-05`, so the Inspector's era toggle is a useful A/B check |
| The connection appears in our logs as `client=inspector-cli version=2.2.0` at `initialize` | The server records the identity a client declares; on the legacy handshake it is visible at connection time only                                                            |
| Each CLI login registers a fresh DCR client                                                | Registrations are dynamic and persisted server-side; harmless, but worth knowing when reading the server's client store                                                     |

## Authorization codes are short-lived

If you pause on the IdP login page long enough, the exchange fails with
`invalid_grant` — the authorization code expired between the callback
and the token request. This is deliberate server behaviour, not a
defect. Re-run the flow and complete the login without stopping.

Note the status code: this server currently answers `401` for
`invalid_grant`, where RFC 6749 §5.2 specifies `400`. Read the JSON
body's `error` field rather than branching on the status — a fix is
tracked upstream.
