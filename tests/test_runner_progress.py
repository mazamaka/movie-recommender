"""Unit tests for finished/dropped extraction logic in pipeline runner."""


def _make_items(*progress_specs):
    """Build sync items list from (tmdb_id, time_watched, duration) tuples."""
    return [
        {"tmdb_id": tid, "type": "movie", "time_watched": t, "duration": d}
        for tid, t, d in progress_specs
    ]


def _extract_progress_signals(items):
    """Wrapper to call the function under test (will be added in runner.py)."""
    from movie_recommender.pipeline.runner import _extract_progress_signals as fn
    return fn(items)


def test_finished_above_80_percent():
    """Items with watch ratio > 0.80 land in 'finished'."""
    items = _make_items(
        (101, 850, 1000),    # 0.85
        (102, 950, 1000),    # 0.95
        (103, 1000, 1000),   # 1.00
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == {101, 102, 103}
    assert signals["dropped"] == set()


def test_dropped_in_10_to_50_range():
    """Items with watch ratio in [0.10, 0.50] land in 'dropped'."""
    items = _make_items(
        (201, 100, 1000),   # 0.10
        (202, 300, 1000),   # 0.30
        (203, 500, 1000),   # 0.50
    )
    signals = _extract_progress_signals(items)
    assert signals["dropped"] == {201, 202, 203}
    assert signals["finished"] == set()


def test_grey_zone_excluded():
    """Items with ratio in (0.50, 0.80] are NOT classified."""
    items = _make_items(
        (301, 550, 1000),   # 0.55
        (302, 700, 1000),   # 0.70
        (303, 800, 1000),   # 0.80 — boundary, NOT > 0.80, so excluded
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == set()
    assert signals["dropped"] == set()


def test_below_10_percent_excluded():
    """Items with ratio < 0.10 are NOT classified."""
    items = _make_items(
        (401, 50, 1000),    # 0.05
        (402, 90, 1000),    # 0.09
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == set()
    assert signals["dropped"] == set()


def test_missing_duration_excluded():
    """Items without duration (or duration <= 0) are NOT classified — protects from ZeroDivisionError."""
    items = _make_items(
        (501, 500, None),   # no duration
        (502, 500, 0),      # zero duration
        (503, None, 1000),  # no time_watched but has duration
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == set()
    assert signals["dropped"] == set()
