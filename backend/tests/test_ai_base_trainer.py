"""AI Core trainer contract tests."""

from dataclasses import FrozenInstanceError, dataclass, fields

import app.ml.base as trainer_contracts
import pytest
from app.ml.base import BaseTrainer, TrainerInput, TrainerKey, TrainerOutput
from app.ml.domain import AlgorithmType, TaskType

type FeatureMatrix = tuple[tuple[float, ...], ...]
type TargetVector = tuple[float, ...]
type PredictionVector = tuple[float, ...]

FEATURES: FeatureMatrix = ((1.0, 2.0), (3.0, 4.0))
TARGETS: TargetVector = (0.25, 0.75)
FAKE_TRAINER_KEY = TrainerKey(
    algorithm=AlgorithmType.RANDOM_FOREST,
    task_type=TaskType.REGRESSION,
)


@dataclass(frozen=True, slots=True)
class FakeModel:
    """Small trained model used by the typed fake trainer."""

    prediction: float

    def predict(self, features: FeatureMatrix, /) -> PredictionVector:
        """Return one constant raw prediction per feature row."""
        return tuple(self.prediction for _ in features)


class FakeTrainer(
    BaseTrainer[FeatureMatrix, TargetVector, FakeModel, PredictionVector],
):
    """Typed trainer implementation used to exercise the abstract contract."""

    @property
    def key(self) -> TrainerKey:
        """Return the composite identity represented by this fake trainer."""
        return FAKE_TRAINER_KEY

    def fit(
        self,
        trainer_input: TrainerInput[FeatureMatrix, TargetVector],
    ) -> TrainerOutput[FakeModel]:
        """Build a deterministic fake model from prepared targets."""
        return TrainerOutput(
            model=FakeModel(prediction=trainer_input.targets[0]),
            training_duration_seconds=0.5,
        )

    def predict(
        self,
        model: FakeModel,
        features: FeatureMatrix,
    ) -> PredictionVector:
        """Delegate raw prediction to the fitted fake model."""
        return model.predict(features)


class IncompleteTrainer(
    BaseTrainer[FeatureMatrix, TargetVector, FakeModel, PredictionVector],
):
    """Trainer intentionally missing fit and predict implementations."""

    @property
    def key(self) -> TrainerKey:
        """Return the fake trainer's supported composite identity."""
        return FAKE_TRAINER_KEY


def _assign_attribute(
    instance: object,
    attribute_name: str,
    value: object,
) -> None:
    setattr(instance, attribute_name, value)


def test_trainer_input_stores_prepared_data() -> None:
    """Trainer input retains prepared features, targets, and configuration."""
    trainer_input = TrainerInput[FeatureMatrix, TargetVector](
        features=FEATURES,
        targets=TARGETS,
        hyperparameters={"max_depth": 4},
        random_seed=42,
    )

    assert trainer_input.features == FEATURES
    assert trainer_input.targets == TARGETS
    assert trainer_input.hyperparameters["max_depth"] == 4
    assert trainer_input.random_seed == 42


def test_trainer_input_is_immutable() -> None:
    """Trainer input fields cannot be reassigned after construction."""
    trainer_input = TrainerInput[FeatureMatrix, TargetVector](
        features=FEATURES,
        targets=TARGETS,
        hyperparameters={},
    )

    with pytest.raises(FrozenInstanceError):
        _assign_attribute(trainer_input, "random_seed", 7)


def test_trainer_output_stores_typed_model() -> None:
    """Trainer output retains the concrete fitted model type."""
    model = FakeModel(prediction=0.5)
    output = TrainerOutput[FakeModel](
        model=model,
        training_duration_seconds=1.25,
    )

    assert output.model is model
    assert output.training_duration_seconds == 1.25


def test_trainer_output_rejects_negative_duration() -> None:
    """Raw trainer output rejects negative training durations."""
    with pytest.raises(ValueError, match="greater than or equal to zero"):
        TrainerOutput(
            model=FakeModel(prediction=0.5),
            training_duration_seconds=-0.01,
        )


def test_trainer_output_accepts_zero_duration() -> None:
    """Zero is a valid training duration."""
    output = TrainerOutput(
        model=FakeModel(prediction=0.5),
        training_duration_seconds=0.0,
    )

    assert output.training_duration_seconds == 0.0


def test_trainer_output_is_immutable() -> None:
    """Trainer output fields cannot be reassigned after construction."""
    output = TrainerOutput(
        model=FakeModel(prediction=0.5),
        training_duration_seconds=1.0,
    )

    with pytest.raises(FrozenInstanceError):
        _assign_attribute(output, "training_duration_seconds", 2.0)


def test_fake_trainer_subclasses_base_trainer() -> None:
    """A concrete implementation can inherit from the abstract trainer."""
    assert isinstance(FakeTrainer(), BaseTrainer)


def test_trainer_key_is_immutable() -> None:
    """Composite trainer identity cannot change after construction."""
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(FAKE_TRAINER_KEY, "task_type", TaskType.CLASSIFICATION)


def test_fake_trainer_exposes_supported_key() -> None:
    """A concrete trainer identifies its supported algorithm and task."""
    trainer = FakeTrainer()

    assert trainer.key == FAKE_TRAINER_KEY
    assert trainer.key.algorithm is AlgorithmType.RANDOM_FOREST
    assert trainer.key.task_type is TaskType.REGRESSION


def test_fake_trainer_fits_and_returns_raw_output() -> None:
    """A concrete trainer fits prepared data and returns only raw output."""
    trainer = FakeTrainer()
    trainer_input = TrainerInput[FeatureMatrix, TargetVector](
        features=FEATURES,
        targets=TARGETS,
        hyperparameters={},
        random_seed=None,
    )

    output = trainer.fit(trainer_input)

    assert isinstance(output, TrainerOutput)
    assert isinstance(output.model, FakeModel)
    assert output.model.prediction == TARGETS[0]


def test_fake_trainer_performs_raw_prediction() -> None:
    """A concrete trainer predicts with an already fitted model."""
    trainer = FakeTrainer()

    predictions = trainer.predict(FakeModel(prediction=0.75), FEATURES)

    assert predictions == (0.75, 0.75)


def test_base_trainer_cannot_be_instantiated() -> None:
    """The abstract trainer contract cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseTrainer[
            FeatureMatrix,
            TargetVector,
            FakeModel,
            PredictionVector,
        ]()  # type: ignore[abstract]


def test_base_trainer_has_only_the_clean_abstract_contract() -> None:
    """Identity, fitting, and raw prediction are its only responsibilities."""
    assert BaseTrainer.__abstractmethods__ == frozenset({"key", "fit", "predict"})


def test_incomplete_trainer_cannot_be_instantiated() -> None:
    """Subclasses must implement every abstract trainer operation."""
    with pytest.raises(TypeError):
        IncompleteTrainer()  # type: ignore[abstract]


def test_public_trainer_contract_exports() -> None:
    """The base package exposes its complete intended public API."""
    assert trainer_contracts.__all__ == [
        "BaseTrainer",
        "TrainerKey",
        "TrainerInput",
        "TrainerOutput",
    ]
    assert BaseTrainer.__name__ == "BaseTrainer"
    assert TrainerKey.__name__ == "TrainerKey"
    assert TrainerInput.__name__ == "TrainerInput"
    assert TrainerOutput.__name__ == "TrainerOutput"


def test_trainer_output_contains_only_raw_fit_result_fields() -> None:
    """Workflow, evaluation, and infrastructure fields stay out of output."""
    assert {field.name for field in fields(TrainerOutput)} == {
        "model",
        "training_duration_seconds",
    }
