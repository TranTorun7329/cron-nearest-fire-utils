"""Core logic for computing the next fire time of a cron expression.

The module supports a useful subset of standard Vixie cron:
  - Five fields: minute, hour, day-of-month, month, day-of-week.
  - Ranges (1-5), step values (*/15, 1-10/2), comma lists (1,5,10).
  - Predefined aliases (e.g. @daily, @hourly, @weekly).
  - Named months and day-of-week literals (jan, mon).

Design decision: when day-of-month and day-of-week are both restricted
(non-wildcard), cron semantics require a logical OR — a match on either
field is sufficient. This mirrors Vixie cron's well-documented behaviour
and is the most common source of confusion in cron calculators.

The implementation is a self-contained, forward-searching iterator that
does not depend on any third-party libraries.
"""

from __future__ import annotations

import datetime as _dt
from typing import List, Optional, Tuple

__all__ = [
    "CronError",
    "cron_field_aliases",
    "next_fire_time",
    "parse_cron",
]


class CronError(ValueError):
    """Raised when a cron expression cannot be parsed."""


_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3,
    "thu": 4, "fri": 5, "sat": 6,
}


def cron_field_aliases() -> List[Tuple[str, str]]:
    """Return a list of (alias_name, expression) pairs for introspection."""
    return [
        ("@yearly", "0 0 1 1 *"),
        ("@annually", "0 0 1 1 *"),
        ("@monthly", "0 0 1 * *"),
        ("@weekly", "0 0 * * 0"),
        ("@daily", "0 0 * * *"),
        ("@midnight", "0 0 * * *"),
        ("@hourly", "0 * * * *"),
    ]


def _parse_field(
    field: str,
    min_val: int,
    max_val: int,
    names: Optional[dict] = None,
) -> List[int]:
    """Parse a single cron field into a sorted list of valid integers."""
    field = field.strip().lower()
    if not field:
        raise CronError("Empty cron field")

    values: set = set()

    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError("Empty list element in cron field")

        # Handle step: "range/step" or "*/step"
        step = 1
        if "/" in part:
            base, step_str = part.split("/", 1)
            try:
                step = int(step_str)
            except ValueError:
                raise CronError(f"Invalid step value '{step_str}'") from None
            if step <= 0:
                raise CronError(f"Step must be positive, got {step}")
            part = base

        # Determine the range bounds
        if part == "*":
            start, end = min_val, max_val
        elif "-" in part:
            lo, hi = part.split("-", 1)
            start = _resolve_token(lo, min_val, max_val, names)
            end = _resolve_token(hi, min_val, max_val, names)
        else:
            # Single value — may be a bare name or number.
            single = _resolve_token(part, min_val, max_val, names)
            start = single
            end = max_val if step > 1 or part == "*" else single
            # Special-case: a single value with a step (e.g. "5/10") means
            # "start at 5, then every 10 up to max".
            if "/" in field:
                start = single
                end = max_val

        if start < min_val or end > max_val:
            raise CronError(
                f"Value out of range [{min_val}-{max_val}]: {part}"
            )
        if start > end:
            raise CronError(f"Inverted range in cron field: {part}")

        i = start
        while i <= end:
            values.add(i)
            i += step

    if not values:
        raise CronError(f"Field produced no valid values: {field}")

    return sorted(values)


def _resolve_token(
    token: str,
    min_val: int,
    max_val: int,
    names: Optional[dict],
) -> int:
    """Resolve a single token (name or number) to an integer."""
    token = token.strip().lower()
    if names and token in names:
        return names[token]
    try:
        return int(token)
    except ValueError:
        raise CronError(f"Cannot parse token '{token}'") from None


def parse_cron(expression: str) -> dict:
    """Parse a cron expression into a structured schedule.

    Returns a dict with keys:
        minutes:    list[int]   (0-59)
        hours:      list[int]   (0-23)
        doms:       list[int]   (1-31)
        months:     list[int]   (1-12)
        dows:       list[int]   (0-6, where 0 = Sunday)
        dom_restricted: bool    (True if day-of-month is not wildcard)
        dow_restricted: bool    (True if day-of-week is not wildcard)
    """
    if not expression or not expression.strip():
        raise CronError("Empty cron expression")

    expr = expression.strip().lower()

    # Handle named aliases
    aliases = dict(cron_field_aliases())
    if expr in aliases:
        expr = aliases[expr]

    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"Expected 5 fields, got {len(fields)}: '{expression}'"
        )

    minute_f, hour_f, dom_f, month_f, dow_f = fields

    minutes = _parse_field(minute_f, 0, 59)
    hours = _parse_field(hour_f, 0, 23)
    doms = _parse_field(dom_f, 1, 31)
    months = _parse_field(month_f, 1, 12, _MONTH_NAMES)
    dows = _parse_field(dow_f, 0, 6, _DOW_NAMES)

    return {
        "minutes": minutes,
        "hours": hours,
        "doms": doms,
        "months": months,
        "dows": dows,
        "dom_restricted": dom_f != "*",
        "dow_restricted": dow_f != "*",
    }


def next_fire_time(
    expression: str,
    now: _dt.datetime,
    tz: Optional[_dt.tzinfo] = None,
    max_iterations: int = 366 * 1440,
) -> Optional[_dt.datetime]:
    """Compute the next time `expression` will fire after `now`.

    Args:
        expression:    A cron expression string (5 fields or @alias).
        now:           The reference datetime. The returned time is strictly
                       after this moment.
        tz:            Optional timezone. If provided, `now` is interpreted
                       in this zone and the result is returned in this zone.
        max_iterations: Safety cap to prevent infinite loops on
                        pathological or impossible expressions (e.g.
                        "0 0 31 2 *" — Feb 31st never exists).

    Returns:
        A datetime, or None if no matching time exists within the iteration
        cap.
    """
    schedule = parse_cron(expression)

    if tz is not None and now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    elif tz is not None:
        now = now.astimezone(tz)

    candidate = now.replace(second=0, microsecond=0) + _dt.timedelta(minutes=1)

    dom_restricted = schedule["dom_restricted"]
    dow_restricted = schedule["dow_restricted"]

    for _ in range(max_iterations):
        if candidate.month not in schedule["months"]:
            next_month = candidate.month + 1
            next_year = candidate.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            candidate = candidate.replace(
                year=next_year, month=next_month, day=1,
                hour=0, minute=0,
            )
            continue

        # Compute day-of-week: Monday=0..Sunday=6 in Python, but cron uses
        # Sunday=0..Saturday=6. We convert Python's value to cron's.
        python_dow = candidate.weekday()  # Monday=0, Sunday=6
        cron_dow = (python_dow + 1) % 7    # Sunday=0, Monday=1, ..., Saturday=6

        dom_match = candidate.day in schedule["doms"]
        dow_match = cron_dow in schedule["dows"]

        if dom_restricted and dow_restricted:
            # Vixie cron OR semantics: either field matching is sufficient.
            day_ok = dom_match or dow_match
        elif dom_restricted:
            day_ok = dom_match
        elif dow_restricted:
            day_ok = dow_match
        else:
            day_ok = True

        if not day_ok:
            candidate = candidate + _dt.timedelta(days=1)
            candidate = candidate.replace(hour=0, minute=0)
            continue

        if candidate.hour not in schedule["hours"]:
            candidate = candidate + _dt.timedelta(hours=1)
            candidate = candidate.replace(minute=0)
            continue

        if candidate.minute not in schedule["minutes"]:
            candidate = candidate + _dt.timedelta(minutes=1)
            continue

        return candidate

    return None
