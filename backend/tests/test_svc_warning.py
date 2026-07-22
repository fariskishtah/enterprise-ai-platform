"""SVC warning regression tests: SVC(probability=True) must not emit FutureWarning
or ConvergenceWarning during training or prediction on a simple dataset.
"""

import warnings

import numpy as np
import pytest
from app.ml.base import TrainerInput
from app.ml.plugins import PluginTrainer, create_default_plugin_registry


@pytest.fixture()
def classification_data() -> tuple[np.ndarray, np.ndarray]:
    """Balanced two-class dataset that is linearly separable."""
    rng = np.random.default_rng(42)
    features = rng.standard_normal((60, 4))
    features[:30] += 1.5
    features[30:] -= 1.5
    targets = np.array([0] * 30 + [1] * 30, dtype=np.int64)
    return features, targets


def test_svc_trains_without_future_warning(
    classification_data: tuple[np.ndarray, np.ndarray],
) -> None:
    """SVC with probability=True must not raise FutureWarning or ConvergenceWarning."""
    plugin = create_default_plugin_registry().get("svm_classification")
    trainer = PluginTrainer(plugin)
    features, targets = classification_data

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        warnings.simplefilter("error", DeprecationWarning)
        # ConvergenceWarning is in sklearn.exceptions — check module path.
        try:
            from sklearn.exceptions import ConvergenceWarning  # type: ignore

            warnings.simplefilter("error", ConvergenceWarning)
        except ImportError:
            pass

        output = trainer.fit(
            TrainerInput(
                features=features,
                targets=targets,
                hyperparameters={
                    "__scaler": "standard",
                    "__imputer": "median",
                },
                random_seed=42,
            )
        )

    # Model must produce valid predictions.
    preds = trainer.predict(output.model, features[:5])
    assert preds.shape == (5,)
    assert all(p in (0, 1) for p in preds)


def test_svc_predict_proba_returns_valid_probabilities(
    classification_data: tuple[np.ndarray, np.ndarray],
) -> None:
    """SVC pipeline must expose predict_proba with values in [0, 1] summing to 1."""
    plugin = create_default_plugin_registry().get("svm_classification")
    trainer = PluginTrainer(plugin)
    features, targets = classification_data

    output = trainer.fit(
        TrainerInput(
            features=features,
            targets=targets,
            hyperparameters={"__scaler": "standard"},
            random_seed=42,
        )
    )

    # Must expose predict_proba.
    assert hasattr(output.model, "predict_proba")

    proba = output.model.predict_proba(features[:10])
    assert proba.shape == (10, 2)

    # All values in [0, 1].
    assert np.all(proba >= 0)
    assert np.all(proba <= 1 + 1e-6)

    # Rows sum to approximately 1.
    row_sums = proba.sum(axis=1)
    assert np.allclose(row_sums, 1.0, atol=0.01)

    # All finite.
    assert np.all(np.isfinite(proba))


def test_svc_with_rbf_kernel_trains_and_predicts(
    classification_data: tuple[np.ndarray, np.ndarray],
) -> None:
    """SVC with rbf kernel (default) should train without warning on small data."""
    plugin = create_default_plugin_registry().get("svm_classification")
    trainer = PluginTrainer(plugin)
    features, targets = classification_data

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        try:
            from sklearn.exceptions import ConvergenceWarning  # type: ignore

            warnings.simplefilter("error", ConvergenceWarning)
        except ImportError:
            pass

        output = trainer.fit(
            TrainerInput(
                features=features,
                targets=targets,
                hyperparameters={"kernel": "rbf", "C": 1.0},
                random_seed=7,
            )
        )

    preds = trainer.predict(output.model, features[:5])
    assert preds.shape == (5,)


def test_svc_regression_plugin_trains_without_warning() -> None:
    """SVM regression plugin (SVR) should also train without FutureWarning."""
    from app.ml.base import TrainerInput as TI

    plugin = create_default_plugin_registry().get("svm_regression")
    trainer = PluginTrainer(plugin)
    rng = np.random.default_rng(0)
    features = rng.standard_normal((40, 3))
    targets = 3.0 * features[:, 0] - features[:, 1] + rng.standard_normal(40) * 0.1

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        output = trainer.fit(
            TI(
                features=features,
                targets=targets,
                hyperparameters={},
                random_seed=0,
            )
        )

    preds = trainer.predict(output.model, features[:5])
    assert preds.shape == (5,)
    assert np.all(np.isfinite(preds))


def test_svc_with_small_dataset() -> None:
    """SVC with classes having fewer than 5 samples should calibrate safely if >= 2."""
    plugin = create_default_plugin_registry().get("svm_classification")
    trainer = PluginTrainer(plugin)

    # Create dataset with exactly 3 samples in class 1
    features = np.random.RandomState(0).standard_normal((10, 4))
    targets = np.array([0, 0, 0, 0, 0, 0, 0, 1, 1, 1], dtype=np.int64)

    output = trainer.fit(
        TrainerInput(
            features=features,
            targets=targets,
            hyperparameters={"kernel": "rbf", "C": 1.0},
            random_seed=7,
        )
    )

    preds = trainer.predict(output.model, features)
    assert preds.shape == (10,)

    proba = output.model.predict_proba(features)
    assert proba.shape == (10, 2)
    assert np.all(proba >= 0)
    assert np.all(proba <= 1)


def test_svc_with_insufficient_samples() -> None:
    """SVC with a class having < 2 samples should raise ModelPluginError."""
    from app.ml.plugins.core import ModelPluginError

    plugin = create_default_plugin_registry().get("svm_classification")
    trainer = PluginTrainer(plugin)

    # Create dataset with exactly 1 sample in class 1
    features = np.random.RandomState(0).standard_normal((10, 4))
    targets = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 1], dtype=np.int64)

    with pytest.raises(ModelPluginError, match="requires at least 2 samples"):
        trainer.fit(
            TrainerInput(
                features=features,
                targets=targets,
                hyperparameters={"kernel": "rbf", "C": 1.0},
                random_seed=7,
            )
        )
