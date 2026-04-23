"""Bearer-token auth for the REST and WebSocket surfaces.

Opt-in: `auth.enabled = true` + `auth.token = "..."` in config.toml.
Otherwise the server stays open (matches v0.1.0 behavior). Both
`/api/sessions*` and `/api/history*` require the token; `/api/health`
and `/metrics` stay open so ops/monitoring can probe without creds.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket, status


def _configured_token(request: Request | WebSocket) -> str | None:
    settings = request.app.state.settings
    if not settings.auth.enabled:
        return None
    token: str | None = settings.auth.token
    if not token:
        # Enabled without a token is a config error; fail closed so
        # nobody thinks auth is on while the server is actually open.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="auth.enabled is true but auth.token is empty",
        )
    return token


def require_auth(request: Request) -> None:
    expected = _configured_token(request)
    if expected is None:
        return
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or presented != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def check_ws_auth(websocket: WebSocket) -> bool:
    """True if the WS request passes auth. Caller is responsible for
    closing the socket with 4401 on False."""
    settings = websocket.app.state.settings
    if not settings.auth.enabled:
        return True
    expected: str | None = settings.auth.token
    if not expected:
        return False
    presented = str(websocket.query_params.get("token", ""))
    return presented == expected


def _allowed_origins(websocket: WebSocket) -> set[str]:
    """Compute the effective allowlist for this request.

    Loopback defaults are derived from `server.port` so a user who
    flips the port doesn't lose their own UI. `server.allowed_origins`
    is merged in to support custom local deployments (Vite dev server,
    reverse proxies). Built per-request rather than cached because
    config changes (admin UI reloads) can change the port without a
    server restart.
    """
    settings = websocket.app.state.settings
    port = settings.server.port
    origins = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://[::1]:{port}",
    }
    origins.update(settings.server.allowed_origins)
    return origins


def check_ws_origin(websocket: WebSocket) -> bool:
    """True if the WS handshake's `Origin` header is allowlisted.

    Mitigates cross-origin agent hijacking: without this, any tab in
    the same browser (including attacker pages served by another
    localhost process) could open the Bearings WS and drive the agent.
    Browsers always send `Origin` on WebSocket upgrades, so a missing
    header fails closed — non-browser clients that need access can set
    `Origin` explicitly to a value in `server.allowed_origins`.

    Caller is responsible for closing the socket with 4403 on False.
    """
    origin = websocket.headers.get("origin")
    if origin is None:
        return False
    return origin in _allowed_origins(websocket)
