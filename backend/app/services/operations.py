"""Company-scoped operational maintenance use cases."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
)
from app.models.manufacturing import Factory, Machine
from app.models.monitoring_orchestration import MonitoringAlertEntity
from app.models.operations import (
    MaintenanceFeedback,
    MaintenanceFeedbackOutcome,
    OperationalAction,
    OperationalActionPriority,
    OperationalActionStatus,
    OperationalNote,
    OperationalNoteKind,
    OperationalTimelineEvent,
    ShiftHandover,
    ShiftStatus,
)
from app.models.pilot import MachineRiskAssessment
from app.models.user import User, UserRole
from app.utils.security import utc_now

_URGENT_PRIORITIES = (
    OperationalActionPriority.CRITICAL,
    OperationalActionPriority.HIGH,
)
_ACTION_TRANSITIONS: dict[
    OperationalActionStatus, frozenset[OperationalActionStatus]
] = {
    OperationalActionStatus.OPEN: frozenset(
        {OperationalActionStatus.ASSIGNED, OperationalActionStatus.CANCELLED}
    ),
    OperationalActionStatus.ASSIGNED: frozenset(
        {
            OperationalActionStatus.IN_PROGRESS,
            OperationalActionStatus.BLOCKED,
            OperationalActionStatus.CANCELLED,
        }
    ),
    OperationalActionStatus.IN_PROGRESS: frozenset(
        {
            OperationalActionStatus.BLOCKED,
            OperationalActionStatus.COMPLETED,
            OperationalActionStatus.CANCELLED,
        }
    ),
    OperationalActionStatus.BLOCKED: frozenset(
        {OperationalActionStatus.IN_PROGRESS, OperationalActionStatus.CANCELLED}
    ),
    OperationalActionStatus.COMPLETED: frozenset(),
    OperationalActionStatus.CANCELLED: frozenset(),
}


class OperationsError(RuntimeError):
    """Base safe operations error."""


class OperationsNotFoundError(OperationsError):
    pass


class OperationsConflictError(OperationsError):
    pass


class OperationsPermissionError(OperationsError):
    pass


class OperationsService:
    """Coordinate operational state transitions in one database transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def require_machine(
        self, *, company_id: UUID, factory_id: UUID, machine_id: UUID
    ) -> Machine:
        machine = (
            await self._session.execute(
                select(Machine)
                .join(Factory, Factory.id == Machine.factory_id)
                .where(
                    Machine.id == machine_id,
                    Machine.factory_id == factory_id,
                    Machine.deleted_at.is_(None),
                    Factory.company_id == company_id,
                    Factory.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if machine is None:
            raise OperationsNotFoundError("Machine was not found.")
        return machine

    async def require_assignee(self, *, company_id: UUID, user_id: UUID) -> User:
        user = (
            await self._session.execute(
                select(User).where(
                    User.id == user_id,
                    User.company_id == company_id,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise OperationsNotFoundError("Assignee was not found.")
        return user

    def _operator_can_access(self, action: OperationalAction, actor: User) -> bool:
        return action.assigned_user_id == actor.id or (
            action.assigned_user_id is None
            and action.priority in _URGENT_PRIORITIES
            and action.status
            not in {
                OperationalActionStatus.COMPLETED,
                OperationalActionStatus.CANCELLED,
            }
        )

    async def get_action(self, action_id: UUID, *, actor: User) -> OperationalAction:
        action = (
            await self._session.execute(
                select(OperationalAction).where(
                    OperationalAction.id == action_id,
                    OperationalAction.company_id == actor.company_id,
                )
            )
        ).scalar_one_or_none()
        if action is None or (
            actor.role is UserRole.OPERATOR
            and not self._operator_can_access(action, actor)
        ):
            raise OperationsNotFoundError("Operational action was not found.")
        return action

    async def list_actions(
        self,
        *,
        actor: User,
        priority: OperationalActionPriority | None,
        action_status: OperationalActionStatus | None,
        factory_id: UUID | None,
        machine_id: UUID | None,
        assignee_id: UUID | None,
        overdue: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[OperationalAction], int]:
        conditions = [OperationalAction.company_id == actor.company_id]
        if actor.role is UserRole.OPERATOR:
            conditions.append(
                or_(
                    OperationalAction.assigned_user_id == actor.id,
                    and_(
                        OperationalAction.assigned_user_id.is_(None),
                        OperationalAction.priority.in_(_URGENT_PRIORITIES),
                        OperationalAction.status.not_in(
                            (
                                OperationalActionStatus.COMPLETED,
                                OperationalActionStatus.CANCELLED,
                            )
                        ),
                    ),
                )
            )
        if priority is not None:
            conditions.append(OperationalAction.priority == priority)
        if action_status is not None:
            conditions.append(OperationalAction.status == action_status)
        if factory_id is not None:
            conditions.append(OperationalAction.factory_id == factory_id)
        if machine_id is not None:
            conditions.append(OperationalAction.machine_id == machine_id)
        if assignee_id is not None:
            conditions.append(OperationalAction.assigned_user_id == assignee_id)
        now = utc_now()
        if overdue is True:
            conditions.extend(
                (
                    OperationalAction.due_at.is_not(None),
                    OperationalAction.due_at < now,
                    OperationalAction.status.not_in(
                        (
                            OperationalActionStatus.COMPLETED,
                            OperationalActionStatus.CANCELLED,
                        )
                    ),
                )
            )
        elif overdue is False:
            conditions.append(
                or_(
                    OperationalAction.due_at.is_(None),
                    OperationalAction.due_at >= now,
                )
            )
        if start_at is not None:
            conditions.append(OperationalAction.created_at >= start_at)
        if end_at is not None:
            conditions.append(OperationalAction.created_at <= end_at)
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(OperationalAction)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(OperationalAction)
            .where(*conditions)
            .order_by(
                case(
                    (
                        OperationalAction.priority
                        == OperationalActionPriority.CRITICAL,
                        0,
                    ),
                    (OperationalAction.priority == OperationalActionPriority.HIGH, 1),
                    (OperationalAction.priority == OperationalActionPriority.MEDIUM, 2),
                    else_=3,
                ),
                OperationalAction.due_at.asc().nulls_last(),
                OperationalAction.created_at.desc(),
                OperationalAction.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars()), total

    async def create_action(
        self,
        *,
        actor: User,
        factory_id: UUID,
        machine_id: UUID,
        related_alert_id: UUID | None,
        title: str,
        reason: str,
        recommended_action: str,
        priority: OperationalActionPriority,
        assigned_user_id: UUID | None,
        due_at: datetime | None,
    ) -> OperationalAction:
        await self.require_machine(
            company_id=actor.company_id,
            factory_id=factory_id,
            machine_id=machine_id,
        )
        if assigned_user_id is not None:
            await self.require_assignee(
                company_id=actor.company_id, user_id=assigned_user_id
            )
        if related_alert_id is not None:
            alert = await self._get_alert(related_alert_id, actor.company_id)
            if alert.machine_id != machine_id or alert.factory_id != factory_id:
                raise OperationsConflictError(
                    "The related alert does not belong to this machine."
                )
            await self._ensure_alert_source_timeline(alert)
        now = utc_now()
        action = OperationalAction(
            company_id=actor.company_id,
            factory_id=factory_id,
            machine_id=machine_id,
            related_alert_id=related_alert_id,
            title=title.strip(),
            reason=reason.strip(),
            recommended_action=recommended_action.strip(),
            priority=priority,
            status=(
                OperationalActionStatus.ASSIGNED
                if assigned_user_id is not None
                else OperationalActionStatus.OPEN
            ),
            assigned_user_id=assigned_user_id,
            created_by=actor.id,
            due_at=due_at,
        )
        self._session.add(action)
        await self._session.flush()
        await self._timeline(
            action=action,
            actor=actor,
            event_type="action.created",
            title="Operational action created",
            detail=action.reason,
            occurred_at=now,
        )
        if assigned_user_id is not None:
            await self._timeline(
                action=action,
                actor=actor,
                event_type="action.assigned",
                title="Operational action assigned",
                detail="An assignee was selected for this action.",
                occurred_at=now,
                metadata={"assigned_user_id": str(assigned_user_id)},
            )
        await self._session.commit()
        await self._session.refresh(action)
        return action

    def _check_version(self, *, actual: int, expected: int) -> None:
        if actual != expected:
            raise OperationsConflictError(
                "This record changed. Refresh before trying again."
            )

    async def assign_action(
        self,
        action_id: UUID,
        *,
        actor: User,
        assigned_user_id: UUID,
        expected_version: int,
    ) -> OperationalAction:
        action = await self.get_action(action_id, actor=actor)
        self._check_version(actual=action.version, expected=expected_version)
        await self.require_assignee(
            company_id=actor.company_id, user_id=assigned_user_id
        )
        if action.status in {
            OperationalActionStatus.COMPLETED,
            OperationalActionStatus.CANCELLED,
        }:
            raise OperationsConflictError("Closed actions cannot be assigned.")
        action.assigned_user_id = assigned_user_id
        if action.status is OperationalActionStatus.OPEN:
            action.status = OperationalActionStatus.ASSIGNED
        action.version += 1
        now = utc_now()
        await self._timeline(
            action=action,
            actor=actor,
            event_type="action.assigned",
            title="Operational action assigned",
            detail="The action assignee changed.",
            occurred_at=now,
            metadata={"assigned_user_id": str(assigned_user_id)},
        )
        await self._session.commit()
        await self._session.refresh(action)
        return action

    async def acknowledge_action(
        self,
        action_id: UUID,
        *,
        actor: User,
        expected_version: int,
        note: str | None,
    ) -> OperationalAction:
        action = await self.get_action(action_id, actor=actor)
        self._check_version(actual=action.version, expected=expected_version)
        if actor.role is UserRole.OPERATOR and action.assigned_user_id not in {
            None,
            actor.id,
        }:
            raise OperationsPermissionError(
                "Only the assigned operator can acknowledge this action."
            )
        if action.status not in {
            OperationalActionStatus.OPEN,
            OperationalActionStatus.ASSIGNED,
        }:
            raise OperationsConflictError(
                "Only an open or assigned action can be acknowledged."
            )
        now = utc_now()
        if action.assigned_user_id is None:
            action.assigned_user_id = actor.id
        action.status = OperationalActionStatus.ASSIGNED
        action.acknowledged_at = now
        action.version += 1
        await self._timeline(
            action=action,
            actor=actor,
            event_type="action.acknowledged",
            title="Operational action acknowledged",
            detail="The assigned work was acknowledged.",
            occurred_at=now,
        )
        if note and note.strip():
            await self._add_note_entity(
                actor=actor, action=action, alert=None, body=note
            )
        await self._session.commit()
        await self._session.refresh(action)
        return action

    async def transition_action(
        self,
        action_id: UUID,
        *,
        actor: User,
        next_status: OperationalActionStatus,
        expected_version: int,
        summary: str | None,
    ) -> OperationalAction:
        action = await self.get_action(action_id, actor=actor)
        self._check_version(actual=action.version, expected=expected_version)
        if actor.role is UserRole.OPERATOR and action.assigned_user_id != actor.id:
            raise OperationsPermissionError(
                "Only the assigned operator can update this action."
            )
        if next_status not in _ACTION_TRANSITIONS[action.status]:
            raise OperationsConflictError(
                f"Action cannot move from {action.status.value} to "
                f"{next_status.value}."
            )
        if (
            next_status is OperationalActionStatus.COMPLETED
            and not (summary or "").strip()
        ):
            raise OperationsConflictError("A completion summary is required.")
        now = utc_now()
        action.status = next_status
        action.version += 1
        if next_status is OperationalActionStatus.IN_PROGRESS:
            action.started_at = action.started_at or now
        if next_status is OperationalActionStatus.COMPLETED:
            action.completed_at = now
            action.completion_summary = (summary or "").strip()
        elif summary and summary.strip():
            action.completion_summary = summary.strip()
        await self._timeline(
            action=action,
            actor=actor,
            event_type=f"action.{next_status.value}",
            title=f"Operational action {next_status.value.replace('_', ' ')}",
            detail=(summary or "The action status changed.").strip(),
            occurred_at=now,
        )
        await self._session.commit()
        await self._session.refresh(action)
        return action

    async def reopen_action(
        self,
        action_id: UUID,
        *,
        actor: User,
        expected_version: int,
        reason: str,
    ) -> OperationalAction:
        action = await self.get_action(action_id, actor=actor)
        self._check_version(actual=action.version, expected=expected_version)
        if action.status not in {
            OperationalActionStatus.COMPLETED,
            OperationalActionStatus.CANCELLED,
        }:
            raise OperationsConflictError(
                "Only a completed or cancelled action can be reopened."
            )
        action.status = OperationalActionStatus.OPEN
        action.assigned_user_id = None
        action.acknowledged_at = None
        action.started_at = None
        action.completed_at = None
        action.completion_summary = None
        action.version += 1
        await self._timeline(
            action=action,
            actor=actor,
            event_type="action.reopened",
            title="Operational action reopened",
            detail=reason.strip(),
            occurred_at=utc_now(),
        )
        await self._session.commit()
        await self._session.refresh(action)
        return action

    async def add_action_note(
        self, action_id: UUID, *, actor: User, body: str
    ) -> OperationalNote:
        action = await self.get_action(action_id, actor=actor)
        note = await self._add_note_entity(
            actor=actor, action=action, alert=None, body=body
        )
        await self._session.commit()
        await self._session.refresh(note)
        return note

    async def add_alert_note(
        self, alert_id: UUID, *, actor: User, body: str
    ) -> OperationalNote:
        alert = await self.get_alert(alert_id, actor=actor)
        if alert.factory_id is None or alert.machine_id is None:
            raise OperationsConflictError(
                "This alert is not linked to an operational machine."
            )
        note = await self._add_note_entity(
            actor=actor, action=None, alert=alert, body=body
        )
        await self._session.commit()
        await self._session.refresh(note)
        return note

    async def _add_note_entity(
        self,
        *,
        actor: User,
        action: OperationalAction | None,
        alert: MonitoringAlertEntity | None,
        body: str,
    ) -> OperationalNote:
        factory_id: UUID | None
        machine_id: UUID | None
        if action is not None:
            factory_id = action.factory_id
            machine_id = action.machine_id
        elif alert is not None:
            factory_id = alert.factory_id
            machine_id = alert.machine_id
        else:
            raise OperationsConflictError("A note parent is required.")
        if factory_id is None or machine_id is None:
            raise OperationsConflictError("The note parent has no machine context.")
        note = OperationalNote(
            company_id=actor.company_id,
            factory_id=factory_id,
            machine_id=machine_id,
            action_id=action.id if action else None,
            alert_id=alert.id if alert else None,
            author_user_id=actor.id,
            kind=(
                OperationalNoteKind.OPERATOR
                if actor.role is UserRole.OPERATOR
                else OperationalNoteKind.ENGINEER
            ),
            body=body.strip(),
        )
        self._session.add(note)
        await self._session.flush()
        await self._timeline(
            action=action,
            alert=alert,
            actor=actor,
            event_type="note.added",
            title=f"{note.kind.value.title()} note added",
            detail=note.body,
            occurred_at=utc_now(),
        )
        return note

    async def list_notes(
        self,
        *,
        actor: User,
        action_id: UUID | None,
        alert_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[OperationalNote]:
        if action_id is not None:
            await self.get_action(action_id, actor=actor)
        if alert_id is not None:
            await self.get_alert(alert_id, actor=actor)
        conditions = [OperationalNote.company_id == actor.company_id]
        if action_id is not None:
            conditions.append(OperationalNote.action_id == action_id)
        if alert_id is not None:
            conditions.append(OperationalNote.alert_id == alert_id)
        result = await self._session.execute(
            select(OperationalNote)
            .where(*conditions)
            .order_by(OperationalNote.created_at.asc(), OperationalNote.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def submit_feedback(
        self,
        *,
        actor: User,
        action_id: UUID | None,
        alert_id: UUID | None,
        outcome: MaintenanceFeedbackOutcome,
        maintenance_category: str | None,
        replaced_component: str | None,
        downtime_minutes: int | None,
        summary: str,
    ) -> MaintenanceFeedback:
        action = (
            await self.get_action(action_id, actor=actor)
            if action_id is not None
            else None
        )
        alert = (
            await self.get_alert(alert_id, actor=actor)
            if alert_id is not None
            else None
        )
        if (
            action is not None
            and alert is not None
            and (
                action.machine_id != alert.machine_id
                or action.factory_id != alert.factory_id
            )
        ):
            raise OperationsConflictError(
                "Feedback parents must refer to the same machine."
            )
        factory_id: UUID | None
        machine_id: UUID | None
        if action is not None:
            factory_id = action.factory_id
            machine_id = action.machine_id
        elif alert is not None:
            factory_id = alert.factory_id
            machine_id = alert.machine_id
        else:
            raise OperationsConflictError("Feedback requires a parent.")
        if factory_id is None or machine_id is None:
            raise OperationsConflictError("Feedback requires machine context.")
        feedback = MaintenanceFeedback(
            company_id=actor.company_id,
            factory_id=factory_id,
            machine_id=machine_id,
            action_id=action_id,
            alert_id=alert_id,
            outcome=outcome,
            maintenance_category=(
                maintenance_category.strip() if maintenance_category else None
            ),
            replaced_component=(
                replaced_component.strip() if replaced_component else None
            ),
            downtime_minutes=downtime_minutes,
            summary=summary.strip(),
            submitted_by_user_id=actor.id,
        )
        self._session.add(feedback)
        await self._session.flush()
        await self._timeline(
            action=action,
            alert=alert,
            actor=actor,
            event_type="maintenance.feedback_submitted",
            title="Maintenance feedback submitted",
            detail=feedback.summary,
            occurred_at=utc_now(),
            metadata={"outcome": outcome.value},
        )
        await self._session.commit()
        await self._session.refresh(feedback)
        return feedback

    async def list_feedback(
        self,
        *,
        actor: User,
        action_id: UUID | None,
        alert_id: UUID | None,
        machine_id: UUID | None,
        outcome: MaintenanceFeedbackOutcome | None,
        limit: int,
        offset: int,
    ) -> tuple[list[MaintenanceFeedback], int]:
        conditions = [MaintenanceFeedback.company_id == actor.company_id]
        if action_id is not None:
            conditions.append(MaintenanceFeedback.action_id == action_id)
        if alert_id is not None:
            conditions.append(MaintenanceFeedback.alert_id == alert_id)
        if machine_id is not None:
            conditions.append(MaintenanceFeedback.machine_id == machine_id)
        if outcome is not None:
            conditions.append(MaintenanceFeedback.outcome == outcome)
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(MaintenanceFeedback)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        feedback = (
            await self._session.execute(
                select(MaintenanceFeedback)
                .where(*conditions)
                .order_by(
                    MaintenanceFeedback.created_at.desc(),
                    MaintenanceFeedback.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(feedback), total

    async def _get_alert(
        self, alert_id: UUID, company_id: UUID
    ) -> MonitoringAlertEntity:
        alert = (
            await self._session.execute(
                select(MonitoringAlertEntity).where(
                    MonitoringAlertEntity.id == alert_id,
                    MonitoringAlertEntity.company_id == company_id,
                )
            )
        ).scalar_one_or_none()
        if alert is None:
            raise OperationsNotFoundError("Alert was not found.")
        return alert

    async def get_alert(self, alert_id: UUID, *, actor: User) -> MonitoringAlertEntity:
        alert = await self._get_alert(alert_id, actor.company_id)
        if actor.role is UserRole.OPERATOR and (
            alert.machine_id is None or alert.factory_id is None
        ):
            raise OperationsNotFoundError("Alert was not found.")
        return alert

    async def list_alerts(
        self,
        *,
        actor: User,
        alert_status: MonitoringAlertStatus | None,
        severity: MonitoringAlertSeverity | None,
        factory_id: UUID | None,
        machine_id: UUID | None,
        assigned_user_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[MonitoringAlertEntity], int]:
        conditions = [MonitoringAlertEntity.company_id == actor.company_id]
        if actor.role is UserRole.OPERATOR:
            conditions.extend(
                (
                    MonitoringAlertEntity.machine_id.is_not(None),
                    MonitoringAlertEntity.factory_id.is_not(None),
                )
            )
        if alert_status is not None:
            conditions.append(MonitoringAlertEntity.status == alert_status)
        if severity is not None:
            conditions.append(MonitoringAlertEntity.severity == severity)
        if factory_id is not None:
            conditions.append(MonitoringAlertEntity.factory_id == factory_id)
        if machine_id is not None:
            conditions.append(MonitoringAlertEntity.machine_id == machine_id)
        if assigned_user_id is not None:
            conditions.append(
                MonitoringAlertEntity.assigned_user_id == assigned_user_id
            )
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(MonitoringAlertEntity)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(MonitoringAlertEntity)
            .where(*conditions)
            .order_by(
                MonitoringAlertEntity.severity.asc(),
                MonitoringAlertEntity.last_detected_at.desc(),
                MonitoringAlertEntity.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars()), total

    async def transition_alert(
        self,
        alert_id: UUID,
        *,
        actor: User,
        transition: str,
        expected_version: int,
        assigned_user_id: UUID | None,
        note: str | None,
        resolution_summary: str | None,
        resolution_classification: str | None,
        reopen_reason: str | None,
    ) -> MonitoringAlertEntity:
        alert = await self.get_alert(alert_id, actor=actor)
        self._check_version(actual=alert.lifecycle_version, expected=expected_version)
        await self._ensure_alert_source_timeline(alert)
        now = utc_now()
        if transition == "assign":
            if actor.role is UserRole.OPERATOR:
                raise OperationsPermissionError("Operators cannot assign alerts.")
            if assigned_user_id is None:
                raise OperationsConflictError("An assignee is required.")
            await self.require_assignee(
                company_id=actor.company_id, user_id=assigned_user_id
            )
            if alert.status is MonitoringAlertStatus.RESOLVED:
                raise OperationsConflictError("Resolved alerts cannot be assigned.")
            alert.assigned_user_id = assigned_user_id
            alert.assigned_at = now
            alert.assigned_by_user_id = actor.id
        elif transition == "acknowledge":
            if alert.status not in {
                MonitoringAlertStatus.OPEN,
                MonitoringAlertStatus.ESCALATED,
            }:
                raise OperationsConflictError(
                    "Only an open or escalated alert can be acknowledged."
                )
            if actor.role is UserRole.OPERATOR and alert.assigned_user_id not in {
                None,
                actor.id,
            }:
                raise OperationsPermissionError(
                    "Only the assigned operator can acknowledge this alert."
                )
            alert.assigned_user_id = alert.assigned_user_id or actor.id
            alert.status = MonitoringAlertStatus.ACKNOWLEDGED
            alert.acknowledged_at = now
            alert.acknowledged_by_user_id = actor.id
        elif transition == "start":
            if alert.status is not MonitoringAlertStatus.ACKNOWLEDGED:
                raise OperationsConflictError(
                    "Only an acknowledged alert can be started."
                )
            if actor.role is UserRole.OPERATOR and alert.assigned_user_id != actor.id:
                raise OperationsPermissionError(
                    "Only the assigned operator can start this alert."
                )
            alert.status = MonitoringAlertStatus.IN_PROGRESS
            alert.in_progress_at = now
        elif transition == "escalate":
            if alert.status is MonitoringAlertStatus.RESOLVED:
                raise OperationsConflictError("Resolved alerts cannot be escalated.")
            alert.status = MonitoringAlertStatus.ESCALATED
            alert.escalated_at = now
            alert.escalated_by_user_id = actor.id
        elif transition == "resolve":
            if actor.role is UserRole.OPERATOR:
                raise OperationsPermissionError("Operators cannot resolve alerts.")
            if alert.status is MonitoringAlertStatus.RESOLVED:
                raise OperationsConflictError("The alert is already resolved.")
            safe_resolution_summary = (resolution_summary or "").strip()
            if not safe_resolution_summary or not resolution_classification:
                raise OperationsConflictError(
                    "Resolution summary and classification are required."
                )
            alert.status = MonitoringAlertStatus.RESOLVED
            alert.resolved_at = now
            alert.resolution_summary = safe_resolution_summary
            alert.resolution_classification = resolution_classification
            alert.engineer_note = (note or safe_resolution_summary).strip()
        elif transition == "reopen":
            if actor.role is UserRole.OPERATOR:
                raise OperationsPermissionError("Operators cannot reopen alerts.")
            if alert.status is not MonitoringAlertStatus.RESOLVED:
                raise OperationsConflictError("Only a resolved alert can be reopened.")
            safe_reopen_reason = (reopen_reason or "").strip()
            if not safe_reopen_reason:
                raise OperationsConflictError("A reopen reason is required.")
            alert.status = MonitoringAlertStatus.OPEN
            alert.reopened_at = now
            alert.reopened_by_user_id = actor.id
            alert.reopen_reason = safe_reopen_reason
            alert.resolved_at = None
            alert.resolution_summary = None
            alert.resolution_classification = None
        else:
            raise OperationsConflictError("Unsupported alert transition.")
        alert.lifecycle_version += 1
        await self._timeline(
            alert=alert,
            actor=actor,
            event_type=f"alert.{transition}",
            title=f"Alert {transition.replace('_', ' ')}",
            detail=(
                resolution_summary
                or reopen_reason
                or note
                or "The alert lifecycle changed."
            ).strip(),
            occurred_at=now,
            metadata=(
                {"assigned_user_id": str(assigned_user_id)}
                if assigned_user_id
                else None
            ),
        )
        if note and transition not in {"resolve"}:
            await self._add_note_entity(
                actor=actor, action=None, alert=alert, body=note
            )
        await self._session.commit()
        await self._session.refresh(alert)
        return alert

    async def list_timeline(
        self,
        *,
        actor: User,
        machine_id: UUID | None,
        factory_id: UUID | None,
        event_type: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[OperationalTimelineEvent], int]:
        conditions = [OperationalTimelineEvent.company_id == actor.company_id]
        if machine_id is not None:
            conditions.append(OperationalTimelineEvent.machine_id == machine_id)
        if factory_id is not None:
            conditions.append(OperationalTimelineEvent.factory_id == factory_id)
        if event_type is not None:
            conditions.append(OperationalTimelineEvent.event_type == event_type)
        if start_at is not None:
            conditions.append(OperationalTimelineEvent.occurred_at >= start_at)
        if end_at is not None:
            conditions.append(OperationalTimelineEvent.occurred_at <= end_at)
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(OperationalTimelineEvent)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(OperationalTimelineEvent)
            .where(*conditions)
            .order_by(
                OperationalTimelineEvent.occurred_at.desc(),
                OperationalTimelineEvent.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars()), total

    async def start_shift(
        self,
        *,
        actor: User,
        factory_id: UUID,
        team_label: str | None,
    ) -> ShiftHandover:
        factory = (
            await self._session.execute(
                select(Factory).where(
                    Factory.id == factory_id,
                    Factory.company_id == actor.company_id,
                    Factory.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if factory is None:
            raise OperationsNotFoundError("Factory was not found.")
        active = (
            await self._session.execute(
                select(ShiftHandover.id).where(
                    ShiftHandover.factory_id == factory_id,
                    ShiftHandover.status == ShiftStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            raise OperationsConflictError("This factory already has an active shift.")
        shift = ShiftHandover(
            company_id=actor.company_id,
            factory_id=factory_id,
            status=ShiftStatus.ACTIVE,
            started_by_user_id=actor.id,
            team_label=team_label.strip() if team_label else None,
            started_at=utc_now(),
            snapshot={},
        )
        self._session.add(shift)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise OperationsConflictError(
                "This factory already has an active shift."
            ) from exc
        await self._session.refresh(shift)
        return shift

    async def get_shift(self, shift_id: UUID, *, actor: User) -> ShiftHandover:
        shift = (
            await self._session.execute(
                select(ShiftHandover).where(
                    ShiftHandover.id == shift_id,
                    ShiftHandover.company_id == actor.company_id,
                )
            )
        ).scalar_one_or_none()
        if shift is None:
            raise OperationsNotFoundError("Shift handover was not found.")
        return shift

    async def list_shifts(
        self,
        *,
        actor: User,
        factory_id: UUID | None,
        shift_status: ShiftStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ShiftHandover], int]:
        conditions = [ShiftHandover.company_id == actor.company_id]
        if factory_id is not None:
            conditions.append(ShiftHandover.factory_id == factory_id)
        if shift_status is not None:
            conditions.append(ShiftHandover.status == shift_status)
        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(ShiftHandover).where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(ShiftHandover)
            .where(*conditions)
            .order_by(ShiftHandover.started_at.desc(), ShiftHandover.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars()), total

    async def end_shift(
        self,
        shift_id: UUID,
        *,
        actor: User,
        handover_notes: str,
        unresolved_summary: str | None,
    ) -> ShiftHandover:
        shift = await self.get_shift(shift_id, actor=actor)
        if shift.status is not ShiftStatus.ACTIVE:
            raise OperationsConflictError("Only an active shift can be ended.")
        if actor.role is UserRole.OPERATOR and shift.started_by_user_id != actor.id:
            raise OperationsPermissionError(
                "Only the operator who started this shift can end it."
            )
        now = utc_now()
        open_actions = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(OperationalAction)
                    .where(
                        OperationalAction.company_id == shift.company_id,
                        OperationalAction.factory_id == shift.factory_id,
                        OperationalAction.status.not_in(
                            (
                                OperationalActionStatus.COMPLETED,
                                OperationalActionStatus.CANCELLED,
                            )
                        ),
                    )
                )
            ).scalar_one()
        )
        unresolved_alerts = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(MonitoringAlertEntity)
                    .where(
                        MonitoringAlertEntity.company_id == shift.company_id,
                        MonitoringAlertEntity.factory_id == shift.factory_id,
                        MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
                    )
                )
            ).scalar_one()
        )
        completed_actions = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(OperationalAction)
                    .where(
                        OperationalAction.company_id == shift.company_id,
                        OperationalAction.factory_id == shift.factory_id,
                        OperationalAction.completed_at >= shift.started_at,
                        OperationalAction.completed_at <= now,
                    )
                )
            ).scalar_one()
        )
        alerts_during_shift = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(MonitoringAlertEntity)
                    .where(
                        MonitoringAlertEntity.company_id == shift.company_id,
                        MonitoringAlertEntity.factory_id == shift.factory_id,
                        MonitoringAlertEntity.last_detected_at >= shift.started_at,
                        MonitoringAlertEntity.last_detected_at <= now,
                    )
                )
            ).scalar_one()
        )
        critical_machines = int(
            (
                await self._session.execute(
                    select(
                        func.count(func.distinct(MonitoringAlertEntity.machine_id))
                    ).where(
                        MonitoringAlertEntity.company_id == shift.company_id,
                        MonitoringAlertEntity.factory_id == shift.factory_id,
                        MonitoringAlertEntity.machine_id.is_not(None),
                        MonitoringAlertEntity.severity
                        == MonitoringAlertSeverity.CRITICAL,
                        MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
                    )
                )
            ).scalar_one()
        )
        shift.status = ShiftStatus.ENDED
        shift.ended_by_user_id = actor.id
        shift.ended_at = now
        shift.handover_notes = handover_notes.strip()
        shift.unresolved_summary = (
            unresolved_summary.strip() if unresolved_summary else None
        )
        shift.snapshot = {
            "alerts_during_shift_count": alerts_during_shift,
            "completed_action_count": completed_actions,
            "critical_machine_count": critical_machines,
            "open_action_count": open_actions,
            "unresolved_alert_count": unresolved_alerts,
        }
        await self._session.commit()
        await self._session.refresh(shift)
        return shift

    async def acknowledge_shift(
        self, shift_id: UUID, *, actor: User, acknowledgement_note: str | None
    ) -> ShiftHandover:
        shift = await self.get_shift(shift_id, actor=actor)
        if shift.status is not ShiftStatus.ENDED:
            raise OperationsConflictError("Only an ended shift can be acknowledged.")
        shift.status = ShiftStatus.ACKNOWLEDGED
        shift.acknowledged_by_user_id = actor.id
        shift.acknowledged_at = utc_now()
        if acknowledgement_note and acknowledgement_note.strip():
            shift.snapshot = {
                **shift.snapshot,
                "acknowledgement_note": acknowledgement_note.strip(),
            }
        await self._session.commit()
        await self._session.refresh(shift)
        return shift

    async def _ensure_alert_source_timeline(self, alert: MonitoringAlertEntity) -> None:
        """Backfill safe source milestones when an alert enters operations."""

        if alert.factory_id is None or alert.machine_id is None:
            return
        existing_types = set(
            (
                await self._session.execute(
                    select(OperationalTimelineEvent.event_type).where(
                        OperationalTimelineEvent.company_id == alert.company_id,
                        OperationalTimelineEvent.alert_id == alert.id,
                        OperationalTimelineEvent.event_type.in_(
                            (
                                "prediction.completed",
                                "machine_risk.assessed",
                                "alert.created",
                            )
                        ),
                    )
                )
            ).scalars()
        )
        assessment = (
            await self._session.execute(
                select(MachineRiskAssessment)
                .where(
                    MachineRiskAssessment.company_id == alert.company_id,
                    MachineRiskAssessment.alert_id == alert.id,
                )
                .order_by(
                    MachineRiskAssessment.assessed_at.desc(),
                    MachineRiskAssessment.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        source_events: list[tuple[str, str, str, datetime, dict[str, object]]] = []
        if (
            assessment is not None
            and assessment.prediction_event_id is not None
            and "prediction.completed" not in existing_types
        ):
            source_events.append(
                (
                    "prediction.completed",
                    "Machine analysis completed",
                    "An approved model produced a machine-risk assessment.",
                    assessment.assessed_at,
                    {
                        "model_name": assessment.registered_model_name,
                        "model_version": assessment.model_version,
                        "prediction_event_id": str(assessment.prediction_event_id),
                    },
                )
            )
        if assessment is not None and "machine_risk.assessed" not in existing_types:
            source_events.append(
                (
                    "machine_risk.assessed",
                    "Machine risk assessed",
                    f"Machine state was assessed as {assessment.risk_state}.",
                    assessment.assessed_at,
                    {
                        "monitoring_status": assessment.monitoring_status,
                        "risk_state": assessment.risk_state,
                    },
                )
            )
        if "alert.created" not in existing_types:
            source_events.append(
                (
                    "alert.created",
                    "Operational alert created",
                    alert.safe_summary,
                    alert.first_detected_at,
                    {"severity": alert.severity.value},
                )
            )
        for event_type, title, detail, occurred_at, metadata in source_events:
            self._session.add(
                OperationalTimelineEvent(
                    company_id=alert.company_id,
                    factory_id=alert.factory_id,
                    machine_id=alert.machine_id,
                    alert_id=alert.id,
                    actor_user_id=None,
                    event_type=event_type,
                    title=title,
                    detail=detail[:2000],
                    safe_metadata=metadata,
                    occurred_at=occurred_at,
                )
            )
        if source_events:
            await self._session.flush()

    async def _timeline(
        self,
        *,
        actor: User,
        event_type: str,
        title: str,
        detail: str,
        occurred_at: datetime,
        action: OperationalAction | None = None,
        alert: MonitoringAlertEntity | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OperationalTimelineEvent:
        factory_id: UUID | None
        machine_id: UUID | None
        if action is not None:
            factory_id = action.factory_id
            machine_id = action.machine_id
        elif alert is not None:
            factory_id = alert.factory_id
            machine_id = alert.machine_id
        else:
            raise OperationsConflictError(
                "Operational timeline events require a parent."
            )
        if factory_id is None or machine_id is None:
            raise OperationsConflictError(
                "Operational timeline events require machine context."
            )
        event = OperationalTimelineEvent(
            company_id=actor.company_id,
            factory_id=factory_id,
            machine_id=machine_id,
            action_id=action.id if action else None,
            alert_id=alert.id if alert else None,
            actor_user_id=actor.id,
            event_type=event_type[:64],
            title=title[:255],
            detail=detail[:2000],
            safe_metadata=dict(metadata or {}),
            occurred_at=occurred_at,
        )
        self._session.add(event)
        await self._session.flush()
        return event
