from src.data_loader import (load_courses, canonicalize_instructor,
                             load_fixed_and_blocked, _runs)
from src.config import load_config

XLSX = "data/courses.xlsx"
AVCILAR = "data/faculty_rooms.xlsx"


def _our_rooms():
    # production parity: the exact set main.py builds
    cfg = load_config("config.yaml")
    return set(sum(cfg.room_pools.values(), [])) | {cfg.lab_room, cfg.amfi_room}


def test_canonicalize_collapses_whitespace():
    assert canonicalize_instructor("  Test   Hoca ") == "Test Hoca"


def test_load_guz_counts():
    cs = load_courses(XLSX, "GÜZ")
    assert len(cs) == 50
    by_level = {}
    for c in cs:
        by_level[c.level] = by_level.get(c.level, 0) + 1
    assert by_level == {"Lisans": 32, "YL": 9, "DR": 9}


def test_hours_are_ints_and_flags():
    cs = load_courses(XLSX, "GÜZ")
    orI = next(c for c in cs if c.name == "Operations Research I")
    assert (orI.T, orI.U, orI.L) == (3, 2, 0) and orI.ctype == "Z"
    eko = next(c for c in cs if c.name == "Ekonomi")
    assert eko.dept_faculty is False


def test_fixed_sessions_extracted_with_instructor_match():
    known = {c.instructor for c in load_courses(XLSX, "GÜZ")}
    fixed, blocked = load_fixed_and_blocked(AVCILAR, _our_rooms(), known_instructors=known)
    names = {f.course_name.split("(")[0].strip() for f in fixed}
    assert any("Matematik I" in n for n in names)
    assert any("Bil. Tem" in n for n in names)
    # the department instructor named inside a faculty-sheet cell is matched to the course master
    assert any(f.instructor == "Öğr. Üyesi 07" for f in fixed)


def test_blocked_excludes_oneoff_teknik_oturum():
    fixed, blocked = load_fixed_and_blocked(AVCILAR, _our_rooms())
    assert not any("Oturum" in b.label for b in blocked)


def test_runs_splits_noncontiguous_periods():
    assert _runs([1, 2, 3]) == [[1, 2, 3]]
    assert _runs([1, 2, 6, 7]) == [[1, 2], [6, 7]]
    assert _runs([4]) == [[4]]
