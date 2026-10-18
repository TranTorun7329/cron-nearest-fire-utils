# cron-nearest-fire-utils

Finds the next time a specific cron expression will trigger.

```python
from cron_nearest_fire_utils import next_fire_time, parse_cron, CronError
import datetime

now = datetime.datetime(2024, 1, 15, 10, 30, 0)
next_run = next_fire_time("0 2 * * 1", now)
print(next_run)  # 2024-01-16 02:00:00
```

## Why this exists

Most cron libraries are full schedulers: they start jobs, manage
subscriptions, and persist state. This library does one thing — given a
cron expression and a reference time, return the next matching datetime.
That makes it suitable for queue schedulers, reminder systems, and tests
that need to assert against a computed fire time without running a
daemon.

The trade-off: this is a pure forward-search calculator. It does not
handle seconds-level precision, timezone-aware DST jumps, or the L/W
modifiers from Quartz cron. It implements the Vixie cron subset (five
fields, ranges, steps, lists, named months/days, and @aliases).

## The awkward edge

When both day-of-month and day-of-week are restricted (neither is `*`),
Vixie cron treats them as a logical OR: the job fires if *either* field
matches. Many naive calculators apply AND and get the wrong answer. This
library implements the OR semantics. For example, `0 0 13 * 5` fires on
the 13th of the month *and* on every Friday — whichever comes first.

Another edge: expressions like `0 0 31 2 *` (Feb 31st) reference a date
that never exists. `next_fire_time` will search up to `max_iterations`
(default ~one year of minutes) and return `None` rather than loop
forever.

## Exports

- `next_fire_time(expression, now, tz=None, max_iterations=...) -> datetime | None`
- `parse_cron(expression) -> dict`
- `CronError` (subclass of `ValueError`)
- `cron_field_aliases() -> list[tuple[str, str]]`
