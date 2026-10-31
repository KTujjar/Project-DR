from cv_service.timeutil import iso_from_epoch, parse_iso


def test_matches_js_to_iso_string():
    # new Date(1793400541123).toISOString() === "2026-10-30T22:49:01.123Z"
    assert iso_from_epoch(1793400541.123) == "2026-10-30T22:49:01.123Z"


def test_pads_milliseconds():
    assert iso_from_epoch(0.005).endswith(".005Z")
    assert iso_from_epoch(0) == "1970-01-01T00:00:00.000Z"


def test_round_trip():
    assert abs(parse_iso("2026-10-30T22:49:01.123Z") - 1793400541.123) < 1e-6


def test_string_order_matches_time_order():
    assert iso_from_epoch(1000.009) < iso_from_epoch(1000.010) < iso_from_epoch(1001)
