"""Explicit provider registry for model trainers."""

from collections.abc import Callable
from dataclasses import dataclass

from app.ml.base import TrainerKey
from app.ml.factory.exceptions import (
    TrainerAlreadyRegisteredError,
    TrainerNotRegisteredError,
)

type TrainerProvider[TrainerT] = Callable[[], TrainerT]


@dataclass(frozen=True, slots=True)
class TrainerRegistration[TrainerT]:
    """Typed token pairing a composite key with its trainer provider."""

    key: TrainerKey
    provider: TrainerProvider[TrainerT]


class TrainerRegistry:
    """Store and resolve typed trainer tokens by composite identity."""

    def __init__(self) -> None:
        self._registrations: dict[TrainerKey, object] = {}

    def register[
        TrainerT
    ](self, registration: TrainerRegistration[TrainerT],) -> None:
        """Register one typed token and reject duplicate trainer keys."""
        key = registration.key
        if key in self._registrations:
            msg = f"Trainer registration already exists for '{key}'."
            raise TrainerAlreadyRegisteredError(msg)
        self._registrations[key] = registration

    def resolve[
        TrainerT
    ](
        self,
        registration: TrainerRegistration[TrainerT],
    ) -> TrainerRegistration[
        TrainerT
    ]:
        """Verify and return the active typed registration token."""
        key = registration.key
        try:
            stored_token = self._registrations[key]
        except KeyError as exc:
            msg = f"No trainer registration exists for '{key}'."
            raise TrainerNotRegisteredError(msg) from exc
        if stored_token is not registration:
            msg = f"Supplied trainer registration for '{key}' is not active."
            raise TrainerNotRegisteredError(msg)
        return registration

    def contains(self, key: TrainerKey) -> bool:
        """Return whether a composite key has a registered provider."""
        return key in self._registrations

    def registered_keys(self) -> tuple[TrainerKey, ...]:
        """Return registered keys in deterministic identity order."""
        return tuple(
            sorted(
                self._registrations,
                key=lambda key: (key.algorithm.value, key.task_type.value),
            ),
        )
