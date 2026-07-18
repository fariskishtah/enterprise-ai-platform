"""Administrative command for pending promotion-audit reconciliation."""

import asyncio

from app.config.settings import get_settings
from app.db.session import build_session_factory
from app.ml.composition import create_ai_model_registry
from app.ml.promotion.service import PromotionAuditReconciliationService
from app.repositories.ai_governance import ModelPromotionAuditRepository


async def _reconcile() -> tuple[tuple[str, str], ...]:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    registry = create_ai_model_registry(settings)
    async with session_factory() as session:
        result = await PromotionAuditReconciliationService(
            audit_repository=ModelPromotionAuditRepository(session),
            model_registry=registry,
            pending_after_seconds=settings.promotion_audit_pending_after_seconds,
        ).reconcile()
    return tuple(
        [("succeeded", str(audit_id)) for audit_id in result.succeeded]
        + [("conflict", str(audit_id)) for audit_id in result.conflicted]
        + [
            ("registry_unavailable", str(audit_id))
            for audit_id in result.registry_unavailable
        ],
    )


def main() -> None:
    """Report stable pending-audit reconciliation outcomes without SDK details."""
    for outcome, audit_id in asyncio.run(_reconcile()):
        print(f"{outcome} {audit_id}")


if __name__ == "__main__":
    main()
