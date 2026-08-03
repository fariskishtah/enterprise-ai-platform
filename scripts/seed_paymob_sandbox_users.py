"""Idempotently seed two disposable, tenant-isolated Paymob sandbox owners."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

from app.config.settings import Settings
from app.models.manufacturing import Company
from app.models.user import User, UserRole
from app.utils.passwords import PasswordHasher, validate_password_strength
from app.utils.security import normalize_email
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def upsert_owner(
    connection: AsyncConnection,
    *,
    company_name: str,
    email: str,
    password: str,
    hasher: PasswordHasher,
) -> tuple[bool, bool]:
    normalized_company = company_name.lower()
    company_id = (
        await connection.execute(
            select(Company.id).where(Company.normalized_name == normalized_company)
        )
    ).scalar_one_or_none()
    company_created = company_id is None
    if company_id is None:
        company_id = uuid4()
        await connection.execute(
            insert(Company).values(
                id=company_id,
                name=company_name,
                normalized_name=normalized_company,
                description="Disposable Paymob sandbox acceptance tenant.",
            )
        )

    normalized_email = normalize_email(email)
    user_id = (
        await connection.execute(select(User.id).where(User.email == normalized_email))
    ).scalar_one_or_none()
    user_created = user_id is None
    values = {
        "hashed_password": hasher.hash(password),
        "is_active": True,
        "is_email_verified": True,
        "email_verified_at": datetime.now(UTC),
        "is_platform_operator": False,
        "role": UserRole.OWNER,
        "company_id": company_id,
    }
    if user_id is None:
        await connection.execute(
            insert(User).values(
                id=uuid4(),
                email=normalized_email,
                **values,
            )
        )
    else:
        await connection.execute(
            update(User).where(User.id == user_id).values(**values)
        )
    return company_created, user_created


async def seed() -> None:
    if required("ENABLE_DEVELOPMENT_SEED").lower() != "true":
        raise RuntimeError("Sandbox user seeding requires explicit one-shot opt-in")
    settings = Settings()
    if settings.environment != "staging" or not settings.payment_sandbox_mode:
        raise RuntimeError("Sandbox users may be seeded only in staging sandbox mode")
    if settings.payment_provider != "paymob":
        raise RuntimeError("The Paymob sandbox provider must be configured")

    owner_email = required("PAYMOB_SANDBOX_OWNER_EMAIL")
    owner_password = required("PAYMOB_SANDBOX_OWNER_PASSWORD")
    external_email = required("PAYMOB_SANDBOX_EXTERNAL_OWNER_EMAIL")
    external_password = required("PAYMOB_SANDBOX_EXTERNAL_OWNER_PASSWORD")
    if normalize_email(owner_email) == normalize_email(external_email):
        raise RuntimeError("Sandbox owners must use different email addresses")
    validate_password_strength(owner_password)
    validate_password_strength(external_password)

    engine = create_async_engine(settings.database_url)
    hasher = PasswordHasher()
    companies_created = 0
    users_created = 0
    try:
        async with engine.begin() as connection:
            for company_name, email, password in (
                ("FactoryMind Paymob Sandbox", owner_email, owner_password),
                (
                    "FactoryMind Paymob Cross-Tenant Sandbox",
                    external_email,
                    external_password,
                ),
            ):
                company_created, user_created = await upsert_owner(
                    connection,
                    company_name=company_name,
                    email=email,
                    password=password,
                    hasher=hasher,
                )
                companies_created += int(company_created)
                users_created += int(user_created)
    finally:
        await engine.dispose()

    print(
        "Paymob sandbox users are ready: "
        f"companies_created={companies_created}, users_created={users_created}."
    )


if __name__ == "__main__":
    asyncio.run(seed())
