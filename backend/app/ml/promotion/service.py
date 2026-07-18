"""Audited application service for explicit model alias promotion."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from app.ml.domain import TaskType
from app.ml.promotion.exceptions import (
    PromotionAliasVerificationError,
    PromotionAuditFinalizationError,
    PromotionAuthorizationError,
    PromotionPolicyRejectedError,
    PromotionPreconditionError,
    PromotionValidationError,
)
from app.ml.promotion.models import (
    ModelAlias,
    ModelPromotionRequest,
    ModelPromotionResult,
    PromotionAuditReconciliationResult,
    PromotionCandidate,
    PromotionDecision,
    PromotionEvaluation,
    PromotionOperationOutcome,
)
from app.ml.promotion.policy import (
    BasePromotionPolicy,
    ClassificationPromotionPolicy,
    RegressionPromotionPolicy,
)
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistryError,
    RegisteredModelAlias,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
    RegisteredModelVersionStatus,
    validate_registered_model_name,
)
from app.models.user import UserRole
from app.repositories.ai_governance import (
    ModelPromotionAuditRepository,
    PromotionAuditPage,
    TrainingJobRepository,
)
from app.utils.security import utc_now


class ModelPromotionService:
    """Evaluate policy, persist audit state, and verify explicit alias changes."""

    def __init__(
        self,
        *,
        job_repository: TrainingJobRepository,
        audit_repository: ModelPromotionAuditRepository,
        model_registry: BaseModelRegistry,
        regression_policy: RegressionPromotionPolicy,
        classification_policy: ClassificationPromotionPolicy,
    ) -> None:
        self._job_repository = job_repository
        self._audit_repository = audit_repository
        self._model_registry = model_registry
        self._policies: dict[TaskType, BasePromotionPolicy] = {
            TaskType.REGRESSION: regression_policy,
            TaskType.CLASSIFICATION: classification_policy,
        }

    async def promote(
        self,
        request: ModelPromotionRequest,
        *,
        requester_role: UserRole,
    ) -> ModelPromotionResult:
        """Perform one explicit, policy-gated, auditable alias assignment."""
        _authorize(request, requester_role)
        candidate_version = self._model_registry.resolve(
            request.registered_model_name,
            request.version,
        )
        if candidate_version.status is not RegisteredModelVersionStatus.READY:
            raise PromotionPreconditionError(
                "Only READY registered model versions may be promoted.",
            )
        candidate = await self._promotion_candidate(candidate_version)
        previous = self._resolve_optional(
            request.registered_model_name,
            request.target_alias,
        )
        incumbent = (
            await self._promotion_candidate(previous) if previous is not None else None
        )
        evaluation = self._policies[candidate.key.task_type].evaluate(
            candidate,
            incumbent,
        )
        transition_allowed = self._transition_allowed(request)
        if not transition_allowed:
            evaluation = PromotionEvaluation(
                accepted=False,
                reason=(
                    "Champion promotion requires the selected version to hold the "
                    "challenger alias."
                ),
                primary_metric=evaluation.primary_metric,
                candidate_value=evaluation.candidate_value,
                incumbent_value=evaluation.incumbent_value,
                improvement=evaluation.improvement,
                safeguards={**evaluation.safeguards, "challenger_transition": False},
            )

        overridden = request.force and not evaluation.accepted
        decision = (
            PromotionDecision.OVERRIDDEN
            if overridden
            else (
                PromotionDecision.APPROVED
                if evaluation.accepted
                else PromotionDecision.REJECTED
            )
        )
        audit = await self._audit_repository.create_attempt(
            registered_model_name=request.registered_model_name,
            model_version=request.version,
            key=candidate.key,
            target_alias=request.target_alias,
            previous_version=previous.version if previous else None,
            requested_by_user_id=request.requested_by_user_id,
            decision=decision,
            policy_result=evaluation.to_mapping(),
            force=request.force,
            reason=request.reason,
        )
        await self._audit_repository.commit()

        if not evaluation.accepted and not request.force:
            await self._complete_failed(
                audit.id,
                error_code="promotion_policy_rejected",
                message="The model did not satisfy the configured promotion policy.",
            )
            raise PromotionPolicyRejectedError(
                "The model did not satisfy the configured promotion policy.",
            )

        try:
            verified = self._model_registry.assign_alias(
                request.registered_model_name,
                request.target_alias.value,
                request.version,
            )
            if (
                verified.version != request.version
                or request.target_alias.value not in verified.aliases
            ):
                raise PromotionAliasVerificationError(
                    "The model registry did not verify the requested alias assignment.",
                )
        except (ModelRegistryError, PromotionAliasVerificationError):
            await self._complete_failed(
                audit.id,
                error_code="registry_alias_update_failed",
                message="The external model alias update failed.",
            )
            raise

        completed_at = await self._finalize_success(audit.id)
        return ModelPromotionResult(
            audit_id=audit.id,
            registered_model_name=request.registered_model_name,
            selected_version=request.version,
            target_alias=request.target_alias,
            previous_version=previous.version if previous else None,
            evaluation=evaluation,
            overridden=overridden,
            completed_at=completed_at,
        )

    async def _finalize_success(self, audit_id: UUID) -> datetime:
        completed_at = utc_now()
        try:
            completed = await self._audit_repository.complete_attempt(
                audit_id=audit_id,
                outcome=PromotionOperationOutcome.SUCCEEDED,
                completed_at=completed_at,
            )
            if completed is None:
                raise PromotionAuditFinalizationError(
                    "The promotion audit requires operational reconciliation.",
                )
            await self._audit_repository.commit()
        except PromotionAuditFinalizationError:
            await self._audit_repository.rollback()
            raise
        except Exception as exc:
            await self._audit_repository.rollback()
            raise PromotionAuditFinalizationError(
                "The promotion audit requires operational reconciliation.",
            ) from exc
        return completed_at

    async def list_audits(
        self,
        *,
        registered_model_name: str,
        limit: int,
        offset: int,
    ) -> PromotionAuditPage:
        """Return immutable audit history for one validated model name."""
        validate_registered_model_name(registered_model_name)
        return await self._audit_repository.list_for_model(
            registered_model_name=registered_model_name,
            limit=limit,
            offset=offset,
        )

    def list_aliases(
        self,
        registered_model_name: str,
    ) -> tuple[RegisteredModelAlias, ...]:
        """Return candidate, challenger, and champion holders."""
        return self._model_registry.list_aliases(registered_model_name)

    async def _promotion_candidate(
        self,
        version: RegisteredModelVersion,
    ) -> PromotionCandidate:
        job = await self._job_repository.find_succeeded_model_version(
            registered_model_name=version.registered_model_name,
            registered_model_version=version.version,
        )
        if job is None or job.metrics is None:
            raise PromotionPreconditionError(
                "A successful background job metrics snapshot is required for "
                "promotion.",
            )
        if job.key != version.key:
            raise PromotionPreconditionError(
                "The training evidence does not match the registered TrainerKey.",
            )
        return PromotionCandidate(
            registered_model_name=version.registered_model_name,
            version=version.version,
            key=version.key,
            metrics=job.metrics,
        )

    def _resolve_optional(
        self,
        registered_model_name: str,
        alias: ModelAlias,
    ) -> RegisteredModelVersion | None:
        try:
            return self._model_registry.resolve(
                registered_model_name,
                alias.value,
            )
        except RegisteredModelVersionNotFoundError:
            return None

    def _transition_allowed(self, request: ModelPromotionRequest) -> bool:
        if request.target_alias is not ModelAlias.CHAMPION or request.force:
            return True
        challenger = self._resolve_optional(
            request.registered_model_name,
            ModelAlias.CHALLENGER,
        )
        return challenger is not None and challenger.version == request.version

    async def _complete_failed(
        self,
        audit_id: UUID,
        *,
        error_code: str,
        message: str,
    ) -> None:
        await self._audit_repository.complete_attempt(
            audit_id=audit_id,
            outcome=PromotionOperationOutcome.FAILED,
            completed_at=utc_now(),
            error_code=error_code,
            safe_error_message=message,
        )
        await self._audit_repository.commit()


def _authorize(request: ModelPromotionRequest, role: UserRole) -> None:
    if request.target_alias is ModelAlias.CANDIDATE:
        raise PromotionValidationError(
            "The candidate alias is assigned only by successful background training.",
        )
    if request.target_alias is ModelAlias.CHAMPION and role is not UserRole.ADMIN:
        raise PromotionAuthorizationError(
            "Only administrators may promote a champion model.",
        )
    if request.target_alias is ModelAlias.CHALLENGER and role not in {
        UserRole.ADMIN,
        UserRole.ENGINEER,
    }:
        raise PromotionAuthorizationError(
            "Only administrators or engineers may promote a challenger model.",
        )
    if request.force:
        if role is not UserRole.ADMIN:
            raise PromotionAuthorizationError(
                "Only administrators may force a promotion.",
            )
        if request.reason is None or not request.reason.strip():
            raise PromotionValidationError(
                "Forced promotion requires a non-empty reason.",
            )
    if request.reason is not None and len(request.reason) > 2000:
        raise PromotionValidationError(
            "Promotion reasons must be at most 2000 characters.",
        )


class PromotionAuditReconciliationService:
    """Finalize aged pending audits by observing aliases without mutating them."""

    def __init__(
        self,
        *,
        audit_repository: ModelPromotionAuditRepository,
        model_registry: BaseModelRegistry,
        pending_after_seconds: int,
    ) -> None:
        if pending_after_seconds <= 0:
            raise ValueError("pending_after_seconds must be positive.")
        self._audit_repository = audit_repository
        self._model_registry = model_registry
        self._pending_after_seconds = pending_after_seconds

    async def reconcile(self) -> PromotionAuditReconciliationResult:
        """Observe each aged alias once and conditionally finalize its pending audit."""
        created_before = utc_now() - timedelta(
            seconds=self._pending_after_seconds,
        )
        audits = await self._audit_repository.list_pending_before(
            created_before=created_before,
        )
        await self._audit_repository.commit()
        succeeded: list[UUID] = []
        conflicted: list[UUID] = []
        unavailable: list[UUID] = []
        for audit in audits:
            try:
                holder = self._model_registry.resolve(
                    audit.registered_model_name,
                    audit.target_alias.value,
                )
            except RegisteredModelVersionNotFoundError:
                finalized = await self._finalize_conflict(audit.id)
                if finalized:
                    conflicted.append(audit.id)
                continue
            except ModelRegistryError:
                unavailable.append(audit.id)
                continue

            if holder.version == audit.model_version:
                finalized = await self._finalize(
                    audit.id,
                    outcome=PromotionOperationOutcome.SUCCEEDED,
                )
                if finalized:
                    succeeded.append(audit.id)
            else:
                finalized = await self._finalize_conflict(audit.id)
                if finalized:
                    conflicted.append(audit.id)
        return PromotionAuditReconciliationResult(
            succeeded=tuple(succeeded),
            conflicted=tuple(conflicted),
            registry_unavailable=tuple(unavailable),
        )

    async def _finalize_conflict(self, audit_id: UUID) -> bool:
        return await self._finalize(
            audit_id,
            outcome=PromotionOperationOutcome.FAILED,
            error_code="promotion_reconciliation_conflict",
            safe_error_message=(
                "The governed alias no longer points to the selected model version."
            ),
        )

    async def _finalize(
        self,
        audit_id: UUID,
        *,
        outcome: PromotionOperationOutcome,
        error_code: str | None = None,
        safe_error_message: str | None = None,
    ) -> bool:
        try:
            completed = await self._audit_repository.complete_attempt(
                audit_id=audit_id,
                outcome=outcome,
                completed_at=utc_now(),
                error_code=error_code,
                safe_error_message=safe_error_message,
            )
            if completed is None:
                await self._audit_repository.rollback()
                return False
            await self._audit_repository.commit()
        except Exception as exc:
            await self._audit_repository.rollback()
            raise PromotionAuditFinalizationError(
                "A pending promotion audit could not be reconciled.",
            ) from exc
        return True
