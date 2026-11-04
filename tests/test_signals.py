"""Hand-built graphs where the right answer is obvious."""
import pandas as pd
import pytest

from aml.data import COLUMNS, prepare
from aml.signals import (daily_signals, flag_patterns, hubs, scatter_gather, temporal_cycles,
                         transfers)


def make(rows, day="2022/09/01"):
    """rows: (payer, payee, "HH:MM" or "YYYY/MM/DD HH:MM", label)."""
    raw = []
    for payer, payee, when, *label in rows:
        stamp = when if "/" in when else f"{day} {when}"
        raw.append([stamp, "001", payer, "001", payee, "10.00", "US Dollar", "10.00", "US Dollar",
                    "ACH", str(label[0] if label else 0)])
    frame, accounts = prepare(pd.DataFrame(raw, columns=COLUMNS, dtype=str))
    return frame, list(accounts)


def names(pattern, accounts):
    return [accounts[a].split("/")[1] for a in pattern.accounts]


# Loading

def test_source_rows_count_the_header_as_line_one():
    frame, _ = make([("A", "B", "09:00"), ("B", "C", "09:05")])
    assert list(frame.source_row) == [2, 3]


def test_same_account_number_at_different_banks_is_a_different_account():
    raw = pd.DataFrame([["2022/09/01 09:00", "001", "A", "002", "A", "1", "US Dollar", "1",
                         "US Dollar", "ACH", "0"]], columns=COLUMNS, dtype=str)
    frame, _ = prepare(raw)
    assert len(transfers(frame)) == 1


# Daily rules

def test_fan_out_needs_ten_distinct_recipients_not_ten_payments():
    frame, _ = make([("A", str(i), "09:00") for i in range(9)] + [("A", "0", "10:00")] * 5)
    assert not daily_signals(frame).fan_out.any()
    frame, _ = make([("A", str(i), "09:00") for i in range(10)])
    assert daily_signals(frame).fan_out.all()


def test_fan_in_counts_distinct_payers():
    frame, _ = make([(str(i), "B", "09:00") for i in range(10)] + [("X", "Y", "09:00")])
    signals = daily_signals(frame)
    assert signals.fan_in.sum() == 10 and not signals.fan_in.iloc[-1]


def test_fan_rules_reset_each_day():
    rows = [("A", str(i), "2022/09/01 09:00") for i in range(5)]
    rows += [("A", str(i), "2022/09/02 09:00") for i in range(5, 10)]
    frame, _ = make(rows)
    assert not daily_signals(frame).fan_out.any()


def test_return_transfer_needs_a_strictly_earlier_reverse_payment():
    frame, _ = make([("X", "Y", "09:00"), ("Y", "X", "09:00"), ("Y", "X", "09:30")])
    assert list(daily_signals(frame).return_transfer) == [False, False, True]


def test_self_transfers_never_trigger_a_signal():
    frame, _ = make([("A", "A", "09:00")] * 12 + [("A", str(i), "09:00") for i in range(10)])
    signals = daily_signals(frame)
    assert not signals.iloc[:12].any().any()
    assert signals.iloc[12:].fan_out.all()


# Temporal cycles

def test_cycle_in_time_order_is_found():
    frame, accounts = make([("A", "B", "09:00"), ("B", "C", "10:00"), ("C", "A", "11:00")])
    [cycle] = temporal_cycles(frame)
    assert names(cycle, accounts) == ["A", "B", "C"]
    assert cycle.rows == (2, 3, 4)


def test_cycle_can_start_at_any_account():
    frame, accounts = make([("A", "B", "11:00"), ("B", "C", "09:00"), ("C", "A", "10:00")])
    [cycle] = temporal_cycles(frame)
    assert names(cycle, accounts) == ["B", "C", "A"]


def test_loop_whose_hops_run_backwards_in_time_is_not_a_cycle():
    # A->B at 11:00, B->C at 10:00, C->A at 09:00: no ordering of these goes round in time.
    frame, _ = make([("A", "B", "11:00"), ("B", "C", "10:00"), ("C", "A", "09:00")])
    assert temporal_cycles(frame) == []


