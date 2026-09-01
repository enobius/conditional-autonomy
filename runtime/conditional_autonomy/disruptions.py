"""Deterministic P9 Thanksgiving disruption and replanning episode.

P9 extends the static P6 scenario with one fact: at the intended 10:00 EST SFO
departure, James reports that his flight will instead land at 16:00 EST.
The notification changes canonical state only through a T-04 SET event.  The
static plan is then rejected against that ledger-derived arrival and a revised
plan is recorded before execution continues.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .contracts import validate_contract
from .reducer import canonical_state_bytes, reduce_event, replay_events
from .replay import validate_logical_clock_order
from .storage import canonical_json_bytes, with_content_hash
from .thanksgiving import (
    DINNER,
    EMILY_ARRIVAL,
    JAMES_ARRIVAL,
    MICHAEL_ARRIVAL,
    PredictedEffect,
    ScheduledAction,
    evaluate_schedule,
    initial_thanksgiving_state,
    normalized_time,
    thanksgiving_actions,
    utc_minute,
)


P9_NOTIFICATION = utc_minute("2026-11-26T15:00:00Z")  # 10:00 local
P9_JAMES_ARRIVAL = utc_minute("2026-11-26T21:00:00Z")  # 16:00 local
P9_EPISODE_ID = "episode:thanksgiving-p9-dynamic-001"
P9_PLAN_ID = "plan:thanksgiving-p9-replanned"


class DisruptionError(RuntimeError):
    """The disruption or replacement plan violates the Stage 1 contract."""


@dataclass(frozen=True, init=False)
class DisruptedThanksgivingEpisode:
    """Immutable replay evidence for the deterministic dynamic episode."""

    _initial_bytes: bytes = field(repr=False)
    _final_bytes: bytes = field(repr=False)
    _events_bytes: bytes = field(repr=False)
    original_plan_id: str
    replacement_plan_id: str

    def __init__(
        self,
        initial_state: object,
        final_state: object,
        events: object,
        original_plan_id: str,
        replacement_plan_id: str,
    ) -> None:
        object.__setattr__(self, "_initial_bytes", canonical_json_bytes(initial_state))
        object.__setattr__(self, "_final_bytes", canonical_json_bytes(final_state))
        object.__setattr__(self, "_events_bytes", canonical_json_bytes(events))
        object.__setattr__(self, "original_plan_id", original_plan_id)
        object.__setattr__(self, "replacement_plan_id", replacement_plan_id)

    @property
    def initial_state(self) -> dict[str, Any]:
        import json
        return json.loads(self._initial_bytes)

    @property
    def final_state(self) -> dict[str, Any]:
        import json
        return json.loads(self._final_bytes)

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        import json
        return tuple(json.loads(self._events_bytes))

    @property
    def disruption_event(self) -> dict[str, Any]:
        return next(event for event in self.events if event["event_id"] == "event:p9-james-delay")

    @property
    def replanning_event(self) -> dict[str, Any]:
        return next(event for event in self.events if event["event_id"] == "event:p9-replan")


def p9_replanned_actions() -> tuple[ScheduledAction, ...]:
    """Return the P6 plan revised only where the delayed arrival requires it."""

    unchanged = {
        action.action_id: action
        for action in thanksgiving_actions()
        if action.action_id not in {
            "action:james-land-and-rent",
            "action:airport-grandma-pickup",
        }
    }
    return (
        ScheduledAction(
            "action:p9-james-land-and-rent",
            "thanksgiving:land-and-rent",
            "obligation:james-rental",
            P9_JAMES_ARRIVAL,
            P9_JAMES_ARRIVAL,
            (),
            (),
            (
                PredictedEffect(
                    "/entities/person:james/location", "BOS",
                    P9_JAMES_ARRIVAL, P9_JAMES_ARRIVAL,
                ),
                PredictedEffect(
                    "/entities/person:james/has_vehicle", True,
                    P9_JAMES_ARRIVAL, P9_JAMES_ARRIVAL,
                ),
                PredictedEffect(
                    "/resources/capacities/vehicle:rental-james/status", "AVAILABLE",
                    P9_JAMES_ARRIVAL, P9_JAMES_ARRIVAL,
                ),
            ),
        ),
        unchanged["action:cook-turkey"],
        unchanged["action:michael-arrive"],
        ScheduledAction(
            "action:p9-airport-grandma-pickup",
            "thanksgiving:airport-grandma-pickup",
            "obligation:airport-grandma-pickup",
            P9_JAMES_ARRIVAL,
            utc_minute("2026-11-26T22:30:00Z"),  # 17:30 local
            ("vehicle:rental-james",),
            ("action:p9-james-land-and-rent",),
            (
                PredictedEffect(
                    "/entities/person:james/location", "HOME",
                    utc_minute("2026-11-26T22:30:00Z"),
                    utc_minute("2026-11-26T22:30:00Z"),
                ),
                PredictedEffect(
                    "/entities/person:emily/location", "HOME",
                    utc_minute("2026-11-26T22:30:00Z"),
                    utc_minute("2026-11-26T22:30:00Z"),
                ),
                PredictedEffect(
                    "/entities/person:grandma/location", "HOME",
                    utc_minute("2026-11-26T22:30:00Z"),
                    utc_minute("2026-11-26T22:30:00Z"),
                ),
                PredictedEffect(
                    "/resources/capacities/vehicle:rental-james/location", "HOME",
                    utc_minute("2026-11-26T22:30:00Z"),
                    utc_minute("2026-11-26T22:30:00Z"),
                ),
            ),
        ),
        unchanged["action:prepare-sides"],
    )


def _event(
    state: Mapping[str, Any],
    *,
    event_id: str,
    timestamp_minute: int,
    path: str,
    value: object,
    source: str = "ENVIRONMENT",
    logical_clock: int | None = None,
) -> dict[str, Any]:
    clock = state["logical_clock"] + 1 if logical_clock is None else logical_clock
    provenance = with_content_hash(
        {
            "provenance_id": f"provenance:{event_id}",
            "source": source,
            "recorded_at": normalized_time(timestamp_minute),
            "access_class": "EVALUATOR_ONLY",
        }
    )
    event = with_content_hash(
        {
            "event_id": event_id,
            "episode_id": P9_EPISODE_ID,
            "event_type": "STATE_TRANSITION",
            "logical_clock": clock,
            "timestamp": normalized_time(timestamp_minute),
            "source": source,
            "access_class": "EVALUATOR_ONLY",
            "payload": {
                "operation": "SET",
                "path": path,
                "value": deepcopy(value),
                "from_state_version": state["state_version"],
                "to_state_version": state["state_version"] + 1,
            },
            "provenance": provenance,
        }
    )
    return validate_contract(event, "event.schema.json", "P9 ledger event")


def _plan_authorized_event(state: Mapping[str, Any]) -> dict[str, Any]:
    recorded = normalized_time(utc_minute("2026-11-26T14:00:00Z"))  # 09:00 local
    provenance = with_content_hash(
        {
            "provenance_id": "provenance:event:p6-plan-authorized",
            "source": "MODEL_CLAIM",
            "recorded_at": recorded,
            "access_class": "EVALUATOR_ONLY",
        }
    )
    return validate_contract(
        with_content_hash(
            {
                "event_id": "event:p6-plan-authorized",
                "episode_id": P9_EPISODE_ID,
                "event_type": "PLAN_AUTHORIZED",
                "logical_clock": state["logical_clock"] + 1,
                "timestamp": recorded,
                "source": "MODEL_CLAIM",
                "access_class": "EVALUATOR_ONLY",
                "payload": {"plan_id": state["active_plan"]["plan_id"]},
                "provenance": provenance,
            }
        ),
        "event.schema.json",
        "initial plan authorization event",
    )


def plan_respects_james_arrival(
    state: Mapping[str, Any], actions: Sequence[ScheduledAction]
) -> bool:
    """Reject a plan that schedules James before the ledger-derived arrival."""

    arrival = state["entities"]["person:james"]["arrival_at"]
    arrival_minute = utc_minute(arrival["instant"])
    james_actions = [
        action for action in actions if action.obligation_id == "obligation:james-rental"
    ]
    return len(james_actions) == 1 and james_actions[0].start_minute >= arrival_minute


def _completed_obligations(
    state: Mapping[str, Any], obligation_id: str
) -> list[dict[str, Any]]:
    obligations = deepcopy(state["obligations"])
    for obligation in obligations:
        if obligation["obligation_id"] == obligation_id:
            obligation["status"] = "COMPLETED"
            return obligations
    raise DisruptionError(f"unknown obligation {obligation_id!r}")


def run_disrupted_thanksgiving_episode() -> DisruptedThanksgivingEpisode:
    """Run P9 with disruption and replanning represented entirely in the ledger."""

    initial = deepcopy(initial_thanksgiving_state())
    initial["episode_id"] = P9_EPISODE_ID
    initial = validate_contract(
        initial, "canonical-state.schema.json", "P9 initial canonical state"
    )
    state = deepcopy(initial)
    events: list[dict[str, Any]] = []

    authorization = _plan_authorized_event(state)
    events.append(authorization)

    delay = _event(
        state,
        event_id="event:p9-james-delay",
        timestamp_minute=P9_NOTIFICATION,
        path="/entities/person:james/arrival_at",
        value=normalized_time(P9_JAMES_ARRIVAL),
        source="USER",
        logical_clock=authorization["logical_clock"] + 1,
    )
    state = reduce_event(state, delay)
    events.append(delay)

    original = thanksgiving_actions()
    revised = p9_replanned_actions()
    if plan_respects_james_arrival(state, original):
        raise DisruptionError("P9 delay did not invalidate the authorized P6 plan")
    if not plan_respects_james_arrival(state, revised):
        raise DisruptionError("replacement plan still precedes James's delayed arrival")
    failures = [item for item in evaluate_schedule(state, revised) if not item.passed]
    if failures:
        raise DisruptionError(
            "; ".join(
                f"{item.constraint.constraint_id}: {item.detail}" for item in failures
            )
        )

    active_plan = deepcopy(state["active_plan"])
    active_plan["plan_id"] = P9_PLAN_ID
    replan = _event(
        state,
        event_id="event:p9-replan",
        timestamp_minute=P9_NOTIFICATION,
        path="/active_plan",
        value=active_plan,
        source="MODEL_CLAIM",
    )
    state = reduce_event(state, replan)
    events.append(replan)

    for action in sorted(
        revised, key=lambda item: (item.end_minute, item.start_minute, item.action_id)
    ):
        ordinal = 0
        for effect in action.effects:
            ordinal += 1
            transition = _event(
                state,
                event_id=f"event:p9:{action.action_id.removeprefix('action:')}:{ordinal}",
                timestamp_minute=action.end_minute,
                path=effect.path,
                value=effect.value,
            )
            state = reduce_event(state, transition)
            events.append(transition)
        ordinal += 1
        transition = _event(
            state,
            event_id=f"event:p9:{action.action_id.removeprefix('action:')}:{ordinal}",
            timestamp_minute=action.end_minute,
            path="/obligations",
            value=_completed_obligations(state, action.obligation_id),
        )
        state = reduce_event(state, transition)
        events.append(transition)
        ordinal += 1
        transition = _event(
            state,
            event_id=f"event:p9:{action.action_id.removeprefix('action:')}:{ordinal}",
            timestamp_minute=action.end_minute,
            path="/completed_actions",
            value=[*state["completed_actions"], action.action_id],
        )
        state = reduce_event(state, transition)
        events.append(transition)

    validate_logical_clock_order(events)
    transitions = [event for event in events if event["event_type"] == "STATE_TRANSITION"]
    replayed = replay_events(initial, transitions)
    if canonical_state_bytes(replayed) != canonical_state_bytes(state):
        raise DisruptionError("INV-008: disrupted episode did not replay identically")
    return DisruptedThanksgivingEpisode(
        initial,
        state,
        events,
        initial["active_plan"]["plan_id"],
        P9_PLAN_ID,
    )


def canonical_disrupted_episode_bytes(episode: DisruptedThanksgivingEpisode) -> bytes:
    """Serialize the replay evidence deterministically for fresh-process checks."""

    return canonical_json_bytes(
        {
            "initial_state": episode.initial_state,
            "final_state": episode.final_state,
            "events": list(episode.events),
            "original_plan_id": episode.original_plan_id,
            "replacement_plan_id": episode.replacement_plan_id,
        }
    )
