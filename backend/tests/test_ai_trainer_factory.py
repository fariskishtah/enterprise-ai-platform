"""AI Core trainer registry and factory tests."""

import ast
import inspect
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing import assert_type

import app.ml.factory as factory_contracts
import pytest
from app.ml.base import BaseTrainer, TrainerInput, TrainerOutput
from app.ml.domain import AlgorithmType
from app.ml.factory import (
    InvalidTrainerProviderError,
    TrainerAlgorithmMismatchError,
    TrainerAlreadyRegisteredError,
    TrainerFactory,
    TrainerFactoryError,
    TrainerNotRegisteredError,
    TrainerRegistration,
    TrainerRegistry,
)

type FeatureMatrix = tuple[tuple[float, ...], ...]
type TargetVector = tuple[float, ...]
type PredictionVector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class FakeModel:
    """Small fitted model used by the typed fake trainer."""

    prediction: float


class FakeTrainer(
    BaseTrainer[FeatureMatrix, TargetVector, FakeModel, PredictionVector],
):
    """Strictly typed trainer used to exercise heterogeneous registration."""

    @property
    def algorithm(self) -> AlgorithmType:
        """Return the fake trainer's supported algorithm."""
        return AlgorithmType.RANDOM_FOREST

    def fit(
        self,
        trainer_input: TrainerInput[FeatureMatrix, TargetVector],
    ) -> TrainerOutput[FakeModel]:
        """Create a fake model from prepared target data."""
        return TrainerOutput(
            model=FakeModel(prediction=trainer_input.targets[0]),
            training_duration_seconds=0.0,
        )

    def predict(
        self,
        model: FakeModel,
        features: FeatureMatrix,
    ) -> PredictionVector:
        """Return one constant raw prediction per feature row."""
        return tuple(model.prediction for _ in features)


class MismatchedTrainer(FakeTrainer):
    """Trainer whose identity intentionally differs from its registration."""

    @property
    def algorithm(self) -> AlgorithmType:
        """Return an algorithm that will not match the registry key."""
        return AlgorithmType.RANDOM_FOREST


class ProviderConstructionError(RuntimeError):
    """Sentinel exception raised by a failing provider."""


def create_fake_trainer() -> FakeTrainer:
    """Return a new typed fake trainer."""
    return FakeTrainer()


def create_mismatched_trainer() -> MismatchedTrainer:
    """Return a trainer with the wrong algorithm identity."""
    return MismatchedTrainer()


def create_invalid_trainer() -> object:
    """Return an object that is not a BaseTrainer."""
    return object()


def raise_during_construction() -> FakeTrainer:
    """Raise a provider-specific construction error."""
    raise ProviderConstructionError("constructor failed")


FAKE_REGISTRATION = TrainerRegistration(
    algorithm=AlgorithmType.RANDOM_FOREST,
    provider=create_fake_trainer,
)
MISMATCHED_REGISTRATION = TrainerRegistration(
    algorithm=AlgorithmType.XGBOOST,
    provider=create_mismatched_trainer,
)
INVALID_REGISTRATION = TrainerRegistration(
    algorithm=AlgorithmType.CATBOOST,
    provider=create_invalid_trainer,
)
FAILING_REGISTRATION = TrainerRegistration(
    algorithm=AlgorithmType.LIGHTGBM,
    provider=raise_during_construction,
)

assert_type(FAKE_REGISTRATION, TrainerRegistration[FakeTrainer])


def _assign_attribute(
    instance: object,
    attribute_name: str,
    value: object,
) -> None:
    setattr(instance, attribute_name, value)


def test_typed_registration_is_immutable() -> None:
    """Registration tokens preserve configuration after construction."""
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(FAKE_REGISTRATION, "algorithm", AlgorithmType.CATBOOST)


def test_registry_registers_and_resolves_typed_token() -> None:
    """An explicitly registered token is resolved with its concrete type."""
    registry = TrainerRegistry()

    registry.register(FAKE_REGISTRATION)

    resolved = registry.resolve(FAKE_REGISTRATION)
    assert_type(resolved, TrainerRegistration[FakeTrainer])
    assert resolved is FAKE_REGISTRATION


def test_registry_contains_reports_registration_state() -> None:
    """Registry membership reflects explicit registration."""
    registry = TrainerRegistry()

    assert registry.contains(AlgorithmType.RANDOM_FOREST) is False

    registry.register(FAKE_REGISTRATION)

    assert registry.contains(AlgorithmType.RANDOM_FOREST) is True


def test_registered_algorithms_are_deterministic() -> None:
    """Registered algorithms are sorted independently of insertion order."""
    registry = TrainerRegistry()
    registry.register(MISMATCHED_REGISTRATION)
    registry.register(FAKE_REGISTRATION)

    assert registry.registered_algorithms() == (
        AlgorithmType.RANDOM_FOREST,
        AlgorithmType.XGBOOST,
    )


def test_registered_algorithms_do_not_expose_mutable_registry_state() -> None:
    """The registry exposes an immutable snapshot rather than its dictionary."""
    registry = TrainerRegistry()
    registry.register(FAKE_REGISTRATION)

    algorithms = registry.registered_algorithms()
    extended_algorithms = algorithms + (AlgorithmType.CATBOOST,)

    assert isinstance(algorithms, tuple)
    assert extended_algorithms != registry.registered_algorithms()
    assert registry.registered_algorithms() == (AlgorithmType.RANDOM_FOREST,)


