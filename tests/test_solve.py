from src.data_loader import load_courses, load_fixed_and_blocked
from src.domain import generate_components
from src.config import load_config, load_availability
from src.solve import solve

XLSX = "data/courses.xlsx"
AVCILAR = "data/faculty_rooms.xlsx"


def _load():
    # production parity: mirror main.py's load pipeline exactly
    from src.data_loader import apply_instructor_overrides
    cfg = load_config("config.yaml")
    av = load_availability("availability.yaml")
    courses = load_courses(XLSX, "GÜZ")
    apply_instructor_overrides(courses, cfg.instructor_overrides)
    for c in courses:
        if c.name in cfg.ctype_overrides:
            c.ctype = cfg.ctype_overrides[c.name]
    courses = [c for c in courses if not cfg.is_excluded(c)]
    comps = generate_components(courses, cfg.lab_courses, cfg.split_tu, cfg.uygulama_assistants, cfg.single_block_courses)
    our = set(sum(cfg.room_pools.values(), [])) | {cfg.lab_room, cfg.amfi_room}
    fixed, blocked = load_fixed_and_blocked(AVCILAR, our)
    return comps, fixed, blocked, cfg, av


def test_real_instance_feasible_and_complete():
    comps, fixed, blocked, cfg, av = _load()
    res = solve(comps, fixed, blocked, cfg, av, time_limit=60, optimize=False)
    assert res.feasible
    assert len(res.blocks) == len(comps)   # every component placed
