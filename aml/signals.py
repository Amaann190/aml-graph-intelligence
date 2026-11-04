"""Detection signals.

Daily rules look at one calendar day of transfers at a time:

* fan-out: the payer paid at least FAN_THRESHOLD distinct accounts that day
* fan-in: the payee was paid by at least FAN_THRESHOLD distinct accounts that day
* return transfer: the payee had already paid the payer earlier the same day

Graph patterns look across days at how money moves between accounts:

* temporal cycle: money leaves an account and comes back to it through 2 to 7 other
  accounts, with every hop later than the one before and the whole loop inside WINDOW
* scatter-gather: one account pays at least MIN_MIDDLE intermediaries, and each of
  them pays the same final account after receiving, inside WINDOW

Accounts with more than HUB_LIMIT distinct counterparties over the whole period are
not used as cycle members or intermediaries. They behave like merchants or payroll
accounts, and including them multiplies cycles without adding signal.

Self-transfers never trigger a signal. Labels are never read here.
"""
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

FAN_THRESHOLD = 10
MAX_CYCLE_LENGTH = 8
MIN_MIDDLE = 3
WINDOW = 5 * 24 * 60          # minutes
HUB_LIMIT = 30


@dataclass(frozen=True)
class Pattern:
    kind: str                 # "cycle" or "scatter_gather"
    accounts: tuple           # cycle: accounts in order; scatter-gather: (source, *middles, sink)
    rows: tuple               # source_row of every transfer that forms the pattern
    start: int                # minute of the first transfer
    end: int                  # minute of the last transfer


def transfers(frame: pd.DataFrame) -> pd.DataFrame:
    """Transfers between two different accounts."""
    return frame.loc[frame.source != frame.target]


