"""Public registration and factory API for AI Core trainers."""

from app.ml.factory.exceptions import (
    InvalidTrainerProviderError,
    TrainerAlgorithmMismatchError,
    TrainerAlreadyRegisteredError,
    TrainerFactoryError,
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
    "TrainerAlgorithmMismatchError",
    "TrainerAlreadyRegisteredError",
    "TrainerFactory",
    "TrainerFactoryError",
    "TrainerNotRegisteredError",
    "TrainerProvider",
    "TrainerRegistration",
    "TrainerRegistry",
]
