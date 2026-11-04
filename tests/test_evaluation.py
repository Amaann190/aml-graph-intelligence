"""Metric arithmetic and queue ordering on tiny hand-checked examples."""
import pandas as pd
import pytest

from aml.evaluation import build_cases, labelled_cases, queue_report, rank, score


def test_score_matches_hand_calculation():
    flagged = pd.Series([True, True, True, True, False, False, False, False, False, False])
    label = pd.Series([1, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    result = score(flagged, label)
    # 1 of 4 flags is labelled; 1 of 2 labelled transfers flagged; base rate 2/10.
    assert result["precision"] == pytest.approx(0.25)
    assert result["recall"] == pytest.approx(0.5)
    assert result["lift"] == pytest.approx(1.25)


def test_score_handles_no_flags():
    assert score(pd.Series([False, False]), pd.Series([1, 0]))["precision"] == 0.0


def frame_and_signals():
    frame = pd.DataFrame({
        "day": ["d1", "d1", "d1", "d1", "d2"],
        "source": [1, 1, 2, 3, 1],
        "source_row": [10, 11, 12, 13, 14],
        "label": [0, 0, 0, 1, 0],
    })
    signals = pd.DataFrame({
        "fan_out": [True, True, True, False, True],
        "fan_in": [False, True, False, False, False],
        "return_transfer": [False, False, False, False, False],
        "cycle": [False, False, False, True, False],
        "scatter_gather": [False, False, False, False, False],
        "pattern_ids": ["", "", "", "P1", ""],
    })
    return frame, signals


def test_cases_group_by_payer_and_day():
    cases = build_cases(*frame_and_signals()).set_index(["day", "source"])
    assert cases.loc[("d1", 1)].transfers == 2
    assert cases.loc[("d1", 1)].max_overlap == 2
    assert cases.loc[("d1", 1)].example_row == 11
    assert cases.loc[("d1", 3)].graph_patterns == 1


def test_graph_ranking_puts_pattern_cases_first():
    queue = rank(build_cases(*frame_and_signals()))
    assert list(zip(queue.day, queue.source))[:2] == [("d1", 3), ("d1", 1)]


def test_graph_ranking_keeps_the_original_order_after_pattern_cases():
    frame, signals = frame_and_signals()
    cases = build_cases(frame, signals)
    with_graph = rank(cases)
    original = rank(cases, use_graph=False)
    rest = with_graph.loc[with_graph.graph_patterns == 0]
    assert list(zip(rest.day, rest.source)) == list(zip(original.day, original.source))


def test_daily_ranking_ignores_graph_only_cases():
    queue = rank(build_cases(*frame_and_signals()), use_graph=False)
    assert ("d1", 3) not in set(zip(queue.day, queue.source))


def test_queue_report_counts_hits_at_each_depth():
    frame, signals = frame_and_signals()
    queue = rank(build_cases(frame, signals))
    report = queue_report(queue, labelled_cases(frame), depths=[1, 2])
    assert report["precision_at_1"] == 1.0
    assert report["precision_at_2"] == 0.5
    assert report["candidate_recall"] == 1.0
