"""Abstract contract implemented by algorithm-specific trainers."""

from abc import ABC, abstractmethod

from app.ml.base.identity import TrainerKey
from app.ml.base.types import TrainerInput, TrainerOutput


class BaseTrainer[
    FeaturesT,
    TargetsT,
    ModelT,
    RawPredictionT,
](ABC):
    """Typed interface for fitting one algorithm and making raw predictions."""

    @property
    @abstractmethod
    def key(self) -> TrainerKey:
        """Return the composite identity implemented by this trainer."""

    @abstractmethod
    def fit(
        self,
        trainer_input: TrainerInput[FeaturesT, TargetsT],
    ) -> TrainerOutput[ModelT]:
        """Fit and return a prediction-capable model."""

    @abstractmethod
    def predict(
        self,
        model: ModelT,
        features: FeaturesT,
    ) -> RawPredictionT:
        """Return raw predictions from an already fitted model."""
