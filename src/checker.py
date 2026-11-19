"""Independent hard-constraint verifier.

Recomputes every hard rule from the ScheduledBlock table alone (never from the
CP-SAT model), so a modeling bug cannot hide itself. Returns human-readable
violation strings; an empty list means the schedule is valid.
"""
from collections import defaultdict

from src import timegrid as tg


def _cells(day, period, length):
    return [(day, period + k) for k in range(length)]


def _overlaps(a, b):
    """Do two blocks (day, period, length) overlap in time?"""
    if a.day != b.day:
        return False
    return a.period < b.period + b.length and b.period < a.period + a.length


def _group_pick_k(config, group):
    for name, (g, k) in config.groups.items():
        if g == group:
            return k
    return None


def _pin_target(fx, config):
    """Cohort a fixed session belongs to, mirroring model.pin_cohort."""
    for pattern, co in config.fixed_session_cohorts.items():
        if pattern in fx.course_name:
            lvl, sem = co.rsplit("-", 1)
            return (lvl, int(sem))
    lvl, sem = getattr(config, "default_pin_cohort", "Lisans-1").rsplit("-", 1)
    return (lvl, int(sem))


def _pin_group(fx, config):
    """Elective group letter of a fixed session, mirroring model.pin_group."""
    for pattern, g in getattr(config, "fixed_session_groups", {}).items():
        if pattern in fx.course_name:
            return g
    return None


