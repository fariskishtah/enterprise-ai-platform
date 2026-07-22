"""Immutable typed search spaces for allowlisted model plugins."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from app.ml.domain import TaskType

SafeName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    ),
]
SafeChoice = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    ),
]
type SearchScalar = StrictBool | StrictInt | FiniteFloat | SafeChoice


class SearchParameterKind(StrEnum):
    """Supported dependency-free search parameter families."""

    INTEGER = "integer"
    FLOAT = "float"
    CATEGORICAL = "categorical"


class IntegerSearchParameter(BaseModel):
    """A bounded integer grid."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: SafeName
    kind: Literal[SearchParameterKind.INTEGER] = SearchParameterKind.INTEGER
    low: StrictInt
    high: StrictInt
    step: StrictInt = Field(default=1, gt=0)
    default: StrictInt
    log_scale: Literal[False] = False

    @model_validator(mode="after")
    def validate_grid(self) -> IntegerSearchParameter:
        if self.low > self.high:
            raise ValueError("Integer search-space low must not exceed high.")
        if not self.low <= self.default <= self.high:
            raise ValueError("Integer search-space default must be within bounds.")
        if (self.default - self.low) % self.step:
            raise ValueError("Integer search-space default must align with step.")
        return self


class FloatSearchParameter(BaseModel):
    """A bounded finite float interval or grid."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: SafeName
    kind: Literal[SearchParameterKind.FLOAT] = SearchParameterKind.FLOAT
    low: FiniteFloat
    high: FiniteFloat
    step: FiniteFloat | None = Field(default=None, gt=0)
    default: FiniteFloat
    log_scale: bool = False

    @model_validator(mode="after")
    def validate_interval(self) -> FloatSearchParameter:
        if self.low > self.high:
            raise ValueError("Float search-space low must not exceed high.")
        if not self.low <= self.default <= self.high:
            raise ValueError("Float search-space default must be within bounds.")
        if self.log_scale and self.low <= 0:
            raise ValueError("Log-scaled search-space bounds must be positive.")
        if self.log_scale and self.step is not None:
            raise ValueError("Log-scaled float spaces cannot define a linear step.")
        if self.step is not None and not _aligned(self.default, self.low, self.step):
            raise ValueError("Float search-space default must align with step.")
        return self


class CategoricalSearchParameter(BaseModel):
    """A non-empty ordered allowlist of JSON-safe scalar choices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: SafeName
    kind: Literal[SearchParameterKind.CATEGORICAL] = SearchParameterKind.CATEGORICAL
    choices: tuple[SearchScalar, ...] = Field(min_length=1, max_length=32)
    default: SearchScalar

    @model_validator(mode="after")
    def validate_choices(self) -> CategoricalSearchParameter:
        canonical = [_scalar_identity(choice) for choice in self.choices]
        if len(set(canonical)) != len(canonical):
            raise ValueError("Categorical search-space choices must be unique.")
        if _scalar_identity(self.default) not in canonical:
            raise ValueError("Categorical search-space default must be a choice.")
        return self


type SearchParameter = Annotated[
    IntegerSearchParameter | FloatSearchParameter | CategoricalSearchParameter,
    Field(discriminator="kind"),
]


class PluginAutoMLSearchSpace(BaseModel):
    """One explicit plugin-owned AutoML capability contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin_id: SafeName
    task_type: TaskType
    parameters: tuple[SearchParameter, ...] = Field(min_length=1, max_length=32)
    probability_support: bool = False

    @model_validator(mode="after")
    def reject_duplicate_parameters(self) -> PluginAutoMLSearchSpace:
        names = [parameter.name for parameter in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("AutoML search parameter names must be unique.")
        return self


def validate_narrowed_search_space(
    owned: PluginAutoMLSearchSpace,
    narrowed: PluginAutoMLSearchSpace,
) -> PluginAutoMLSearchSpace:
    """Accept only task-compatible restrictions of a plugin-owned search space."""
    if (
        owned.plugin_id != narrowed.plugin_id
        or owned.task_type is not narrowed.task_type
    ):
        raise ValueError(
            "A narrowed search space must target the same plugin and task."
        )
    if owned.probability_support != narrowed.probability_support:
        raise ValueError("A narrowed search space cannot change plugin capabilities.")
    owned_by_name = {parameter.name: parameter for parameter in owned.parameters}
    narrowed_by_name = {parameter.name: parameter for parameter in narrowed.parameters}
    if set(narrowed_by_name) != set(owned_by_name):
        raise ValueError("A narrowed search space must retain every owned parameter.")
    for name, candidate in narrowed_by_name.items():
        _validate_narrowed_parameter(owned_by_name[name], candidate)
    return narrowed


def _validate_narrowed_parameter(
    owned: SearchParameter,
    narrowed: SearchParameter,
) -> None:
    if owned.kind != narrowed.kind:
        raise ValueError("A narrowed parameter cannot change its kind.")
    if isinstance(owned, IntegerSearchParameter) and isinstance(
        narrowed, IntegerSearchParameter
    ):
        if narrowed.low < owned.low or narrowed.high > owned.high:
            raise ValueError("A narrowed integer range cannot broaden its bounds.")
        if narrowed.step < owned.step or narrowed.step % owned.step:
            raise ValueError(
                "A narrowed integer step must be a multiple of the owner step."
            )
        if (narrowed.low - owned.low) % owned.step:
            raise ValueError("A narrowed integer range must align with the owner grid.")
        return
    if isinstance(owned, FloatSearchParameter) and isinstance(
        narrowed, FloatSearchParameter
    ):
        if narrowed.low < owned.low or narrowed.high > owned.high:
            raise ValueError("A narrowed float range cannot broaden its bounds.")
        if narrowed.log_scale != owned.log_scale:
            raise ValueError("A narrowed float range cannot change log scaling.")
        if owned.step is None:
            if narrowed.step is not None and narrowed.step <= 0:
                raise ValueError("A narrowed float step must be positive.")
        elif (
            narrowed.step is None
            or narrowed.step < owned.step
            or not _aligned(narrowed.step, 0.0, owned.step)
            or not _aligned(narrowed.low, owned.low, owned.step)
        ):
            raise ValueError("A narrowed float grid must align with the owner grid.")
        return
    if isinstance(owned, CategoricalSearchParameter) and isinstance(
        narrowed, CategoricalSearchParameter
    ):
        owned_choices = {_scalar_identity(choice) for choice in owned.choices}
        if not {_scalar_identity(choice) for choice in narrowed.choices}.issubset(
            owned_choices
        ):
            raise ValueError("A narrowed categorical space cannot add choices.")
        return
    raise ValueError("A narrowed parameter must preserve its owned type.")


def _aligned(value: float, origin: float, step: float) -> bool:
    quotient = (Decimal(str(value)) - Decimal(str(origin))) / Decimal(str(step))
    return quotient == quotient.to_integral_value()


def _scalar_identity(value: SearchScalar) -> tuple[str, str]:
    return type(value).__name__, str(value)
