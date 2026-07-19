"""Public registration and factory API for AI Core trainers."""

from app.ml.factory.exceptions import (
    InvalidTrainerProviderError,
    TrainerAlreadyRegisteredError,
    TrainerFactoryError,
    TrainerKeyMismatchError,
    TrainerNotRegisteredError,
)
from app.ml.factory.factory import TrainerFactory
from app.ml.factory.registry import (
    TrainerProvider,
    TrainerRegistration,
    TrainerRegistry,
)

__all__ = [
    "InvalidTrainerProviderError",
    "TrainerAlreadyRegisteredError",
    "TrainerFactory",
    "TrainerFactoryError",
    "TrainerKeyMismatchError",
    "TrainerNotRegisteredError",
    "TrainerProvider",
    "TrainerRegistration",
    "TrainerRegistry",
]
