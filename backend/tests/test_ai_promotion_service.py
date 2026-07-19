"""Audited controlled model-promotion service tests."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import app.ml.promotion.service as promotion_service_module
import pytest
from app.ml.domain import TaskType
from app.ml.jobs import RandomForestRegressionJobSpec, random_forest_key
from app.ml.promotion import (
    ClassificationPromotionPolicy,
    ModelAlias,
    ModelPromotionAuditRecord,
    ModelPromotionRequest,
    PromotionAuditFinalizationError,
    PromotionAuthorizationError,
    PromotionDecision,
    PromotionOperationOutcome,
    PromotionPolicyRejectedError,
    PromotionValidationError,
    RegressionPromotionPolicy,
)
from app.ml.promotion.service import (
    ModelPromotionService,
    PromotionAuditReconciliationService,
)
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    ModelRegistryError,
    RegisteredModelAlias,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
    RegisteredModelVersionStatus,
)
from app.models.user import User, UserRole
from app.repositories.ai_governance import (
    ModelPromotionAuditRepository,
    TrainingJobRepository,
)
from app.utils.security import utc_now
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

MODEL_NAME = "ai_core_random_forest_regression"


class FakeAliasRegistry(BaseModelRegistry):
    """In-memory exact-version and alias behavior behind the registry port."""

    def __init__(self) -> None:
        self.versions: dict[str, RegisteredModelVersion] = {}
        self.aliases: dict[str, str] = {}
        self.fail_assignment = False
        self.fail_resolution = False
        self.assignment_count = 0

    def add_version(self, version: str) -> None:
        self.versions[version] = RegisteredModelVersion(
            registered_model_name=MODEL_NAME,
            version=version,
            run_id=f"run-{version}",
            source_uri=f"file:/models/{version}/model.joblib",
            key=random_forest_key(TaskType.REGRESSION),
            status=RegisteredModelVersionStatus.READY,
            aliases=(),
        )

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        raise NotImplementedError

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        if self.fail_resolution:
            raise ModelRegistryError("private registry availability failure")
        if registered_model_name != MODEL_NAME:
            raise RegisteredModelVersionNotFoundError("not found")
        version = self.aliases.get(version_or_alias, version_or_alias)
        resolved = self.versions.get(version)
        if resolved is None:
            raise RegisteredModelVersionNotFoundError("not found")
        current_aliases = tuple(
            sorted(alias for alias, holder in self.aliases.items() if holder == version)
        )
        return RegisteredModelVersion(
            registered_model_name=resolved.registered_model_name,
            version=resolved.version,
            run_id=resolved.run_id,
            source_uri=resolved.source_uri,
            key=resolved.key,
            status=resolved.status,
            aliases=current_aliases,
        )

    def assign_alias(
        self,
        registered_model_name: str,
        alias: str,
        version: str,
    ) -> RegisteredModelVersion:
        self.assignment_count += 1
        if self.fail_assignment:
            raise ModelRegistryError("private SDK failure")
        _ = self.resolve(registered_model_name, version)
        self.aliases[alias] = version
        return self.resolve(registered_model_name, alias)

    def list_aliases(
        self,
        registered_model_name: str,
    ) -> tuple[RegisteredModelAlias, ...]:
        if registered_model_name != MODEL_NAME:
            raise RegisteredModelVersionNotFoundError("not found")
        return tuple(
            RegisteredModelAlias(alias=alias, version=version)
            for alias, version in sorted(self.aliases.items())
        )


class FailingAuditCompletionRepository(ModelPromotionAuditRepository):
    """Persist the pending attempt but fail its post-alias completion write."""

    async def complete_attempt(
        self,
        *,
        audit_id: UUID,
        outcome: PromotionOperationOutcome,
        completed_at: datetime,
        error_code: str | None = None,
        safe_error_message: str | None = None,
    ) -> ModelPromotionAuditRecord | None:
        _ = (
            audit_id,
            outcome,
            completed_at,
            error_code,
            safe_error_message,
        )
        raise RuntimeError("private database failure")


def _specification() -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,)),
        training_targets=(0.0, 1.0),
        evaluation_features=((0.5,), (0.75,)),
        evaluation_targets=(0.5, 0.75),
        hyperparameters={"n_estimators": 2, "n_jobs": 1},
        experiment_name="Promotion",
        registered_model_name=MODEL_NAME,
        tags={},
    )


async def _user_id(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
) -> UUID:
    user = User(
        email=email,
        hashed_password="not-used",
        role=UserRole.ADMIN,
        is_active=True,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user.id


async def _evidence(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    version: str,
    rmse: float,
    r2: float,
) -> None:
    job_id = uuid4()
    async with session_factory() as session:
        repository = TrainingJobRepository(session)
        await repository.create(
            job_id=job_id,
            requested_by_user_id=user_id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key=None,
            request_fingerprint=_specification().fingerprint(),
            max_attempts=3,
            queued_at=utc_now(),
        )
        claimed = await repository.claim_queued(job_id=job_id, started_at=utc_now())
        assert claimed is not None
        completed = await repository.mark_succeeded(
            job_id=job_id,
            expected_version=claimed.state_version,
            finished_at=utc_now(),
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="experiment",
            mlflow_run_id=f"run-{version}",
            registered_model_version=version,
            metrics={"rmse": rmse, "r2": r2},
        )
        assert completed is not None
        await repository.commit()


def _service(
    session: AsyncSession,
    registry: FakeAliasRegistry,
    *,
    minimum_improvement: float = 0.0,
) -> ModelPromotionService:
    return ModelPromotionService(
        job_repository=TrainingJobRepository(session),
        audit_repository=ModelPromotionAuditRepository(session),
        model_registry=registry,
        regression_policy=RegressionPromotionPolicy(
            minimum_r2=0.0,
            minimum_relative_rmse_improvement=minimum_improvement,
        ),
        classification_policy=ClassificationPromotionPolicy(
            minimum_accuracy=0.0,
            minimum_f1_improvement=0.0,
        ),
    )


@pytest.mark.anyio
async def test_challenger_then_champion_promotion_is_verified_and_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Engineer challenger and admin champion actions preserve explicit history."""
    user_id = await _user_id(session_factory, email="promoter@example.com")
    await _evidence(
        session_factory,
        user_id=user_id,
        version="1",
        rmse=0.4,
        r2=0.8,
    )
    registry = FakeAliasRegistry()
    registry.add_version("1")

    async with session_factory() as session:
        service = _service(session, registry)
        challenger = await service.promote(
            ModelPromotionRequest(
                registered_model_name=MODEL_NAME,
                version="1",
                target_alias=ModelAlias.CHALLENGER,
                requested_by_user_id=user_id,
            ),
            requester_role=UserRole.ENGINEER,
        )
        champion = await service.promote(
            ModelPromotionRequest(
                registered_model_name=MODEL_NAME,
                version="1",
                target_alias=ModelAlias.CHAMPION,
                requested_by_user_id=user_id,
            ),
            requester_role=UserRole.ADMIN,
        )
        audits = await service.list_audits(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert challenger.target_alias is ModelAlias.CHALLENGER
    assert champion.target_alias is ModelAlias.CHAMPION
    assert registry.aliases == {"challenger": "1", "champion": "1"}
    assert audits.total == 2
    assert all(
        audit.operation_outcome is PromotionOperationOutcome.SUCCEEDED
        for audit in audits.items
    )


@pytest.mark.anyio
async def test_policy_rejection_and_admin_force_override_are_both_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Rejected policy data is retained and only an admin reason can override it."""
    user_id = await _user_id(session_factory, email="override@example.com")
    await _evidence(
        session_factory,
        user_id=user_id,
        version="1",
        rmse=0.5,
        r2=0.8,
    )
    await _evidence(
        session_factory,
        user_id=user_id,
        version="2",
        rmse=0.49,
        r2=0.8,
    )
    registry = FakeAliasRegistry()
    registry.add_version("1")
    registry.add_version("2")
    registry.aliases["challenger"] = "1"

    async with session_factory() as session:
        service = _service(session, registry, minimum_improvement=0.1)
        request = ModelPromotionRequest(
            registered_model_name=MODEL_NAME,
            version="2",
            target_alias=ModelAlias.CHALLENGER,
            requested_by_user_id=user_id,
        )
        with pytest.raises(PromotionPolicyRejectedError):
            await service.promote(request, requester_role=UserRole.ENGINEER)
        forced = await service.promote(
            ModelPromotionRequest(
                registered_model_name=MODEL_NAME,
                version="2",
                target_alias=ModelAlias.CHALLENGER,
                requested_by_user_id=user_id,
                force=True,
                reason="Approved exception for a controlled validation exercise.",
            ),
            requester_role=UserRole.ADMIN,
        )
        audits = await service.list_audits(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert forced.overridden is True
    assert forced.previous_version == "1"
    assert {audit.decision for audit in audits.items} == {
        PromotionDecision.REJECTED,
        PromotionDecision.OVERRIDDEN,
    }
    assert registry.aliases["challenger"] == "2"


@pytest.mark.anyio
async def test_force_and_role_rules_are_enforced_before_alias_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Engineer champion and reasonless force attempts cannot mutate MLflow."""
    user_id = await _user_id(session_factory, email="roles@example.com")
    await _evidence(
        session_factory,
        user_id=user_id,
        version="1",
        rmse=0.4,
        r2=0.8,
    )
    registry = FakeAliasRegistry()
    registry.add_version("1")

    async with session_factory() as session:
        service = _service(session, registry)
        champion_request = ModelPromotionRequest(
            registered_model_name=MODEL_NAME,
            version="1",
            target_alias=ModelAlias.CHAMPION,
            requested_by_user_id=user_id,
        )
        with pytest.raises(PromotionAuthorizationError):
            await service.promote(
                champion_request,
                requester_role=UserRole.ENGINEER,
            )
        with pytest.raises(PromotionValidationError, match="reason"):
            await service.promote(
                ModelPromotionRequest(
                    registered_model_name=MODEL_NAME,
                    version="1",
                    target_alias=ModelAlias.CHALLENGER,
                    requested_by_user_id=user_id,
                    force=True,
                ),
                requester_role=UserRole.ADMIN,
            )

    assert registry.aliases == {}


@pytest.mark.anyio
async def test_registry_failure_finalizes_a_safe_failed_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """External alias failures retain sanitized reconciliation-ready audit state."""
    user_id = await _user_id(session_factory, email="registry-fail@example.com")
    await _evidence(
        session_factory,
        user_id=user_id,
        version="1",
        rmse=0.4,
        r2=0.8,
    )
    registry = FakeAliasRegistry()
    registry.add_version("1")
    registry.fail_assignment = True

    async with session_factory() as session:
        service = _service(session, registry)
        with pytest.raises(ModelRegistryError):
            await service.promote(
                ModelPromotionRequest(
                    registered_model_name=MODEL_NAME,
                    version="1",
                    target_alias=ModelAlias.CHALLENGER,
                    requested_by_user_id=user_id,
                ),
                requester_role=UserRole.ADMIN,
            )
        audits = await service.list_audits(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert audits.total == 1
    assert audits.items[0].operation_outcome is PromotionOperationOutcome.FAILED
    assert audits.items[0].error_code == "registry_alias_update_failed"
    assert "private SDK failure" not in (audits.items[0].safe_error_message or "")


@pytest.mark.anyio
async def test_pending_audit_reconciliation_observes_alias_without_reassigning_it(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias success survives audit failure and is finalized idempotently by read."""
    user_id = await _user_id(session_factory, email="reconcile@example.com")
    await _evidence(
        session_factory,
        user_id=user_id,
        version="1",
        rmse=0.4,
        r2=0.8,
    )
    registry = FakeAliasRegistry()
    registry.add_version("1")

    async with session_factory() as session:
        service = ModelPromotionService(
            job_repository=TrainingJobRepository(session),
            audit_repository=FailingAuditCompletionRepository(session),
            model_registry=registry,
            regression_policy=RegressionPromotionPolicy(
                minimum_r2=0.0,
                minimum_relative_rmse_improvement=0.0,
            ),
            classification_policy=ClassificationPromotionPolicy(
                minimum_accuracy=0.0,
                minimum_f1_improvement=0.0,
            ),
        )
        with pytest.raises(PromotionAuditFinalizationError):
            await service.promote(
                ModelPromotionRequest(
                    registered_model_name=MODEL_NAME,
                    version="1",
                    target_alias=ModelAlias.CHALLENGER,
                    requested_by_user_id=user_id,
                ),
                requester_role=UserRole.ADMIN,
            )
        pending = await ModelPromotionAuditRepository(session).list_for_model(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert registry.aliases["challenger"] == "1"
    assert registry.assignment_count == 1
    assert pending.items[0].operation_outcome is PromotionOperationOutcome.PENDING

    monkeypatch.setattr(
        promotion_service_module,
        "utc_now",
        lambda: utc_now() + timedelta(minutes=10),
    )
    registry.fail_resolution = True
    async with session_factory() as session:
        unavailable = await PromotionAuditReconciliationService(
            audit_repository=ModelPromotionAuditRepository(session),
            model_registry=registry,
            pending_after_seconds=60,
        ).reconcile()
        still_pending = await ModelPromotionAuditRepository(session).list_for_model(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert unavailable.registry_unavailable == (pending.items[0].id,)
    assert still_pending.items[0].operation_outcome is PromotionOperationOutcome.PENDING

    registry.fail_resolution = False
    async with session_factory() as session:
        reconciliation = PromotionAuditReconciliationService(
            audit_repository=ModelPromotionAuditRepository(session),
            model_registry=registry,
            pending_after_seconds=60,
        )
        repaired = await reconciliation.reconcile()
        repeated = await reconciliation.reconcile()
        audits = await ModelPromotionAuditRepository(session).list_for_model(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert repaired.succeeded == (pending.items[0].id,)
    assert repeated.succeeded == ()
    assert audits.items[0].operation_outcome is PromotionOperationOutcome.SUCCEEDED
    assert registry.assignment_count == 1


@pytest.mark.anyio
async def test_promotion_reasons_are_normalized_before_validation_and_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Whitespace is stripped, empty force reasons fail, and length follows trim."""
    user_id = await _user_id(session_factory, email="reason@example.com")
    await _evidence(
        session_factory,
        user_id=user_id,
        version="1",
        rmse=0.4,
        r2=0.8,
    )
    registry = FakeAliasRegistry()
    registry.add_version("1")
    exact_limit = ModelPromotionRequest(
        registered_model_name=MODEL_NAME,
        version="1",
        target_alias=ModelAlias.CHALLENGER,
        requested_by_user_id=user_id,
        reason=f"  {'x' * 2000}  ",
    )
    assert exact_limit.reason == "x" * 2000
    with pytest.raises(PromotionValidationError, match="2000"):
        ModelPromotionRequest(
            registered_model_name=MODEL_NAME,
            version="1",
            target_alias=ModelAlias.CHALLENGER,
            requested_by_user_id=user_id,
            reason=f"  {'x' * 2001}  ",
        )

    async with session_factory() as session:
        service = _service(session, registry)
        with pytest.raises(PromotionValidationError, match="reason"):
            await service.promote(
                ModelPromotionRequest(
                    registered_model_name=MODEL_NAME,
                    version="1",
                    target_alias=ModelAlias.CHALLENGER,
                    requested_by_user_id=user_id,
                    force=True,
                    reason="   ",
                ),
                requester_role=UserRole.ADMIN,
            )
        await service.promote(
            ModelPromotionRequest(
                registered_model_name=MODEL_NAME,
                version="1",
                target_alias=ModelAlias.CHALLENGER,
                requested_by_user_id=user_id,
                reason="  reviewed by governance  ",
            ),
            requester_role=UserRole.ADMIN,
        )
        audits = await service.list_audits(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert audits.items[0].reason == "reviewed by governance"


@pytest.mark.anyio
async def test_pending_audit_reconciliation_age_gates_and_records_alias_conflict(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recent audits are untouched; an aged different alias holder fails safely."""
    user_id = await _user_id(session_factory, email="conflict@example.com")
    registry = FakeAliasRegistry()
    registry.add_version("1")
    registry.add_version("2")
    registry.aliases["challenger"] = "2"
    async with session_factory() as session:
        repository = ModelPromotionAuditRepository(session)
        audit = await repository.create_attempt(
            registered_model_name=MODEL_NAME,
            model_version="1",
            key=random_forest_key(TaskType.REGRESSION),
            target_alias=ModelAlias.CHALLENGER,
            previous_version=None,
            requested_by_user_id=user_id,
            decision=PromotionDecision.APPROVED,
            policy_result={"accepted": True},
            force=False,
            reason=None,
        )
        await repository.commit()
        reconciliation = PromotionAuditReconciliationService(
            audit_repository=repository,
            model_registry=registry,
            pending_after_seconds=60,
        )
        recent = await reconciliation.reconcile()

    assert recent.conflicted == ()
    monkeypatch.setattr(
        promotion_service_module,
        "utc_now",
        lambda: utc_now() + timedelta(minutes=10),
    )
    async with session_factory() as session:
        reconciliation = PromotionAuditReconciliationService(
            audit_repository=ModelPromotionAuditRepository(session),
            model_registry=registry,
            pending_after_seconds=60,
        )
        conflicted = await reconciliation.reconcile()
        repeated = await reconciliation.reconcile()
        audits = await ModelPromotionAuditRepository(session).list_for_model(
            registered_model_name=MODEL_NAME,
            limit=10,
            offset=0,
        )

    assert conflicted.conflicted == (audit.id,)
    assert repeated.conflicted == ()
    assert audits.items[0].operation_outcome is PromotionOperationOutcome.FAILED
    assert audits.items[0].error_code == "promotion_reconciliation_conflict"
    assert registry.assignment_count == 0