def test_cycle_must_close_inside_the_window():
    rows = [("A", "B", "2022/09/01 09:00"), ("B", "C", "2022/09/02 09:00"), ("C", "A", "2022/09/09 09:00")]
    frame, _ = make(rows)
    assert temporal_cycles(frame) == []
    assert len(temporal_cycles(frame, window=10 * 24 * 60)) == 1


def test_cycle_can_cross_midnight():
    rows = [("A", "B", "2022/09/01 23:50"), ("B", "C", "2022/09/02 00:10"), ("C", "A", "2022/09/02 01:00")]
    frame, _ = make(rows)
    assert len(temporal_cycles(frame)) == 1


def test_two_account_loops_are_left_to_the_return_rule():
    frame, _ = make([("A", "B", "09:00"), ("B", "A", "10:00")])
    assert temporal_cycles(frame) == []


def test_cycle_longer_than_the_limit_is_ignored():
    chain = list("ABCDE")
    rows = [(chain[i], chain[(i + 1) % 5], f"{9 + i:02d}:00") for i in range(5)]
    frame, _ = make(rows)
    assert temporal_cycles(frame, max_length=4) == []
    assert len(temporal_cycles(frame, max_length=5)) == 1


def test_hub_accounts_are_not_cycle_members():
    rows = [("A", "B", "09:00"), ("B", "C", "10:00"), ("C", "A", "11:00")]
    rows += [("B", f"shop{i}", "12:00") for i in range(31)]          # B now has 33 counterparties
    frame, _ = make(rows)
    assert temporal_cycles(frame) == []


def test_hubs_count_distinct_counterparties_in_both_directions():
    frame, accounts = make([("A", str(i), "09:00") for i in range(20)] + [(str(i), "A", "10:00") for i in range(20, 31)])
    assert {accounts[a] for a in hubs(transfers(frame))} == {"001/A"}


# Scatter-gather

def spread(middles, sink_times):
    rows = [("S", m, "09:00") for m in middles]
    rows += [(m, "T", when) for m, when in zip(middles, sink_times)]
    return make(rows)


def test_scatter_gather_needs_three_intermediaries():
    frame, _ = spread(["M1", "M2"], ["10:00", "10:00"])
    assert scatter_gather(frame) == []
    frame, accounts = spread(["M1", "M2", "M3"], ["10:00", "10:00", "10:00"])
    [pattern] = scatter_gather(frame)
    assert names(pattern, accounts) == ["S", "M1", "M2", "M3", "T"]
    assert len(pattern.rows) == 6


def test_intermediary_must_forward_after_receiving():
    frame, _ = spread(["M1", "M2", "M3"], ["10:00", "10:00", "08:00"])
    assert scatter_gather(frame) == []


def test_forwarding_must_happen_inside_the_window():
    frame, _ = spread(["M1", "M2", "M3"], ["10:00", "10:00", "2022/09/08 10:00"])
    assert scatter_gather(frame) == []


def test_hub_intermediaries_do_not_count():
    rows = [("S", m, "09:00") for m in ["M1", "M2", "M3"]] + [(m, "T", "10:00") for m in ["M1", "M2", "M3"]]
    rows += [("M3", f"shop{i}", "12:00") for i in range(30)]
    frame, _ = make(rows)
    assert scatter_gather(frame) == []


# Flags

def test_flags_mark_every_transfer_in_a_pattern():
    rows = [("A", "B", "09:00"), ("B", "C", "10:00"), ("C", "A", "11:00"), ("X", "Y", "12:00")]
    frame, _ = make(rows)
    flags = flag_patterns(frame, temporal_cycles(frame))
    assert list(flags.cycle) == [True, True, True, False]
    assert list(flags.pattern_ids) == ["P1", "P1", "P1", ""]
    assert not flags.scatter_gather.any()


@pytest.mark.parametrize("label", [0, 1])
def test_signals_do_not_depend_on_labels(label):
    rows = [("A", "B", "09:00", label), ("B", "C", "10:00", label), ("C", "A", "11:00", label)]
    frame, _ = make(rows)
    assert len(temporal_cycles(frame)) == 1


def test_entity_lookup_ignores_bank_id_zero_padding():
    from aml.data import entity_key, entity_name
    assert entity_key("0126/813426341") == entity_key("126/813426341") == "126/813426341"
    assert entity_name({"126/813426341": "Country #1"}, "0126/813426341") == "Country #1"
    assert entity_name({}, "000/X") == "unknown"
