"""Backend-authoritative subscription plan catalogue."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanDefinition:
    code: str
    name: str
    monthly_price_minor: int
    currency: str
    description: str
    entitlements: dict[str, int | bool]


PLAN_CATALOG: tuple[PlanDefinition, ...] = (
    PlanDefinition(
        code="starter",
        name="Starter",
        monthly_price_minor=100_000,
        currency="EGP",
        description="Essential monitoring and reporting for one production site.",
        entitlements={
            "team_members": 5,
            "factories": 1,
            "machines": 25,
            "document_storage_gb": 2,
            "monthly_rag_queries": 500,
            "model_training": False,
            "training_concurrency": 0,
            "advanced_reports": False,
            "scheduled_reports": 0,
            "audit_log": False,
        },
    ),
    PlanDefinition(
        code="professional",
        name="Professional",
        monthly_price_minor=500_000,
        currency="EGP",
        description="Advanced AI operations for growing manufacturing teams.",
        entitlements={
            "team_members": 25,
            "factories": 5,
            "machines": 250,
            "document_storage_gb": 25,
            "monthly_rag_queries": 5_000,
            "model_training": True,
            "training_concurrency": 2,
            "advanced_reports": True,
            "scheduled_reports": 10,
            "audit_log": False,
        },
    ),
    PlanDefinition(
        code="enterprise",
        name="Enterprise",
        monthly_price_minor=1_000_000,
        currency="EGP",
        description="Organisation controls and governed AI at industrial scale.",
        entitlements={
            "team_members": 100,
            "factories": 25,
            "machines": 2_000,
            "document_storage_gb": 250,
            "monthly_rag_queries": 50_000,
            "model_training": True,
            "training_concurrency": 10,
            "advanced_reports": True,
            "scheduled_reports": 100,
            "audit_log": True,
        },
    ),
)


def get_plan(code: str) -> PlanDefinition | None:
    normalized = code.strip().lower()
    return next((plan for plan in PLAN_CATALOG if plan.code == normalized), None)