def check(blocks, fixed, blocked, config, availability=None, courses=None):
    violations = []
    room_occ = {}
    instr_occ = {}

    # --- pins/blocks occupy rooms and (for pins) instructors ---
    for fx in fixed:
        for cell in _cells(fx.day, fx.period, fx.length):
            room_occ.setdefault((fx.room, cell), fx.course_name)
            if fx.instructor:
                instr_occ.setdefault((fx.instructor, cell), fx.course_name)
    for bl in blocked:
        for cell in _cells(bl.day, bl.period, bl.length):
            room_occ.setdefault((bl.room, cell), bl.label)

    first_period = 1 if config.forbid_first_period else 0
    last_period = (tg.NUM_PERIODS - 1) if config.unlock_evening else config.latest_period - 1

    for b in blocks:
        # window bounds: P1 ban, latest_period, day-crossing
        if b.period < first_period and b.course_name not in getattr(config, "allow_first_courses", set()):
            violations.append(f"P1 violation: {b.course_name} {b.kind} starts at P{b.period + 1}")
        if b.period + b.length - 1 > last_period:
            violations.append(
                f"late violation: {b.course_name} {b.kind} ends P{b.period + b.length} "
                f"past P{last_period + 1}")
        if b.period + b.length - 1 >= tg.NUM_PERIODS:
            violations.append(f"day-crossing: {b.course_name} {b.kind} at day {b.day} p{b.period}")
        # room eligibility: dual-room, lab-only, amfi-only, lab rules, pools
        b_rooms = [p.strip() for p in b.room.split(" / ")]
        if b.course_name in getattr(config, "dual_room_courses", set()) and b.kind != "L":
            pool = "grad" if b.level in ("YL", "DR") else "lisans"
            if len(b_rooms) != 2 or b_rooms[1] != config.lab_room \
                    or b_rooms[0] not in set(config.room_pools[pool]):
                violations.append(
                    f"dual-room violation: {b.course_name} must hold a classroom + the lab, "
                    f"got {b.room}")
        elif b.course_name in getattr(config, "lab_only_courses", set()):
            if b.room != config.lab_room:
                violations.append(
                    f"lab-only violation: {b.course_name} placed in {b.room}, not the computer lab")
        elif b.course_name in config.amfi_courses and b.kind != "L":
            aa = getattr(config, "amfi_assignments", {})
            expected = aa.get(f"{b.course_name}:{b.kind}") or aa.get(b.course_name, config.amfi_room)
            allowed_amfi = list(expected) if isinstance(expected, list) else [expected]
            if b.room not in allowed_amfi:
                violations.append(
                    f"amfi violation: {b.course_name} placed in {b.room}, expected {allowed_amfi}")
        elif b.kind == "L":
            if b.room != config.lab_room:
                violations.append(f"lab violation: {b.course_name} L-hours in {b.room}, not the lab")
        else:
            pool = "grad" if b.level in ("YL", "DR") else "lisans"
            allowed = set(config.room_pools[pool])
            if pool == "grad" or b.course_name in config.lab_courses:
                allowed.add(config.lab_room)
            if b.room not in allowed:
                violations.append(f"room ineligible: {b.course_name} in {b.room} (level {b.level})")
        # per-course required room (e.g. high-enrollment courses -> D-731)
        req = getattr(config, "course_rooms", {}).get(b.course_name)
        if req and not any(rm in req for rm in b_rooms):
            violations.append(
                f"course-room violation: {b.course_name} in {b.room}, required {req}")
        # campus-wide blocked slots (e.g. Friday prayer)
        for bs in getattr(config, "blocked_slots", []):
            bd = tg.day_index(bs["day"])
            for p in bs["periods"]:
                if b.day == bd and b.period <= p - 1 <= b.period + b.length - 1:
                    violations.append(
                        f"blocked-slot violation: {b.course_name} covers {bs['day']} P{p}")
        # per-course day restriction
        allowed_days = getattr(config, "course_days", {}).get(b.course_name)
        if allowed_days and tg.DAYS[b.day] not in allowed_days:
            violations.append(
                f"course-day violation: {b.course_name} on {tg.DAYS[b.day]}, "
                f"allowed {allowed_days}")
        # per-course hard time window (1-based min start / max last occupied period)
        cw = getattr(config, "course_windows", {}).get(b.course_name)
        if cw:
            if cw.get("min") and b.period + 1 < int(cw["min"]):
                violations.append(
                    f"course-window violation: {b.course_name} starts P{b.period + 1} "
                    f"before P{cw['min']}")
            if cw.get("max") and b.period + b.length > int(cw["max"]):
                violations.append(
                    f"course-window violation: {b.course_name} occupies P{b.period + b.length} "
                    f"past P{cw['max']}")
        # availability windows
        if availability is not None:
            for (d, p) in _cells(b.day, b.period, b.length):
                if availability.is_blocked(b.instructor, d, p):
                    violations.append(
                        f"availability violation: {b.instructor} teaches {b.course_name} "
                        f"in blocked slot ({tg.DAYS[d]}, P{p + 1})")
                    break
        # double-booking (a dual-room block occupies BOTH its rooms)
        for cell in _cells(b.day, b.period, b.length):
            for rm in b_rooms:
                rk = (rm, cell)
                if rk in room_occ:
                    violations.append(f"room clash: {rm} {cell} — {b.course_name} vs {room_occ[rk]}")
                room_occ[rk] = b.course_name
            ik = (b.instructor, cell)
            if ik in instr_occ:
                violations.append(
                    f"instructor clash: {b.instructor} {cell} — {b.course_name} vs {instr_occ[ik]}")
            instr_occ[ik] = b.course_name

    # --- same course: time-ADJACENT blocks must share the room ---
    by_course = defaultdict(list)
    for b in blocks:
        if b.kind != "L":
            by_course[(b.level, b.semester, b.course_name)].append(b)
    for key, bs in by_course.items():
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                u, v = bs[i], bs[j]
                adjacent = u.day == v.day and (u.period + u.length == v.period
                                               or v.period + v.length == u.period)
                if adjacent and u.room != v.room:
                    violations.append(
                        f"split-room violation: {key[2]} adjacent blocks in "
                        f"{u.room} and {v.room}")

    # --- student-conflict rules per Lisans cohort ---
    by_cohort = defaultdict(list)
    ctype_of = {}
    if courses is not None:
        ctype_of = {(c.level, c.semester, c.name): c.ctype for c in courses}
    for b in blocks:
        if b.level == "Lisans":
            by_cohort[(b.level, b.semester)].append(b)

    for cohort, bs in by_cohort.items():
        mand = [b for b in bs if ctype_of.get((b.level, b.semester, b.course_name)) == "Z"] \
            if ctype_of else [b for b in bs if not b.group]
        elect = [b for b in bs if b not in mand]
        # mandatory pairwise disjoint
        for i in range(len(mand)):
            for j in range(i + 1, len(mand)):
                if _overlaps(mand[i], mand[j]):
                    violations.append(
                        f"mandatory clash {cohort}: {mand[i].course_name} vs {mand[j].course_name}")
        # electives vs mandatory
        for e in elect:
            for z in mand:
                if _overlaps(e, z):
                    violations.append(
                        f"elective-vs-mandatory clash {cohort}: {e.course_name} vs {z.course_name}")
        # elective structure: different groups -> disjoint; same pick-k group ->
        # overlap allowed ONLY as an exact shared slot (same day+period, no
        # partial overlap); pick-1 groups may overlap freely
        for i in range(len(elect)):
            for j in range(i + 1, len(elect)):
                u, v = elect[i], elect[j]
                if not u.group or not v.group or not _overlaps(u, v):
                    continue
                if u.group != v.group:
                    violations.append(
                        f"cross-group elective clash {cohort}: {u.course_name} ({u.group}) "
                        f"vs {v.course_name} ({v.group})")
                    continue
                if _group_pick_k(config, u.group) == 1:
                    continue
                if not (u.day == v.day and u.period == v.period):
                    violations.append(
                        f"partial-overlap violation {cohort}: {u.course_name} vs "
                        f"{v.course_name} (group {u.group}) overlap without sharing a slot")
        # pick-k groups must keep >= k distinct time-slots (selection guarantee)
        by_group_slots = defaultdict(set)
        by_group_n = defaultdict(int)
        for e in elect:
            if e.group and _group_pick_k(config, e.group) and _group_pick_k(config, e.group) >= 2:
                by_group_slots[e.group].add((e.day, e.period))
                by_group_n[e.group] += 1
        for g, slots in by_group_slots.items():
            k = _group_pick_k(config, g)
            if len(slots) < k:
                violations.append(
                    f"selection violation {cohort}: group {g} has {len(slots)} distinct "
                    f"slots for pick-{k}")
        # max parallel electives
        if config.max_parallel_electives > 0:
            cell_count = defaultdict(list)
            for e in elect:
                for cell in _cells(e.day, e.period, e.length):
                    cell_count[cell].append(e.course_name)
            for cell, names in cell_count.items():
                if len(names) > config.max_parallel_electives:
                    violations.append(
                        f"parallel-elective cap {cohort}: {len(names)} electives at "
                        f"{cell}: {names}")

    # --- fixed-pin clashes: EVERY course of the pinned cohort (any level, incl.
    # YL/DR when fixed_session_cohorts targets them) must avoid the pin ---
    for fx in fixed:
        target = _pin_target(fx, config)
        pg = _pin_group(fx, config)
        for b in blocks:
            if (b.level, b.semester) != target:
                continue
            if pg is not None and b.group == pg:
                continue  # same pick-1 elective group as the pin: students take one OR the other
            if b.day == fx.day and b.period < fx.period + fx.length \
                    and fx.period < b.period + b.length:
                violations.append(
                    f"fixed-pin clash {target}: {b.course_name} overlaps "
                    f"pinned '{fx.course_name[:40]}'")

    # --- free-day guarantee (counts fixed pins for their cohort) ---
    if config.require_free_day:
        used_days = defaultdict(set)
        for b in blocks:
            used_days[(b.level, b.semester)].add(b.day)
        for fx in fixed:
            used_days[_pin_target(fx, config)].add(fx.day)
        for cohort, days in used_days.items():
            if len(days) >= 5:
                violations.append(f"free-day violation: cohort {cohort} has class all 5 days")

    return violations
