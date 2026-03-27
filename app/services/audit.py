"""
Audit log service - append-only event logging for all state mutations.
"""

from app.db import get_db
from app.utils.helpers import make_id, now_iso, json_dumps


def log_event(
    entity_type: str,
    entity_id: str,
    event: str,
    actor_type: str,
    actor_id: str,
    old_state: dict = None,
    new_state: dict = None,
    metadata: dict = None,
    service: str = None,
    trace_id: str = None,
):
    """Write an immutable audit log entry."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO audit_log
               (audit_id, entity_type, entity_id, event, old_state, new_state,
                actor_type, actor_id, metadata, timestamp, service, trace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                make_id("aud_"),
                entity_type,
                entity_id,
                event,
                json_dumps(old_state) if old_state else None,
                json_dumps(new_state) if new_state else None,
                actor_type,
                actor_id,
                json_dumps(metadata or {}),
                now_iso(),
                service,
                trace_id,
            ),
        )
