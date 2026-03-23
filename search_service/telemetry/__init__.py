"""Telemetry -- trace recording and event factories for the search pipeline."""

from search_service.telemetry import events
from search_service.telemetry.tracer import Tracer

__all__ = [
    "Tracer",
    "events",
]
