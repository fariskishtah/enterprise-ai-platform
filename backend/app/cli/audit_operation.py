"""Record one safe, tenant-wide operational audit event."""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.config.settings import get_settings
from app.db.session import build_session_factory
from app.models.manufacturing import Company
from app.models.user import AuditEvent

_ALLOWED_ACTIONS = {"backup.executed", "restore.validation_executed"}
_ALLOWED_RESULTS = {"failure", "success"}


async def _record(action: str, result: str, operation_id: str) -> None:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    async with session_factory() as session:
        company_ids = list((await session.scalars(select(Company.id))).all())
        for company_id in company_ids:
            session.add(
                AuditEvent(
                    company_id=company_id,
                    actor_user_id=None,
                    actor_role=None,
                    action=action,
                    resource_type=(
                        "backup" if action.startswith("backup") else "restore"
                    ),
                    resource_id=operation_id[:128],
                    result=result,
                    safe_metadata={"source": "operations_cli"},
                    retention_class="security",
                )
            )
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=sorted(_ALLOWED_ACTIONS))
    parser.add_argument("result", choices=sorted(_ALLOWED_RESULTS))
    parser.add_argument("operation_id")
    arguments = parser.parse_args()
    asyncio.run(_record(arguments.action, arguments.result, arguments.operation_id))


if __name__ == "__main__":
    main()
