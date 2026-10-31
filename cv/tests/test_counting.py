import pytest

from cv_service.counting import Smoother, count_confidence, count_people


def test_counts_only_above_threshold():
    assert count_people([0.9, 0.41, 0.4, 0.39, 0.1], conf=0.4) == 3
    assert count_people([], conf=0.4) == 0


def test_confidence_is_mean_of_counted():
    assert count_confidence([0.9, 0.7, 0.2], conf=0.4) == 0.8


def test_confidence_with_nobody_counted():
    assert count_confidence([], conf=0.4) == 1.0
    assert count_confidence([0.3, 0.1], conf=0.4) == 0.7


def test_smoother_takes_median_of_window():
    s = Smoother(window=3)
    assert s.push(4) == 4
    assert s.push(10) == 4  # median_low of [4, 10]
    assert s.push(5) == 5
    assert s.push(5) == 5  # window is now [10, 5, 5]
    assert s.push(0) == 5  # [5, 5, 0]


def test_smoother_drops_single_frame_spike():
    s = Smoother(window=5)
    results = [s.push(v) for v in [3, 3, 3, 12, 3]]
    assert results[-1] == 3


def test_smoother_rejects_bad_window():
    with pytest.raises(ValueError):
        Smoother(window=0)
