"""Explicit provider registry for model trainers."""

from collections.abc import Callable
from dataclasses import dataclass

from app.ml.domain import AlgorithmType
from app.ml.factory.exceptions import (
    TrainerAlreadyRegisteredError,
    TrainerNotRegisteredError,
)

type TrainerProvider[TrainerT] = Callable[[], TrainerT]


@dataclass(frozen=True, slots=True)
class TrainerRegistration[TrainerT]:
    """Typed token pairing an algorithm with its trainer provider."""

    algorithm: AlgorithmType
    provider: TrainerProvider[TrainerT]


@dataclass(frozen=True, slots=True)
class _StoredRegistration:
    """Privately erased registration used for heterogeneous storage."""

    algorithm: AlgorithmType
    provider: TrainerProvider[object]
    token: object


class TrainerRegistry:
    """Store and resolve trainer providers by supported algorithm."""

    def __init__(self) -> None:
        self._registrations: dict[AlgorithmType, _StoredRegistration] = {}

    def register[
        TrainerT
    ](self, registration: TrainerRegistration[TrainerT],) -> None:
        """Register one typed token and reject duplicate algorithm keys."""
        algorithm = registration.algorithm
        if algorithm in self._registrations:
            msg = f"Trainer registration already exists for '{algorithm.value}'."
            raise TrainerAlreadyRegisteredError(msg)
        self._registrations[algorithm] = _StoredRegistration(
            algorithm=algorithm,
            provider=registration.provider,
            token=registration,
        )

    def resolve[
        TrainerT
    ](
        self,
        registration: TrainerRegistration[TrainerT],
    ) -> TrainerRegistration[
        TrainerT
    ]:
        """Verify and return the active typed registration token."""
        algorithm = registration.algorithm
        try:
            stored = self._registrations[algorithm]
        except KeyError as exc:
            msg = f"No trainer registration exists for '{algorithm.value}'."
            raise TrainerNotRegisteredError(msg) from exc
        if stored.token is not registration:
            msg = (
                f"Supplied trainer registration for '{algorithm.value}' is not active."
            )
            raise TrainerNotRegisteredError(msg)
        return registration

    def contains(self, algorithm: AlgorithmType) -> bool:
        """Return whether an algorithm has a registered provider."""
        return algorithm in self._registrations

    def registered_algorithms(self) -> tuple[AlgorithmType, ...]:
        """Return registered algorithms in deterministic value order."""
        return tuple(
            sorted(self._registrations, key=lambda algorithm: algorithm.value),
        )
