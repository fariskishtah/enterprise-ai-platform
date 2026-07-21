"""Public model-plugin architecture."""

from app.ml.plugins.core import (
    DuplicateModelPluginError,
    FeatureArray,
    ModelPlugin,
    ModelPluginError,
    ModelPluginRegistry,
    ParameterDefinition,
    PluginMetricsEngine,
    PluginMetricsReport,
    PluginTrainer,
    PreprocessingOptions,
    UnknownModelPluginError,
    create_default_plugin_registry,
)

__all__ = [
    "DuplicateModelPluginError",
    "FeatureArray",
    "ModelPlugin",
    "ModelPluginError",
    "ModelPluginRegistry",
    "ParameterDefinition",
    "PluginMetricsEngine",
    "PluginMetricsReport",
    "PluginTrainer",
    "PreprocessingOptions",
    "UnknownModelPluginError",
    "create_default_plugin_registry",
]
