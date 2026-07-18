"""Public contracts for AI Core model trainers."""

from app.ml.base.identity import TrainerKey
from app.ml.base.trainer import BaseTrainer
from app.ml.base.types import TrainerInput, TrainerOutput

__all__ = [
    "BaseTrainer",
    "TrainerKey",
    "TrainerInput",
    "TrainerOutput",
]
