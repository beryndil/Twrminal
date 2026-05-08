# Deprecation convention

Bearings v1.x uses a three-part marker on any route or query parameter
that is retained for back-compat but will be removed in a future minor
release.

## The three parts

### 1. `deprecated=True` on the FastAPI decorator

```python
@router.get("/api/tag-groups", response_model=list[str], deprecated=True)
```

For query parameters, pass it to `Query()`:

```python
tag_ids: Annotated[list[int] | None, Query(deprecated=True)] = None
```

FastAPI propagates the flag into the generated OpenAPI document
(`"deprecated": true` on the path item or parameter object). Tools
that consume `docs/openapi.json` — including the oasdiff breaking-change
gate — can therefore distinguish intentional deprecations from accidental
removals.

### 2. `x-sunset` OpenAPI extension

Add `openapi_extra={"x-sunset": "<ISO-8601 date or version>"}` to the
route decorator to name the release in which the surface will be removed:

```python
@router.get(
    "/api/tag-groups",
    response_model=list[str],
    deprecated=True,
    openapi_extra={"x-sunset": "v1.2.0"},
)
```

For parameters the extension lives on the route decorator's
`openapi_extra`, not on `Query()` (FastAPI does not forward arbitrary
kwargs from `Query` into the spec).

### 3. `Sunset` response header (deferred to v1.1)

A planned ASGI middleware will read the `x-sunset` value from the
matched route's OpenAPI metadata and emit a `Sunset: <date>` response
header on every response from that endpoint, per
[RFC 8594](https://www.rfc-editor.org/rfc/rfc8594). This gives HTTP
clients a machine-readable signal without requiring them to parse the
spec. Implementation is tracked in `TODO.md` and will ship no later
than the first deprecated surface's removal release.

## Currently deprecated surfaces

| Surface | File | Removed in |
|---|---|---|
| `GET /api/tag-groups` | `src/bearings/web/routes/tags.py` | v1.2.0 |
| `tag_ids` query param on `GET /api/sessions` | `src/bearings/web/routes/sessions.py` | v1.2.0 |

Both carry `deprecated=True`. The `x-sunset` extension and `Sunset`
header middleware land in v1.1.0 (see TODO.md).

## Deprecation lifecycle

1. Mark with `deprecated=True` (+ `x-sunset` once middleware exists) in
   the release that introduces the replacement.
2. Document the migration path in the route's docstring and in the
   relevant `docs/behavior/<subsystem>.md`.
3. Keep the surface working for at least one full minor release.
4. Remove in the release named by `x-sunset`; bump minor version.