def test_duplicate_registration_raises_dedicated_exception() -> None:
    """An algorithm cannot be registered more than once."""
    registry = TrainerRegistry()
    registry.register(FAKE_REGISTRATION)

    with pytest.raises(
        TrainerAlreadyRegisteredError,
        match="already exists for 'random_forest'",
    ):
        registry.register(FAKE_REGISTRATION)


def test_missing_registration_raises_dedicated_exception() -> None:
    """Resolving an unsupported algorithm fails deterministically."""
    registry = TrainerRegistry()

    with pytest.raises(
        TrainerNotRegisteredError,
        match="No trainer registration exists for 'lightgbm'",
    ):
        registry.resolve(FAILING_REGISTRATION)


def test_registry_rejects_inactive_token_for_registered_algorithm() -> None:
    """A different token cannot impersonate the active registration."""
    registry = TrainerRegistry()
    registry.register(FAKE_REGISTRATION)
    different_token = TrainerRegistration(
        algorithm=AlgorithmType.RANDOM_FOREST,
        provider=create_fake_trainer,
    )

    with pytest.raises(TrainerNotRegisteredError, match="is not active"):
        registry.resolve(different_token)


def test_factory_creates_registered_trainer() -> None:
    """The factory creates a BaseTrainer from a registered provider."""
    registry = TrainerRegistry()
    registry.register(FAKE_REGISTRATION)

    created = TrainerFactory(registry).create(FAKE_REGISTRATION)

    assert_type(created, FakeTrainer)
    assert isinstance(created, FakeTrainer)


def test_factory_creates_distinct_instances() -> None:
    """Each factory call invokes the provider and returns a fresh instance."""
    registry = TrainerRegistry()
    registry.register(FAKE_REGISTRATION)
    factory = TrainerFactory(registry)

    first = factory.create(FAKE_REGISTRATION)
    second = factory.create(FAKE_REGISTRATION)

    assert first is not second


def test_created_trainer_exposes_requested_algorithm() -> None:
    """A created trainer identifies the algorithm requested from the factory."""
    registry = TrainerRegistry()
    registry.register(FAKE_REGISTRATION)

    created = TrainerFactory(registry).create(FAKE_REGISTRATION)

    assert created.algorithm is AlgorithmType.RANDOM_FOREST


def test_factory_rejects_non_trainer_provider_result() -> None:
    """Providers must return BaseTrainer instances."""
    registry = TrainerRegistry()
    registry.register(INVALID_REGISTRATION)

    with pytest.raises(
        InvalidTrainerProviderError,
        match="returned 'object', expected a BaseTrainer instance",
    ):
        TrainerFactory(registry).create(INVALID_REGISTRATION)


def test_factory_rejects_algorithm_mismatch() -> None:
    """Provider output must match its registered algorithm key."""
    registry = TrainerRegistry()
    registry.register(MISMATCHED_REGISTRATION)

    with pytest.raises(
        TrainerAlgorithmMismatchError,
        match="registered for 'xgboost'.*trainer for 'random_forest'",
    ):
        TrainerFactory(registry).create(MISMATCHED_REGISTRATION)


def test_provider_constructor_exception_propagates() -> None:
    """The factory does not hide provider construction failures."""
    registry = TrainerRegistry()
    registry.register(FAILING_REGISTRATION)

    with pytest.raises(ProviderConstructionError, match="constructor failed"):
        TrainerFactory(registry).create(FAILING_REGISTRATION)


def test_factory_package_public_exports() -> None:
    """The factory package exposes only its intended public API."""
    assert factory_contracts.__all__ == [
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
    assert issubclass(InvalidTrainerProviderError, TrainerFactoryError)
    assert issubclass(TrainerAlgorithmMismatchError, TrainerFactoryError)
    assert issubclass(TrainerAlreadyRegisteredError, TrainerFactoryError)
    assert issubclass(TrainerNotRegisteredError, TrainerFactoryError)


def test_factory_package_has_no_concrete_algorithm_imports() -> None:
    """The factory core remains independent of concrete ML libraries."""
    factory_dir = Path(__file__).parents[1] / "app" / "ml" / "factory"
    imported_modules: set[str] = set()
    for module_path in factory_dir.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

    forbidden_modules = ("sklearn", "xgboost", "lightgbm", "catboost")

    assert not any(
        imported.startswith(forbidden)
        for imported in imported_modules
        for forbidden in forbidden_modules
    )


def test_factory_package_has_no_unsound_erased_trainer_or_any() -> None:
    """Public typing does not widen invariant BaseTrainer specializations."""
    factory_dir = Path(__file__).parents[1] / "app" / "ml" / "factory"
    source = "\n".join(
        module_path.read_text(encoding="utf-8")
        for module_path in factory_dir.glob("*.py")
    )
    tree = ast.parse(source)

    assert "ErasedTrainer" not in source
    assert "BaseTrainer[object" not in source
    assert not any(
        isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(tree)
    )


def test_typed_fake_trainer_crosses_registration_boundary() -> None:
    """A fully typed trainer provider remains registerable and creatable."""
    registry = TrainerRegistry()
    registry.register(FAKE_REGISTRATION)

    created = TrainerFactory(registry).create(FAKE_REGISTRATION)

    assert_type(created, FakeTrainer)
    assert isinstance(created, FakeTrainer)
    trainer_input = TrainerInput[FeatureMatrix, TargetVector](
        features=((1.0, 2.0),),
        targets=(0.75,),
        hyperparameters={},
    )
    output = created.fit(trainer_input)
    assert output.model.prediction == 0.75
    assert created.predict(output.model, trainer_input.features) == (0.75,)


def test_base_trainer_remains_abstract() -> None:
    """The existing typed trainer contract remains abstract and unchanged."""
    assert inspect.isabstract(BaseTrainer)
