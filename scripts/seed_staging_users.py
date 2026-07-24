"""Create or reset disposable staging-validation role accounts."""

import asyncio
import os
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import Settings
from app.models.manufacturing import Company
from app.models.user import User, UserRole
from app.utils.passwords import PasswordHasher, validate_password_strength
from app.utils.security import normalize_email


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def seed() -> None:
    password = required("E2E_PASSWORD")
    validate_password_strength(password)
    accounts = (
        (required("E2E_ADMIN_EMAIL"), UserRole.ADMIN),
        (required("E2E_ENGINEER_EMAIL"), UserRole.ENGINEER),
        (required("E2E_OPERATOR_EMAIL"), UserRole.OPERATOR),
    )
    engine = create_async_engine(Settings().database_url)
    hasher = PasswordHasher()
    try:
        async with engine.begin() as connection:
            company_name = "Northstar Demo Manufacturing"
            company_id = (
                await connection.execute(
                    select(Company.id).where(
                        Company.normalized_name == company_name.lower()
                    )
                )
            ).scalar_one_or_none()
            if company_id is None:
                company_id = uuid4()
                await connection.execute(
                    Company.__table__.insert().values(
                        id=company_id,
                        name=company_name,
                        normalized_name=company_name.lower(),
                        description="Disposable deterministic pilot validation tenant.",
                    )
                )
            for email, role in accounts:
                normalized = normalize_email(email)
                existing_id = (
                    await connection.execute(
                        select(User.id).where(User.email == normalized)
                    )
                ).scalar_one_or_none()
                values = {
                    "hashed_password": hasher.hash(password),
                    "is_active": True,
                    "role": role,
                    "company_id": company_id,
                }
                if existing_id is None:
                    await connection.execute(
                        User.__table__.insert().values(email=normalized, **values)
                    )
                else:
                    await connection.execute(
                        User.__table__.update()
                        .where(User.id == existing_id)
                        .values(**values)
                    )
    finally:
        await engine.dispose()
    print("Staging validation users are ready: admin, engineer, operator.")


if __name__ == "__main__":
    asyncio.run(seed())
