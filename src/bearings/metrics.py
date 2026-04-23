"""Prometheus collectors for Bearings.

One shared ``CollectorRegistry`` so `/metrics` emits only the metrics we
own (not the default Python process collectors). All instrumentation
lives at the route / WS-handler boundary — the store and agent layers
stay side-effect-free.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge

REGISTRY = CollectorRegistry()

sessions_created = Counter(
    "bearings_sessions_created_total",
    "Number of sessions created via POST /api/sessions.",
    registry=REGISTRY,
)

messages_persisted = Counter(
    "bearings_messages_persisted_total",
    "Number of messages written to the database, by role.",
    ["role"],
    registry=REGISTRY,
)

tool_calls_started = Counter(
    "bearings_tool_calls_started_total",
    "Number of tool calls begun (ToolCallStart events).",
    registry=REGISTRY,
)

tool_calls_finished = Counter(
    "bearings_tool_calls_finished_total",
    "Number of tool calls completed, labeled by success.",
    ["ok"],
    registry=REGISTRY,
)

ws_active_connections = Gauge(
    "bearings_ws_active_connections",
    "Currently connected agent WebSockets.",
    registry=REGISTRY,
)

ws_events_sent = Counter(
    "bearings_ws_events_sent_total",
    "AgentEvent frames sent to clients, by type.",
    ["type"],
    registry=REGISTRY,
)

# Slice 7 of the Session Reorg plan
# (`~/.claude/plans/sparkling-triaging-otter.md`). One label per op so
# move/split/merge volume can be compared independently. Incremented in
# `routes_reorg.py` after the route commits; a failed op (400/404 or a
# raised exception) never bumps the counter.
session_reorg_total = Counter(
    "bearings_session_reorg_total",
    "Session reorg operations completed, by op type.",
    ["op"],
    registry=REGISTRY,
)

# Phase 7 of docs/context-menu-plan.md. Checkpoints are the primitive
# behind "fork from here" — one counter for the anchor creation path
# (POST /checkpoints) and one for the branch creation path (POST
# /checkpoints/{id}/fork). A successful fork also bumps sessions_created
# above so the session-creation tally remains complete across all paths.
checkpoints_created = Counter(
    "bearings_checkpoints_created_total",
    "Number of checkpoints created via POST /checkpoints.",
    registry=REGISTRY,
)

checkpoints_forked = Counter(
    "bearings_checkpoints_forked_total",
    "Number of session forks spawned from a checkpoint anchor.",
    registry=REGISTRY,
)

# Phase 8 of docs/context-menu-plan.md. PATCH /messages/{id} toggles one
# of two flags — `pinned` (UX only) or `hidden_from_context` (filtered out
# of the next-turn prompt). One label per flag so operators can tell which
# affordance is getting exercised. Only successful toggles bump; 404s and
# no-op patches (body with every field unset) do not.
message_flag_toggles = Counter(
    "bearings_message_flag_toggles_total",
    "Message flag toggles via PATCH /messages/{id}, by flag name.",
    ["flag"],
    registry=REGISTRY,
)

# Phase 9a of docs/context-menu-plan.md. POST /sessions/bulk dispatches
# one of five ops (tag/untag/close/delete/export); one label per op so
# the operator can tell at a glance which of the bulk affordances the
# UI actually drives. Bumped once per request — the per-id success /
# failure split isn't sampled here, only the op volume. A 400 on bad
# payload or unknown op does not bump.
sessions_bulk_ops = Counter(
    "bearings_sessions_bulk_ops_total",
    "POST /sessions/bulk requests, by op type.",
    ["op"],
    registry=REGISTRY,
)

# Phase 9b of docs/context-menu-plan.md. Template CRUD + instantiation.
# `templates_created` bumps on POST /templates; `templates_instantiated`
# bumps on every successful POST /sessions/from_template/{id}. The
# instantiate counter feeds "is anyone actually using templates?" health
# monitoring without requiring the frontend to emit a separate event.
templates_created = Counter(
    "bearings_templates_created_total",
    "Session templates created via POST /templates.",
    registry=REGISTRY,
)

templates_instantiated = Counter(
    "bearings_templates_instantiated_total",
    "Sessions spawned from a saved template.",
    registry=REGISTRY,
)
