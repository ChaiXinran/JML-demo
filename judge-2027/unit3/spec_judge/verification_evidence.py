"""Small, serializable models for verification sessions and evidence.

The semantic judge remains responsible for deciding a result.  These models
only make the inputs, provenance and tool observations explicit so a CLI or a
future interactive client can inspect a run without reconstructing it from
free-form output.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceSpan:
    """A source location that can be safely shown to a client."""

    source: str
    start_line: int
    end_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    """One observation, with its origin distinguished from its interpretation."""

    kind: str
    origin: str
    summary: str
    data: Mapping[str, Any] = field(default_factory=dict)
    source_span: SourceSpan | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": self.kind,
            "origin": self.origin,
            "summary": self.summary,
            "data": dict(self.data),
        }
        if self.source_span is not None:
            payload["source_span"] = self.source_span.to_dict()
        return payload


@dataclass
class VerificationSession:
    """A lightweight record of one verification attempt.

    This is deliberately an in-memory value object in the first increment.
    Persistence, access control and retention belong to the Web deployment
    layer and are not implied by this model.
    """

    session_id: str
    method: str
    created_at: str
    inputs: dict[str, str]
    configuration: dict[str, Any]
    evidence: list[Evidence] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        method: str,
        inputs: Mapping[str, str],
        configuration: Mapping[str, Any] | None = None,
    ) -> "VerificationSession":
        return cls(
            session_id=str(uuid.uuid4()),
            method=method,
            created_at=datetime.now(timezone.utc).isoformat(),
            inputs=dict(inputs),
            configuration=dict(configuration or {}),
        )

    def add(self, item: Evidence) -> None:
        self.evidence.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "method": self.method,
            "created_at": self.created_at,
            "inputs": dict(self.inputs),
            "configuration": dict(self.configuration),
            "evidence": [item.to_dict() for item in self.evidence],
        }
