"""Transport-independent submission and identity contracts for Runtime v2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

RuntimePayload = tuple[tuple[str, object], ...]


class RuntimeEngine(StrEnum):
    """A durable runtime implementation selected when an instance is created."""

    LOCAL = "local"
    REMOTE = "remote"


class RuntimeInstanceStatus(StrEnum):
    """Stable status vocabulary shared by local and remote runtime adapters."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RuntimeExecutorRef:
    """Opaque reference to an executor owned outside Runtime."""

    namespace: str
    key: str
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.namespace.strip():
            raise ValueError("runtime executor namespace must not be blank")
        if not self.key.strip():
            raise ValueError("runtime executor key must not be blank")


@dataclass(frozen=True, slots=True)
class RuntimeStepSubmissionV2:
    """One executable node in a generic directed acyclic graph."""

    business_key: str
    executor_ref: RuntimeExecutorRef
    input_data: RuntimePayload = ()
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.business_key.strip():
            raise ValueError("runtime step business key must not be blank")
        if self.business_key in self.depends_on:
            raise ValueError("runtime step cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("runtime step dependencies must be unique")
        _validate_payload(self.input_data, owner="runtime step input")


@dataclass(frozen=True, slots=True)
class RuntimeSubmissionV2:
    """A new runtime instance request with no planning or persistence types."""

    business_key: str
    workflow_type: str
    input_data: RuntimePayload
    steps: tuple[RuntimeStepSubmissionV2, ...]
    contract_version: int = 2

    def __post_init__(self) -> None:
        if self.contract_version != 2:
            raise ValueError("unsupported runtime submission contract version")
        if not self.business_key.strip():
            raise ValueError("runtime business key must not be blank")
        if not self.workflow_type.strip():
            raise ValueError("runtime workflow type must not be blank")
        if not self.steps:
            raise ValueError("runtime submission must contain at least one step")
        _validate_payload(self.input_data, owner="runtime input")
        keys = tuple(step.business_key for step in self.steps)
        if len(keys) != len(set(keys)):
            raise ValueError("runtime step business keys must be unique")
        known = set(keys)
        if any(dependency not in known for step in self.steps for dependency in step.depends_on):
            raise ValueError("runtime dependency references an unknown step")
        if _has_cycle(self.steps):
            raise ValueError("runtime dependency graph must be acyclic")


@dataclass(frozen=True, slots=True)
class RuntimeInstanceRefV2:
    """Stable instance identity; its engine is immutable after creation."""

    runtime_id: str
    business_key: str
    workflow_type: str
    engine: RuntimeEngine

    def __post_init__(self) -> None:
        if not self.runtime_id.strip():
            raise ValueError("runtime id must not be blank")
        if not self.business_key.strip():
            raise ValueError("runtime business key must not be blank")
        if not self.workflow_type.strip():
            raise ValueError("runtime workflow type must not be blank")


@dataclass(frozen=True, slots=True)
class RuntimeStartResultV2:
    """Result returned after a runtime implementation accepts a submission."""

    instance: RuntimeInstanceRefV2
    status: RuntimeInstanceStatus
    output_data: RuntimePayload = ()

    def __post_init__(self) -> None:
        _validate_payload(self.output_data, owner="runtime output")


def _validate_payload(payload: RuntimePayload, *, owner: str) -> None:
    keys = tuple(key for key, _value in payload)
    if any(not key.strip() for key in keys):
        raise ValueError(f"{owner} keys must not be blank")
    if len(keys) != len(set(keys)):
        raise ValueError(f"{owner} keys must be unique")


def _has_cycle(steps: tuple[RuntimeStepSubmissionV2, ...]) -> bool:
    dependencies = {step.business_key: step.depends_on for step in steps}
    colors: dict[str, int] = {}

    def visit(key: str) -> bool:
        colors[key] = 1
        for dependency in dependencies[key]:
            state = colors.get(dependency, 0)
            if state == 1 or (state == 0 and visit(dependency)):
                return True
        colors[key] = 2
        return False

    return any(colors.get(key, 0) == 0 and visit(key) for key in dependencies)
