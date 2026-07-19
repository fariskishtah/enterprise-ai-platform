"""Fresh-instance factory for registered model trainers."""

from app.ml.base import BaseTrainer
from app.ml.factory.exceptions import (
    InvalidTrainerProviderError,
    TrainerKeyMismatchError,
)
from app.ml.factory.registry import TrainerRegistration, TrainerRegistry


class TrainerFactory:
    """Create validated trainer instances from an explicit registry."""

    def __init__(self, registry: TrainerRegistry) -> None:
        self._registry = registry

    def create[
        TrainerT
    ](self, registration: TrainerRegistration[TrainerT],) -> TrainerT:
        """Create a fresh trainer while preserving its concrete static type."""
        active_registration = self._registry.resolve(registration)
        created = active_registration.provider()
        if not isinstance(created, BaseTrainer):
            returned_type = type(created).__name__
            msg = (
                f"Trainer provider for '{registration.key}' returned "
                f"'{returned_type}', expected a BaseTrainer instance."
            )
            raise InvalidTrainerProviderError(msg)
        if created.key != registration.key:
            msg = (
                f"Trainer provider registered for '{registration.key}' created "
                f"a trainer for '{created.key}'."
            )
            raise TrainerKeyMismatchError(msg)
        return created
