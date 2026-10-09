"""The schedule engine (taas-specs/ppm/schedule/schedule-spec.md §5) — pure: items + links in, dates out.

Working days are indexed ``w(date)`` from the project start (Monday–Friday until the organization calendar exists,
resources V3). Boundaries: item with start day ``s`` and duration ``D ≥ 1`` has ``ES = s``, ``EF = s + D``; shown start
``day(ES)``, due ``day(EF − 1)``. A milestone (``D = 0``) at boundary ``b`` shows on ``day(b − 1)`` (``day(p)`` when
``b = p``).

Forward pass (Kahn order) over scheduled leaf items: done and manual items are fixed and drive their successors; auto
items start at ``max(p, incoming bounds, SNET)`` (``MSO`` wins, a later bound is a violation). Links FS · SS · FF · SF
with lag ``L`` (negative = lead). Summary items roll up their descendants; links on a summary apply to every
descendant leaf. Backward pass gives total float and the critical path; the forecast pass pushes late work past the
status date.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, timedelta

DEPENDENCIES = ('fs', 'ss', 'ff', 'sf')


# --- working days -----------------------------------------------------------------------------------


def is_working(day: date) -> bool:
    return day.weekday() < 5


def next_working(day: date) -> date:
    while not is_working(day):
        day += timedelta(days=1)
    return day


def previous_working(day: date) -> date:
    while not is_working(day):
        day -= timedelta(days=1)
    return day


@dataclass(frozen=True, slots=True)
class Calendar:
    """Working-day index from ``base`` (a working day)."""

    base: date

    def w(self, day: date) -> int:
        """Index of ``day`` (a non-working day counts as the next working day)."""
        d = next_working(day)
        if d == self.base:
            return 0
        sign = 1 if d > self.base else -1
        a, b = (self.base, d) if sign > 0 else (d, self.base)
        full, rest = divmod((b - a).days, 7)
        n = full * 5
        x = a
        for _ in range(rest):
            x += timedelta(days=1)
            if is_working(x):
                n += 1
        return sign * n

    def day(self, index: int) -> date:
        d = self.base
        step = 1 if index >= 0 else -1
        left = abs(index)
        weeks, left = divmod(left, 5)
        d += timedelta(days=7 * weeks * step)
        while left:
            d += timedelta(days=step)
            if is_working(d):
                left -= 1
        return d

    def working_days(self, start: date, end: date) -> int:
        """Working days in [start, end] (inclusive), at least 1."""
        return max(1, self.w(previous_working(end)) - self.w(next_working(start)) + 1)


# --- input / output -----------------------------------------------------------------------------------


@dataclass(slots=True)
class Item:
    id: str
    start: date | None = None
    due: date | None = None
    duration: int | None = None
    milestone: bool = False
    done: bool = False
    excluded: bool = False
    """Cancelled / rejected: out of the schedule, links ignored."""
    manual: bool = True
    """Dates typed by people (project manual, or a manual item in an auto project)."""
    constraint: str | None = None
    """``asap`` · ``snet`` · ``mso`` · ``fnlt``."""
    constraint_date: date | None = None
    started: date | None = None
    finished: date | None = None
    progress: int = 0
    parent_id: str | None = None


@dataclass(slots=True)
class Link:
    id: str
    source: str
    target: str
    type: str = 'fs'
    lag: int = 0


@dataclass(slots=True)
class Result:
    start: date | None = None
    due: date | None = None
    duration: int = 0
    forecast_start: date | None = None
    forecast_due: date | None = None
    total_float: int | None = None
    critical: bool = False
    summary: bool = False
    scheduled: bool = True
    driving_link: str | None = None
    why: str = 'none'
    """``link`` · ``constraint`` · ``manual`` · ``done`` · ``project_start`` · ``summary`` · ``unscheduled`` · ``excluded``."""
    violations: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class Schedule:
    items: dict[str, Result]
    project_start: date
    finish: date | None
    forecast_finish: date | None
    critical_path: list[str]
    cycle: list[str] | None = None


class CycleError(ValueError):
    def __init__(self, path: list[str]):
        super().__init__('dependency cycle')
        self.path = path


# --- graph helpers --------------------------------------------------------------------------------------


def _children(items: dict[str, Item]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for it in items.values():
        if it.parent_id and it.parent_id in items:
            out[it.parent_id].append(it.id)
    return out


def _descendants(node: str, children: dict[str, list[str]]) -> list[str]:
    out, stack = [], list(children.get(node, []))
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(children.get(n, []))
    return out


def _ancestors(node: str, items: dict[str, Item]) -> list[str]:
    out, cur = [], items[node].parent_id if node in items else None
    while cur and cur in items and cur not in out:
        out.append(cur)
        cur = items[cur].parent_id
    return out


def find_cycle(
    items: dict[str, Item], links: list[Link], new: Link
) -> list[str] | None:
    """Path when ``new`` (source → target) would close a cycle (§5.4): self, ancestor / descendant, or a path back."""
    if new.source == new.target:
        return [new.source, new.target]
    children = _children(items)
    s_family = {new.source, *_descendants(new.source, children)}
    if new.target in s_family or new.target in _ancestors(new.source, items):
        return [new.source, new.target]
    outgoing: dict[str, list[str]] = defaultdict(list)
    for link in links:
        if link.type in (*DEPENDENCIES, 'blocks'):
            outgoing[link.source].append(link.target)

    def nxt(x: str) -> list[str]:
        out: list[str] = []
        for node in (x, *_ancestors(x, items)):
            for t in outgoing.get(node, []):
                out += [t, *_descendants(t, children)]
        return out

    start = [new.target, *_descendants(new.target, children)]
    prev: dict[str, str | None] = dict.fromkeys(start)
    queue = deque(start)
    while queue:
        x = queue.popleft()
        if x in s_family:
            path = [x]
            while prev.get(path[-1]) is not None:
                path.append(prev[path[-1]])  # type: ignore[arg-type]
            return [new.source, *reversed(path)]
        for y in nxt(x):
            if y not in prev:
                prev[y] = x
                queue.append(y)
    return None


# --- the passes ------------------------------------------------------------------------------------------


def compute(
    items: list[Item],
    links: list[Link],
    *,
    project_start: date | None = None,
    project_due: date | None = None,
    today: date | None = None,
    default_duration: int = 1,
    critical_float: int = 0,
) -> Schedule:
    """Plan (forward pass), forecast at ``today`` and backward pass (float, critical path) of one project."""
    by_id = {i.id: i for i in items}
    children = _children(by_id)
    today = today or date.today()
    linked = {link.source for link in links} | {link.target for link in links}
    starts = [i.start or i.due for i in items if (i.start or i.due) and not i.excluded]
    base = next_working(project_start or (min(starts) if starts else today))
    cal = Calendar(base)
    p = 0
    results: dict[str, Result] = {i.id: Result() for i in items}

    def w_due(day: date) -> int:
        """Index of a due / finish day (a non-working day counts as the previous working day)."""
        return cal.w(previous_working(day))

    # --- inputs: duration and typed start (boundary) of every scheduled leaf -------------------------
    summaries = {
        i.id
        for i in items
        if not i.excluded and any(not by_id[c].excluded for c in children.get(i.id, []))
    }
    typed: dict[str, int] = {}
    """ES from the item's own dates (manual items keep it, done items are fixed at it)."""
    dur: dict[str, int] = {}
    for it in items:
        r = results[it.id]
        r.summary = it.id in summaries
        if it.excluded:
            r.scheduled, r.why = False, 'excluded'
            continue
        if r.summary:
            continue
        if it.done:
            start = it.started or it.start or it.finished or it.due
            if start is None:
                r.scheduled, r.why = False, 'unscheduled'
                continue
            end = it.finished or it.due or start
            if it.milestone:
                typed[it.id], dur[it.id] = w_due(end) + 1, 0
            else:
                typed[it.id] = cal.w(start)
                dur[it.id] = max(1, w_due(max(end, start)) - typed[it.id] + 1)
            r.why = 'done'
            continue
        if it.milestone:
            day = it.due or it.start
            if day is None and it.manual and it.id not in linked:
                r.scheduled, r.why = False, 'unscheduled'
                continue
            dur[it.id] = 0
            if day is not None:
                typed[it.id] = w_due(day) + 1
            continue
        d = it.duration or 0
        if not d and (it.start or it.due):
            d = cal.working_days(it.start, it.due) if it.start and it.due else 1
        if not d and (it.id in linked or not it.manual):
            d = default_duration
        if not d:
            r.scheduled, r.why = False, 'unscheduled'
            continue
        dur[it.id] = d
        if it.start:
            typed[it.id] = cal.w(it.start)
        elif it.due:
            typed[it.id] = w_due(it.due) - d + 1

    fixed = {n for n in dur if by_id[n].done or (by_id[n].manual and n in typed)}
    scheduled = [i.id for i in items if i.id in dur]

    # --- graph: dependency links between leaves (links on a summary apply to its descendant leaves) ----
    def leaves_of(node: str) -> list[str]:
        if node not in summaries:
            return [node] if node in dur else []
        return [
            d for d in _descendants(node, children) if d in dur and d not in summaries
        ]

    incoming: dict[str, list[tuple[str, Link]]] = defaultdict(list)
    outgoing: dict[str, list[tuple[str, Link]]] = defaultdict(list)
    indegree = dict.fromkeys(scheduled, 0)
    for link in links:
        if link.type not in DEPENDENCIES:
            continue
        if link.source not in by_id or link.target not in by_id:
            continue
        if by_id[link.source].excluded or by_id[link.target].excluded:
            continue
        for s in leaves_of(link.source):
            for t in leaves_of(link.target):
                if s != t:
                    incoming[t].append((s, link))
                    outgoing[s].append((t, link))
                    indegree[t] += 1
    order: list[str] = []
    queue = deque(n for n in scheduled if indegree[n] == 0)
    while queue:
        n = queue.popleft()
        order.append(n)
        for t, _ in outgoing[n]:
            indegree[t] -= 1
            if indegree[t] == 0:
                queue.append(t)
    if len(order) < len(scheduled):
        stuck = [n for n in scheduled if indegree[n] > 0]
        return Schedule(results, base, None, None, [], cycle=stuck)

    def bound(
        t: str, s: str, link: Link, es_: dict[str, int], ef_: dict[str, int]
    ) -> int:
        lag, d = link.lag, dur[t]
        return {
            'fs': ef_[s] + lag,
            'ss': es_[s] + lag,
            'ff': ef_[s] + lag - d,
            'sf': es_[s] + lag - d,
        }[link.type]

    # --- forward pass: plan (status None) or forecast (status = boundary of today) -------------------
    def forward(
        status: int | None,
    ) -> tuple[dict[str, int], dict[str, int], dict[str, tuple[str, str | None]]]:
        es_: dict[str, int] = {}
        ef_: dict[str, int] = {}
        why: dict[str, tuple[str, str | None]] = {}
        for n in order:
            it, d = by_id[n], dur[n]
            link_bound, link_id = max(
                ((bound(n, s, link, es_, ef_), link.id) for s, link in incoming[n]),
                default=(None, None),
            )
            started = status is not None and it.started is not None and not it.done
            if it.done or (n in fixed and status is None):
                start, reason = typed[n], ('done' if it.done else 'manual', None)
            elif started:
                start, reason = cal.w(it.started), ('manual', None)  # type: ignore[arg-type]
            elif it.constraint == 'mso' and it.constraint_date:
                start, reason = cal.w(it.constraint_date), ('constraint', None)
            else:
                candidates: list[tuple[int, str, str | None]] = [
                    (p, 'project_start', None)
                ]
                if status is not None:
                    candidates.append((status, 'status', None))
                if n in fixed:  # forecast: a manual item acts as SNET = its start
                    candidates.append((typed[n], 'manual', None))
                if it.constraint == 'snet' and it.constraint_date:
                    candidates.append((cal.w(it.constraint_date), 'constraint', None))
                if link_bound is not None:
                    candidates.append((link_bound, 'link', link_id))
                start, *rest = max(candidates, key=lambda c: (c[0], c[1] == 'link'))
                reason = (rest[0], rest[1])
            finish = start + d
            if started:
                remaining = math.ceil(d * (100 - max(0, min(100, it.progress))) / 100)
                finish = max(finish, status + remaining)  # type: ignore[operator]
            es_[n], ef_[n], why[n] = start, finish, reason
        return es_, ef_, why

    plan_es, plan_ef, plan_why = forward(None)
    status = cal.w(next_working(today))
    fc_es, fc_ef, _ = forward(status)

    # --- backward pass on the forecast network (§5.3) ------------------------------------------------
    finish_b = max(fc_ef.values(), default=0)
    lf_max = min(finish_b, w_due(project_due) + 1) if project_due else finish_b
    lf: dict[str, int] = {}
    for n in reversed(order):
        it, d = by_id[n], dur[n]
        value = lf_max
        for t, link in outgoing[n]:
            ls_t = lf[t] - dur[t]
            value = min(
                value,
                {
                    'fs': ls_t - link.lag,
                    'ss': ls_t - link.lag + d,
                    'ff': lf[t] - link.lag,
                    'sf': lf[t] - link.lag + d,
                }[link.type],
            )
        if it.constraint == 'fnlt' and it.constraint_date:
            value = min(value, w_due(it.constraint_date) + 1)
        if it.constraint == 'mso' and it.constraint_date:
            value = fc_ef[n]
        lf[n] = value

    def shown(start: int, d: int) -> tuple[date, date]:
        if d == 0:
            day = cal.day(start - 1) if start > p else cal.day(p)
            return day, day
        return cal.day(start), cal.day(start + d - 1)

    for n in order:
        r, it = results[n], by_id[n]
        r.duration = dur[n]
        r.start, r.due = shown(plan_es[n], dur[n])
        r.forecast_start, r.forecast_due = shown(fc_es[n], fc_ef[n] - fc_es[n])
        r.total_float = (lf[n] - dur[n]) - fc_es[n]
        r.critical = not it.done and r.total_float <= critical_float
        r.why, r.driving_link = plan_why[n]
        for s, link in incoming[n]:
            slack = plan_es[n] - bound(n, s, link, plan_es, plan_ef)
            if slack < 0:
                r.violations.append(
                    {'link_id': link.id, 'predecessor': s, 'days': -slack}
                )
        if (
            it.constraint == 'fnlt'
            and it.constraint_date
            and r.due > it.constraint_date
        ):  # type: ignore[operator]
            r.violations.append(
                {'constraint': 'fnlt', 'days': cal.w(r.due) - w_due(it.constraint_date)}  # type: ignore[arg-type]
            )

    # --- summaries: roll-up of their scheduled descendants (§5.4) -------------------------------------
    for sid in summaries:
        leaves = [d for d in _descendants(sid, children) if d in plan_es]
        r = results[sid]
        r.why = 'summary'
        if not leaves:
            r.scheduled = False
            continue
        r.start = min(results[d].start for d in leaves)  # type: ignore[type-var]
        r.due = max(results[d].due for d in leaves)  # type: ignore[type-var]
        r.forecast_start = min(results[d].forecast_start for d in leaves)  # type: ignore[type-var]
        r.forecast_due = max(results[d].forecast_due for d in leaves)  # type: ignore[type-var]
        r.duration = cal.working_days(r.start, r.due)  # type: ignore[arg-type]
        r.total_float = min(results[d].total_float or 0 for d in leaves)
        r.critical = any(results[d].critical for d in leaves)

    finish = max((results[n].due for n in order), default=None)  # type: ignore[type-var]
    forecast_finish = max((results[n].forecast_due for n in order), default=None)  # type: ignore[type-var]
    critical = [n for n in order if results[n].critical]
    return Schedule(results, base, finish, forecast_finish, critical)


def schedule_progress(items: list[Item], results: dict[str, Result]) -> int:
    """Duration-weighted progress of leaf items (§5.5): ``Σ D × p ÷ Σ D`` (done = 100; all milestones → mean)."""
    pairs = [
        (results[i.id].duration, 100 if i.done else max(0, min(100, i.progress)))
        for i in items
        if i.id in results
        and results[i.id].scheduled
        and not results[i.id].summary
        and not i.excluded
    ]
    if not pairs:
        return 0
    total = sum(d for d, _ in pairs)
    if total == 0:
        return round(sum(v for _, v in pairs) / len(pairs))
    return round(sum(d * v for d, v in pairs) / total)
