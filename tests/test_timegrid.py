from src import timegrid as tg


def test_grid_shape():
    assert len(tg.DAYS) == 5
    assert tg.NUM_PERIODS == 13
    assert tg.LAST_DAYTIME_INDEX == 10
    assert len(tg.PERIODS) == 13


def test_day_index():
    assert tg.day_index("Pazartesi") == 0
    assert tg.day_index("Cuma") == 4


def test_flat_is_day_major():
    assert tg.flat(0, 0) == 0
    assert tg.flat(1, 0) == 13
    assert tg.flat(2, 3) == 29


def test_start_label_to_index_variants():
    assert tg.start_label_to_index("08.30 – 09.20") == 0
    assert tg.start_label_to_index("14:00-14:50") == 6
    assert tg.start_label_to_index("18.35-19.25") == 11
    assert tg.start_label_to_index("bogus") is None
