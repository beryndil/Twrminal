"""Liveness probe.

GET /api/health is the one route that does NOT require auth. Two reasons:

1. Operators (or load balancers, once §11 ships multi-device) need a
   way to confirm the server is up without minting and shipping a
   token to every probe.
2. Humans verifying the install ("did the daemon start?") shouldn't
   have to set ``X-Bearings-Token`` just to learn the answer is yes.

The route returns the package version so a deployed instance can be
identified at a glance.
"""

from fastapi import APIRouter

from bearings import __version__

router = APIRouter(tags=["health"])


@router.get("/api/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Return ``{"status": "ok", "version": <package version>}``.

    Intentionally cheap: no DB roundtrip, no auth, no I/O. The §13
    distribution work will add a deeper ``/api/ready`` if needed
    (DB reachable, migrations current, etc.).
    """
    return {"status": "ok", "version": __version__}
