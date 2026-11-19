import argparse
import os
import re
import sys

from src.data_loader import load_courses, load_fixed_and_blocked, apply_instructor_overrides
from src.domain import generate_components
from src.config import load_config, load_availability
from src.solve import solve
from src.checker import check
from src.render_xlsx import render
from src.reports import write_csv


def next_version(directory=".", prefix=""):
    """Next output version number: 1 + highest existing timetable<prefix>_v<N>.xlsx."""
    best = 0
    for name in os.listdir(directory or "."):
        m = re.fullmatch(rf"timetable{re.escape(prefix)}_v(\d+)\.xlsx", name)
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def room_window_blocks(config, fixed):
    """For rooms granted to us only in specific windows (config.room_windows),
    block every cell OUTSIDE the granted windows (cells already occupied by a
    fixed session are left alone — they are their own reservation)."""
    from src.domain import BlockedInterval
    from src import timegrid as tg
    out = []
    for room, wins in config.room_windows.items():
        allowed = set()
        for w in wins:
            di = tg.day_index(w["day"])
            for p in w["periods"]:
                allowed.add((di, p - 1))
        occupied = set()
        for fx in fixed:
            if fx.room == room:
                for k in range(fx.length):
                    occupied.add((fx.day, fx.period + k))
        for di in range(5):
            run = None
            for p in range(tg.NUM_PERIODS + 1):
                free = p < tg.NUM_PERIODS and (di, p) not in allowed and (di, p) not in occupied
                if free and run is None:
                    run = p
                elif not free and run is not None:
                    out.append(BlockedInterval(room, di, run, p - run, "Fakülte tahsisi dışı"))
                    run = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="IE GÜZ timetable optimizer")
    ap.add_argument("--course-xlsx", default="data/courses.xlsx")
    ap.add_argument("--avcilar-xlsx", default="data/faculty_rooms.xlsx")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--availability", default="availability.yaml")
    ap.add_argument("--out", default=None,
                    help="output xlsx; default: auto-versioned timetable_v<N>.xlsx (+ latest copy timetable.xlsx)")
    ap.add_argument("--csv", default=None,
                    help="output csv; default: schedule_v<N>.csv (+ latest copy schedule.csv)")
    ap.add_argument("--time-limit", type=int, default=7200,
                    help="solver budget in seconds (default 2h; stops early once optimality is PROVEN)")
    ap.add_argument("--workers", type=int, default=1,
                    help="default 1 = deterministic (same input -> same schedule); 0 = all CPU cores")
    ap.add_argument("--no-optimize", action="store_true")
    ap.add_argument("--term", default="GÜZ", choices=["GÜZ", "BAHAR"],
                    help="dönem: GÜZ (varsayılan) veya BAHAR — kaynak satırları, fakülte "
                         "sabit programı sayfası ve çıktı adları buna göre seçilir")
    a = ap.parse_args(argv)

    prefix = "" if a.term == "GÜZ" else "_bahar"
    version = None
    if a.out is None or a.csv is None:
        version = next_version(".", prefix)
    out_path = a.out if a.out is not None else f"timetable{prefix}_v{version}.xlsx"
    csv_path = a.csv if a.csv is not None else f"schedule{prefix}_v{version}.csv"

    cfg = load_config(a.config)
    courses = load_courses(a.course_xlsx, a.term)
    apply_instructor_overrides(courses, cfg.instructor_overrides)
    for c in courses:  # ctype fixes (e.g. a course wrongly marked Z in the master file)
        if c.name in cfg.ctype_overrides:
            c.ctype = cfg.ctype_overrides[c.name]
    dropped = [c.name for c in courses if cfg.is_excluded(c)]
    courses = [c for c in courses if not cfg.is_excluded(c)]
    if dropped:
        print(f"Excluded (açılmayacak) {len(dropped)} course(s): {', '.join(sorted(set(dropped)))}")
    comps = generate_components(courses, cfg.lab_courses, cfg.split_tu, cfg.uygulama_assistants, cfg.single_block_courses)
    # known instructors = post-override course instructors + assistants (for
    # availability-key validation and fixed-pin instructor matching)
    known_instructors = {c.instructor for c in courses} | set(cfg.uygulama_assistants.values())
    av = load_availability(a.availability, known_instructors=known_instructors)
    amfi_rooms = []
    for v in cfg.amfi_assignments.values():
        amfi_rooms += list(v) if isinstance(v, list) else [v]
    our = set(sum(cfg.room_pools.values(), [])) | {cfg.lab_room, cfg.amfi_room} | set(amfi_rooms)
    sheet = "Derslik Programı Güz" if a.term == "GÜZ" else "Derslik Programı Bahar"
    fixed, blocked = load_fixed_and_blocked(a.avcilar_xlsx, our,
                                            known_instructors=known_instructors,
                                            sheet_name=sheet)
    if cfg.room_windows:
        # granted-window rooms: the explicit window grid supersedes per-cell external
        # bookings parsed from the faculty sheet (avoids double-blocking overlaps)
        blocked = [b for b in blocked if b.room not in cfg.room_windows]
        blocked += room_window_blocks(cfg, fixed)

    res = solve(comps, fixed, blocked, cfg, av, time_limit=a.time_limit,
                optimize=not a.no_optimize, workers=(a.workers or None))
    print(f"Solve status: {res.status}  placed={len(res.blocks)}/{len(comps)}  objective={res.objective}")
    if not res.feasible:
        print("INFEASIBLE — no valid timetable under current constraints.")
        return 2
    violations = check(res.blocks, fixed, blocked, cfg, availability=av, courses=courses)
    if violations:
        print(f"CHECKER FOUND {len(violations)} VIOLATIONS:")
        for v in violations[:50]:
            print("  -", v)
        return 3
    render(res.blocks, fixed, cfg, out_path)
    write_csv(res.blocks, csv_path)
    amfi = [b for b in res.blocks if b.course_name in cfg.amfi_courses]
    p1 = [b for b in res.blocks if b.period == 0]
    print(f"OK. Wrote {out_path} and {csv_path}. "
          f"Amfi requests: {len(amfi)}. P1(08:30) dept courses: {len(p1)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
