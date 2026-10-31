from reliefvision.passcount import PassCounter


def seen(counter, ids, now, score=0.9, times=3):
    for _ in range(times):
        counter.observe([(i, score) for i in ids], now)


def test_people_stay_counted_after_leaving_frame():
    c = PassCounter()
    c.start(0)
    seen(c, [1, 2], now=1)
    seen(c, [3], now=2)  # 1 and 2 walked out of view, 3 came in
    assert c.running() == 3


def test_pass_total_is_published_and_replaced_by_the_next_pass():
    c = PassCounter()
    c.start(0)
    seen(c, [1, 2, 3], now=1)
    assert c.end() == 3
    assert c.published() == (3, 0.9)
    c.start(10)
    seen(c, [7], now=11)
    assert c.published() == (3, 0.9)  # unchanged while the recount runs
    c.end()
    assert c.published()[0] == 1  # line got shorter: count goes down


def test_running_count_shown_before_first_pass_finishes():
    c = PassCounter()
    c.start(0)
    seen(c, [1, 2], now=1)
    assert c.published() == (2, 0.9)


def test_brief_tracks_and_low_scores_are_ignored():
    c = PassCounter(min_hits=3, conf=0.4)
    c.start(0)
    seen(c, [1], now=1, times=2)
    seen(c, [2], now=1, score=0.3)
    c.observe([(None, 0.95)], now=1)
    assert c.running() == 0


def test_auto_ends_after_gap_with_nobody_in_view():
    c = PassCounter(gap_s=5)
    c.start(0, managed=False)
    seen(c, [1, 2], now=1)
    c.observe([], now=5.9)
    assert c.in_pass
    c.observe([], now=6)
    assert not c.in_pass and c.last_total == 2 and c.passes_completed == 1


def test_unmanaged_camera_auto_starts_when_people_appear():
    c = PassCounter()
    c.observe([(1, 0.9)], now=0)
    assert c.in_pass and not c.managed


def test_managed_camera_waits_for_start():
    c = PassCounter()
    c.start(0)
    seen(c, [1], now=1)
    c.end()
    seen(c, [5, 6], now=2)  # robot driving back to the start of the line
    assert not c.in_pass and c.published()[0] == 1


def test_start_mid_pass_discards_progress_and_end_without_pass_is_noop():
    c = PassCounter()
    assert c.end() is None
    c.start(0)
    seen(c, [1, 2], now=1)
    c.start(2)
    assert c.running() == 0
    seen(c, [9], now=3)
    assert c.end() == 1
    assert c.end() == 1 and c.passes_completed == 1


def test_confidence_is_mean_best_score_and_one_when_empty():
    c = PassCounter()
    c.start(0)
    seen(c, [1], now=1, score=0.8)
    c.observe([(1, 0.9)], now=1)
    seen(c, [2], now=1, score=0.6)
    assert c.published() == (2, 0.75)
    c.start(5)
    c.end()
    assert c.published() == (0, 1.0)