def daily_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Boolean fan_out, fan_in and return_transfer columns aligned to `frame`."""
    edges = transfers(frame)
    out_degree = edges.groupby(["day", "source"]).target.transform("nunique")
    in_degree = edges.groupby(["day", "target"]).source.transform("nunique")
    first = edges.groupby(["day", "source", "target"]).minute.min()
    first.index = first.index.set_names(["day", "target", "source"])   # look up the reverse pair
    reverse_first = edges.join(first.rename("reverse_first"), on=["day", "target", "source"]).reverse_first

    signals = pd.DataFrame(False, index=frame.index, columns=["fan_out", "fan_in", "return_transfer"])
    signals.loc[edges.index, "fan_out"] = out_degree >= FAN_THRESHOLD
    signals.loc[edges.index, "fan_in"] = in_degree >= FAN_THRESHOLD
    signals.loc[edges.index, "return_transfer"] = reverse_first < edges.minute
    return signals


def hubs(edges: pd.DataFrame, limit: int = HUB_LIMIT) -> set:
    """Accounts with more than `limit` distinct counterparties across the period."""
    pairs = edges[["source", "target"]].drop_duplicates()
    degree = pairs.source.value_counts().add(pairs.target.value_counts(), fill_value=0)
    return set(degree.index[degree > limit])


def _timeline(edges: pd.DataFrame) -> dict:
    """(payer, payee) -> sorted [(minute, source_row), ...]."""
    timeline = defaultdict(list)
    ordered = edges.sort_values(["minute", "source_row"])
    for pair in zip(ordered.source, ordered.target, ordered.minute, ordered.source_row):
        timeline[pair[0], pair[1]].append((pair[2], pair[3]))
    return timeline


def _realise(cycle: list, timeline: dict, window: int):
    """Find transfers that go round `cycle` in time order within `window`, or None.

    Tries each account as the starting point and each transfer on the first hop,
    then takes the earliest transfer on every later hop that is not before the
    previous one. Taking the earliest keeps the loop as short as possible.
    """
    size = len(cycle)
    for shift in range(size):
        order = cycle[shift:] + cycle[:shift]
        hops = [(order[i], order[(i + 1) % size]) for i in range(size)]
        for start, first_row in timeline[hops[0]]:
            now, rows = start, [first_row]
            for hop in hops[1:]:
                options = timeline[hop]
                j = bisect_left(options, (now, -1))
                if j == len(options):
                    break
                now, row = options[j]
                rows.append(row)
            else:
                if now - start <= window:
                    return tuple(order), tuple(rows), start, now
    return None


def temporal_cycles(frame: pd.DataFrame, max_length: int = MAX_CYCLE_LENGTH,
                    window: int = WINDOW, hub_limit: int = HUB_LIMIT) -> list[Pattern]:
    edges = transfers(frame)
    blocked = hubs(edges, hub_limit)
    edges = edges.loc[~edges.source.isin(blocked) & ~edges.target.isin(blocked)]
    graph = nx.DiGraph()
    graph.add_edges_from(edges[["source", "target"]].drop_duplicates().itertuples(index=False, name=None))
    # An account on a cycle must both send and receive; peel off the rest first.
    while dead := [n for n in graph if graph.in_degree(n) == 0 or graph.out_degree(n) == 0]:
        graph.remove_nodes_from(dead)
    timeline = _timeline(edges)
    patterns = []
    for cycle in nx.simple_cycles(graph, length_bound=max_length):
        if len(cycle) < 3:      # two-account loops are the return-transfer rule
            continue
        found = _realise(cycle, timeline, window)
        if found:
            patterns.append(Pattern("cycle", *found))
    return sorted(patterns, key=lambda p: (p.start, p.accounts))


def scatter_gather(frame: pd.DataFrame, min_middle: int = MIN_MIDDLE,
                   window: int = WINDOW, hub_limit: int = HUB_LIMIT) -> list[Pattern]:
    edges = transfers(frame)
    blocked = hubs(edges, hub_limit)
    first_leg = edges.loc[~edges.target.isin(blocked), ["source", "target", "minute", "source_row"]]
    first_leg.columns = ["source", "middle", "sent", "row_in"]
    second_leg = edges.loc[~edges.source.isin(blocked), ["source", "target", "minute", "source_row"]]
    second_leg.columns = ["middle", "sink", "forwarded", "row_out"]

    # Cheap screen on pair-level first/last times, then check individual transfers.
    earliest = first_leg.groupby(["source", "middle"]).sent.min().reset_index()
    latest = second_leg.groupby(["middle", "sink"]).forwarded.max().reset_index()
    screen = earliest.merge(latest, on="middle")
    screen = screen.loc[(screen.source != screen.sink) & (screen.sent <= screen.forwarded)]
    wide = screen.groupby(["source", "sink"]).middle.nunique()
    candidates = wide.index[wide >= min_middle]
    if candidates.empty:
        return []
    keep = screen.set_index(["source", "sink"]).loc[candidates].reset_index()[["source", "middle", "sink"]]

    legs = (keep.merge(first_leg, on=["source", "middle"])
                .merge(second_leg, on=["middle", "sink"]))
    legs = legs.loc[(legs.sent <= legs.forwarded) & (legs.forwarded - legs.sent <= window)]
    patterns = []
    for (source, sink), group in legs.groupby(["source", "sink"]):
        middles = sorted(group.middle.unique())
        if len(middles) < min_middle:
            continue
        rows = tuple(sorted(set(group.row_in) | set(group.row_out)))
        patterns.append(Pattern("scatter_gather", (source, *middles, sink), rows,
                                int(group.sent.min()), int(group.forwarded.max())))
    return sorted(patterns, key=lambda p: (p.start, p.accounts))


def flag_patterns(frame: pd.DataFrame, patterns: list[Pattern]) -> pd.DataFrame:
    """Per-transfer flag for each pattern kind plus the IDs of the patterns it belongs to."""
    flags = pd.DataFrame({"cycle": False, "scatter_gather": False, "pattern_ids": ""}, index=frame.index)
    row_to_index = pd.Series(frame.index, index=frame.source_row)
    members = defaultdict(list)
    for number, pattern in enumerate(patterns, 1):
        for row in pattern.rows:
            members[row].append((pattern.kind, number))
    if not members:
        return flags
    index = row_to_index.loc[list(members)].to_numpy()
    kinds = [{kind for kind, _ in members[row]} for row in members]
    flags.loc[index, "cycle"] = np.array(["cycle" in k for k in kinds])
    flags.loc[index, "scatter_gather"] = np.array(["scatter_gather" in k for k in kinds])
    flags.loc[index, "pattern_ids"] = [" ".join(f"P{n}" for _, n in members[row]) for row in members]
    return flags
