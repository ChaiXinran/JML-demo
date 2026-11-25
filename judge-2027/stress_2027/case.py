"""An independently labeled simulated student submission."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    id: str
    expectation: str
    category: str
    reason: str
    source: str
    diagnostic: str | None = None
