
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_admin_action(
    db: Session,
    admin_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Registra una acción administrativa dentro de la sesión actual.

    La transacción y el commit quedan bajo responsabilidad
    del endpoint que llama a esta función.
    """
    audit_log = AuditLog(
        admin_id=admin_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )

    db.add(audit_log)
    db.flush()

    return audit_log
