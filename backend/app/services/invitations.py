"""Tenant-safe team invitation lifecycle."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.models.user import TeamInvitation, User, UserRole
from app.permissions import Permission, has_permissions
from app.repositories.users import UserRepository
from app.services.exceptions import (
    InvalidInvitationTokenError,
    InvitationLifecycleError,
)
from app.services.users import UserService
from app.utils.security import as_utc, hash_token, normalize_email, utc_now


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation: TeamInvitation
    token: str
    cooldown_seconds: int


class InvitationService:
    """Create, resend, revoke, and consume company-bound invitations."""

    def __init__(self, *, repository: UserRepository, users: UserService) -> None:
        self._repository = repository
        self._users = users

    @staticmethod
    def _authorize_role(actor: User, role: UserRole) -> None:
        if not has_permissions(actor.role, Permission.TEAM_MANAGE):
            raise InvitationLifecycleError("Team management permission is required.")
        if role is UserRole.OWNER and not has_permissions(
            actor.role, Permission.OWNER_ASSIGN
        ):
            raise InvitationLifecycleError("Only an owner can invite another owner.")

    async def create(
        self,
        *,
        actor: User,
        email: str,
        role: UserRole,
        expiry_hours: int,
        cooldown_seconds: int,
    ) -> IssuedInvitation:
        self._authorize_role(actor, role)
        invited_email = normalize_email(email)
        now = utc_now()
        if await self._repository.active_invitation_for_email(
            company_id=actor.company_id,
            invited_email=invited_email,
            now=now,
        ):
            raise InvitationLifecycleError(
                "An active invitation already exists for this email."
            )
        token = secrets.token_urlsafe(48)
        invitation = await self._repository.create_invitation(
            company_id=actor.company_id,
            invited_email=invited_email,
            role=role,
            token_hash=hash_token(token),
            inviter_user_id=actor.id,
            expires_at=now + timedelta(hours=expiry_hours),
            sent_at=now,
        )
        await self._repository.commit()
        return IssuedInvitation(invitation, token, cooldown_seconds)

    async def list_pending(
        self, *, actor: User, limit: int, offset: int
    ) -> tuple[list[TeamInvitation], int]:
        if not has_permissions(actor.role, Permission.TEAM_VIEW):
            raise InvitationLifecycleError("Team view permission is required.")
        return await self._repository.list_invitations(
            company_id=actor.company_id, limit=limit, offset=offset
        )

    async def resend(
        self,
        *,
        actor: User,
        invitation_id: UUID,
        expiry_hours: int,
        cooldown_seconds: int,
    ) -> IssuedInvitation:
        invitation = await self._repository.get_invitation_in_company(
            invitation_id=invitation_id,
            company_id=actor.company_id,
            for_update=True,
        )
        if invitation is None:
            raise InvitationLifecycleError("Invitation not found.")
        self._authorize_role(actor, invitation.role)
        if invitation.accepted_at is not None:
            raise InvitationLifecycleError("Invitation has already been accepted.")
        if invitation.revoked_at is not None:
            raise InvitationLifecycleError("Invitation has been revoked.")
        now = utc_now()
        available_at = as_utc(invitation.last_sent_at) + timedelta(
            seconds=cooldown_seconds
        )
        if available_at > now:
            remaining = max(int((available_at - now).total_seconds()) + 1, 1)
            raise InvitationLifecycleError(
                f"Invitation can be resent in {remaining} seconds."
            )
        token = secrets.token_urlsafe(48)
        invitation.token_hash = hash_token(token)
        invitation.expires_at = now + timedelta(hours=expiry_hours)
        invitation.last_sent_at = now
        invitation.send_count += 1
        await self._repository.commit()
        return IssuedInvitation(invitation, token, cooldown_seconds)

    async def revoke(self, *, actor: User, invitation_id: UUID) -> TeamInvitation:
        invitation = await self._repository.get_invitation_in_company(
            invitation_id=invitation_id,
            company_id=actor.company_id,
            for_update=True,
        )
        if invitation is None:
            raise InvitationLifecycleError("Invitation not found.")
        self._authorize_role(actor, invitation.role)
        if invitation.accepted_at is not None:
            raise InvitationLifecycleError("Invitation has already been accepted.")
        if invitation.revoked_at is not None:
            raise InvitationLifecycleError("Invitation has already been revoked.")
        invitation.revoked_at = utc_now()
        await self._repository.commit()
        return invitation

    async def accept(
        self, *, token: str, full_name: str | None, password: str | None
    ) -> tuple[TeamInvitation, User, bool]:
        invitation = await self._repository.get_invitation_by_token_hash(
            hash_token(token)
        )
        if invitation is None:
            raise InvalidInvitationTokenError("Invitation token is invalid.")
        if invitation.accepted_at is not None:
            raise InvitationLifecycleError("Invitation has already been accepted.")
        if invitation.revoked_at is not None:
            raise InvitationLifecycleError("Invitation has been revoked.")
        now = utc_now()
        if as_utc(invitation.expires_at) <= now:
            raise InvitationLifecycleError("Invitation has expired.")
        inviter = await self._repository.get_by_id_in_company(
            invitation.inviter_user_id, invitation.company_id
        )
        if inviter is None or not inviter.is_active:
            raise InvitationLifecycleError("Invitation is no longer authorized.")
        self._authorize_role(inviter, invitation.role)
        user = await self._repository.get_by_email(invitation.invited_email)
        created = user is None
        if user is not None and user.company_id != invitation.company_id:
            raise InvitationLifecycleError(
                "This account cannot accept an invitation for another company."
            )
        if user is not None and not user.is_active:
            raise InvitationLifecycleError(
                "An inactive account must be reactivated by a team manager."
            )
        if user is not None and user.role is UserRole.OWNER:
            if inviter.role is not UserRole.OWNER:
                raise InvitationLifecycleError("Only an owner can manage owners.")
            if (
                invitation.role is not UserRole.OWNER
                and await self._repository.count_active_owners(invitation.company_id)
                <= 1
            ):
                raise InvitationLifecycleError(
                    "The last active owner cannot be removed."
                )
        if user is None:
            if password is None:
                raise InvitationLifecycleError(
                    "A password is required to create the invited account."
                )
            user = await self._users.create_user(
                email=invitation.invited_email,
                password=password,
                full_name=full_name,
                role=invitation.role,
                company_id=invitation.company_id,
                commit=False,
            )
        else:
            user.role = invitation.role
        user.is_email_verified = True
        user.email_verified_at = user.email_verified_at or now
        invitation.accepted_at = now
        invitation.accepted_by_user_id = user.id
        await self._repository.commit()
        await self._repository.refresh_user(user)
        return invitation, user, created
