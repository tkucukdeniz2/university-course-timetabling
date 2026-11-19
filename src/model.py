from dataclasses import dataclass
from collections import defaultdict

from ortools.sat.python import cp_model

from src import timegrid as tg


@dataclass
class CompVars:
    comp: object
    d: object
    p: object
    start: object
    interval: object
    room_lits: dict


class Timetable:
    def __init__(self):
        self.model = cp_model.CpModel()
        self.comp_vars = {}
        self.rooms = []
        self.by_instructor = defaultdict(list)


def _all_rooms(config):
    rooms = []
    for pool in config.room_pools.values():
        rooms += pool
    rooms.append(config.lab_room)
    rooms.append(config.amfi_room)
    for v in getattr(config, "amfi_assignments", {}).values():
        rooms += list(v) if isinstance(v, list) else [v]
    seen, out = set(), []
    for r in rooms:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def pin_cohort(fx, config):
    """Cohort a fixed common session belongs to. Default: config.default_pin_cohort
    (first-year commons of the term). Overridable per session via
    config.fixed_session_cohorts, a mapping of substring -> "Level-Sem"."""
    for pattern, cohort in config.fixed_session_cohorts.items():
        if pattern in fx.course_name:
            level, sem = cohort.rsplit("-", 1)
            return (level, int(sem))
    level, sem = getattr(config, "default_pin_cohort", "Lisans-1").rsplit("-", 1)
    return (level, int(sem))


def pin_group(fx, config):
    """Elective group letter of a FIXED session (e.g. a faculty-scheduled pick-1
    option); None if it is not part of any elective group."""
    for pattern, g in getattr(config, "fixed_session_groups", {}).items():
        if pattern in fx.course_name:
            return g
    return None


def _student_load(comps, config):
    """One representative component per student 'slot': whole pick-1 group -> 1,
    everything else counted individually. Used for the within-day compactness
    objective so alternatives aren't double-counted. Dynamically-paired pick-k
    courses are counted individually — that only OVERestimates busy time, and the
    gap penalty is max(0, span - busy), so pairing can never be hard-forbidden."""
    out, seen = [], set()
    for c in comps:
        g = config.groups.get(c.course.name)
        if g and g[1] == 1:
            key = ("grp", g[0])
        else:
            key = ("cid", c.cid)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def add_student_conflicts(tt, components, config):
    """Enforce that a single student's schedule is clash-free:
    - all mandatory (Z) courses pairwise disjoint;
    - every elective disjoint from the cohort's mandatory courses;
    - within a pick-k (k>=2) elective group, ANY two courses may share a slot —
      but then they must be at EXACTLY the same (day, period); partial overlap is
      forbidden. The solver chooses the pairing dynamically. At most n-k same-slot
      pairs are allowed, so at least k distinct time-slots remain and every
      one-per-slot selection of k courses is clash-free (max_parallel_electives
      separately caps how many share one slot);
    - pick-1 groups: members are alternatives, they may overlap freely;
    - electives in DIFFERENT groups of the same cohort are pairwise disjoint
      (a sem-7 student takes courses from F AND G, so any F pick may combine
      with any G pick)."""
    m = tt.model
    tt.group_same_lits = []   # same-slot bools (all groups) for the soft pairing reward

    def iv(c):
        return tt.comp_vars[c.cid].interval

    by_cohort = defaultdict(list)
    for c in components:
        if c.course.level == "Lisans":
            by_cohort[(c.course.level, c.course.semester)].append(c)
    for (lvl, sem), comps in by_cohort.items():
        mand = [c for c in comps if c.course.ctype == "Z"]
        mand_ivs = [iv(c) for c in mand]
        if len(mand_ivs) > 1:
            m.add_no_overlap(mand_ivs)
        by_group = defaultdict(list)
        for c in comps:
            if c.course.ctype == "S":
                g = config.groups.get(c.course.name)
                by_group[g[0] if g else None].append(c)
        for key, gcomps in by_group.items():
            # every elective is disjoint from the mandatory backbone
            for c in gcomps:
                if mand_ivs:
                    m.add_no_overlap(mand_ivs + [iv(c)])
            if key is None:
                # ungrouped electives: no mutual constraint beyond mandatory-disjointness
                continue
            pick_k = config.groups[gcomps[0].course.name][1]
            n = len(gcomps)
            same_lits = []
            for i in range(n):
                for j in range(i + 1, n):
                    u, v = tt.comp_vars[gcomps[i].cid], tt.comp_vars[gcomps[j].cid]
                    same = m.new_bool_var(f"same_{lvl}{sem}{key}_{u.comp.cid}_{v.comp.cid}")
                    # same-slot => identical (day, period)
                    m.add(u.d == v.d).only_enforce_if(same)
                    m.add(u.p == v.p).only_enforce_if(same)
                    if pick_k >= 2:
                        # NOT same-slot => fully time-disjoint (no partial overlap)
                        before = m.new_bool_var(
                            f"bef_{lvl}{sem}{key}_{u.comp.cid}_{v.comp.cid}")
                        m.add(u.start + u.comp.length <= v.start).only_enforce_if(
                            [same.Not(), before])
                        m.add(v.start + v.comp.length <= u.start).only_enforce_if(
                            [same.Not(), before.Not()])
                    same_lits.append(same)
            if pick_k >= 2 and same_lits:
                # keep >= pick_k distinct slots so any one-per-slot selection works
                # (max(0, ...) guards partial groups with n <= k: then nothing may pair)
                m.add(sum(same_lits) <= max(0, n - pick_k))
            tt.group_same_lits.extend(same_lits)
        # cross-GROUP disjointness: a student co-selects from every group of their
        # cohort (e.g. sem-7: 3 of F plus 1 of G), so electives in different groups
        # must never overlap.
        group_keys = [k for k in by_group if k is not None]
        for a in range(len(group_keys)):
            for b in range(a + 1, len(group_keys)):
                for u in by_group[group_keys[a]]:
                    for v in by_group[group_keys[b]]:
                        m.add_no_overlap([iv(u), iv(v)])


def instructor_used_days(tt, components, fixed):
    """For every instructor, return {instructor: [used bool per weekday]}.

    used[d] is True iff the instructor teaches any component (or has a fixed pinned
    session) on weekday d. Minimizing the total over instructors concentrates each
    instructor's teaching onto as few days as possible.
    """
    m = tt.model
    by_instr = defaultdict(list)
    for c in components:
        by_instr[c.eff_instructor].append(tt.comp_vars[c.cid])
    pin_days = defaultdict(set)
    for fx in fixed:
        if fx.instructor:
            pin_days[fx.instructor].add(fx.day)
    used = {}
    for instr in set(list(by_instr) + list(pin_days)):
        cvs = by_instr.get(instr, [])
        used[instr] = []
        for di in range(5):
            on_bools = []
            for cv in cvs:
                onb = m.new_bool_var(f"ion_{instr}_{cv.comp.cid}_{di}")
                m.add(cv.d == di).only_enforce_if(onb)
                m.add(cv.d != di).only_enforce_if(onb.Not())
                on_bools.append(onb)
            terms = list(on_bools)
            if di in pin_days.get(instr, set()):
                terms.append(1)  # a fixed pin forces this day to be "used"
            any_on = m.new_bool_var(f"iany_{instr}_{di}")
            if terms:
                m.add_max_equality(any_on, terms)
            else:
                m.add(any_on == 0)
            used[instr].append(any_on)
    return used


def build_hard(components, fixed, blocked, config, availability):
    tt = Timetable()
    tt.rooms = _all_rooms(config)
    tt.fixed = fixed
    m = tt.model
    NP = tg.NUM_PERIODS
    last_period = config.latest_period - 1  # last 1-based period -> 0-based index (e.g. P10 -> 9)
    if config.unlock_evening:
        last_period = max(last_period, tg.NUM_PERIODS - 1)
    global_first = 1 if config.forbid_first_period else 0  # HARD: skip P1 (08:30) for dept courses
    cw_matched = {name: False for name in config.course_windows}
    fp_matched = [0] * len(config.fixed_placements)
    for c in components:
        # per-course exemption from the P1 ban (e.g. an early Amfi slot granted by the faculty)
        first_period = 0 if c.course.name in config.allow_first_courses else global_first
        last_start = last_period - c.length + 1
        if last_start < first_period:
            raise ValueError(
                f"Component {c.cid} ({c.course.name}, {c.length}h) cannot fit in the "
                f"allowed daily window P{first_period + 1}..P{last_period + 1}")
        d = m.new_int_var(0, 4, f"d_{c.cid}")
        p = m.new_int_var(first_period, last_start, f"p_{c.cid}")
        # cohort day restriction (e.g. Lisans-5 -> Mon/Tue/Wed only)
        allowed = config.cohort_days.get(f"{c.course.level}-{c.course.semester}")
        if allowed:
            allowed_idx = {tg.day_index(x) for x in allowed}
            for di in range(5):
                if di not in allowed_idx:
                    m.add(d != di)
        # per-course day restriction (e.g. one instructor's undergraduate courses -> Salı)
        allowed_c = config.course_days.get(c.course.name)
        if allowed_c:
            allowed_idx = {tg.day_index(x) for x in allowed_c}
            for di in range(5):
                if di not in allowed_idx:
                    m.add(d != di)
        # fixed placement: pin a component to an exact day/start period (1-based),
        # and optionally to a specific room
        pin_room = None
        for fi, fp in enumerate(config.fixed_placements):
            if c.course.name == fp["course"] and (fp.get("kind") is None or c.kind == fp["kind"]):
                pin_p = int(fp["period"]) - 1
                if not (first_period <= pin_p <= last_start):
                    raise ValueError(
                        f"fixed_placement for {c.course.name} pins period P{fp['period']} "
                        f"outside the legal window P{first_period + 1}..P{last_start + 1}")
                m.add(d == tg.day_index(fp["day"]))
                m.add(p == pin_p)
                if fp.get("room"):
                    pin_room = fp["room"].split(" / ")[0].strip()
                fp_matched[fi] += 1
        start = m.new_int_var(0, 5 * NP, f"st_{c.cid}")
        m.add(start == d * NP + p)
        end = m.new_int_var(0, 5 * NP + c.length, f"en_{c.cid}")
        interval = m.new_interval_var(start, c.length, end, f"iv_{c.cid}")
        # per-course hard time window (1-based config): start >= min, last occupied <= max
        cw = config.course_windows.get(c.course.name)
        if cw:
            cw_matched[c.course.name] = True
            if cw.get("min"):
                m.add(p >= int(cw["min"]) - 1)
            if cw.get("max"):
                m.add(p + c.length - 1 <= int(cw["max"]) - 1)

        # H9 availability: forbid any start that would cover a blocked (day, period)
        campus_blocked = {(tg.day_index(bs["day"]), int(p) - 1)
                          for bs in config.blocked_slots for p in bs["periods"]}
        for di in range(5):
            for pi in range(NP):
                covered = range(pi, pi + c.length)
                if any(availability.is_blocked(c.eff_instructor, di, k) for k in covered) \
                        or any((di, k) in campus_blocked for k in covered):
                    m.add(start != di * NP + pi)
        # H3 room eligibility + room literals + optional intervals for room no-overlap
        room_lits = {}
        room_intervals = {}
        for r in config.eligible_rooms(c):
            lit = m.new_bool_var(f"r_{c.cid}_{r}")
            room_lits[r] = lit
            room_intervals[r] = m.new_optional_interval_var(start, c.length, end, lit, f"oiv_{c.cid}_{r}")
        m.add_exactly_one(room_lits.values())
        if pin_room is not None:
            if pin_room not in room_lits:
                raise ValueError(
                    f"fixed_placement room {pin_room!r} is not an eligible room for "
                    f"{c.course.name} (eligible: {list(room_lits)})")
            m.add(room_lits[pin_room] == 1)
        cv = CompVars(c, d, p, start, interval, room_lits)
        cv.room_intervals = room_intervals
        tt.comp_vars[c.cid] = cv
        tt.by_instructor[c.eff_instructor].append(interval)

    for fi, n in enumerate(fp_matched):
        if n == 0:
            raise ValueError(
                f"fixed_placements entry {config.fixed_placements[fi]} matched no "
                f"schedulable component — check the course name and kind in config.yaml")
    for name, hit in cw_matched.items():
        if not hit:
            raise ValueError(
                f"course_windows entry {name!r} matched no schedulable course — check the name")

    # NOTE: parallel elective blocks are a SOFT preference (rewarded in add_objective),
    # NOT a hard constraint. Correctness comes from cross-block disjointness in
    # add_student_conflicts; block members may run at different times if needed.

    # same course -> same classroom ONLY for time-ADJACENT blocks: if two non-lab
    # components of one course run back-to-back (one ends exactly when the other
    # starts), they must share the room — a contiguous run never switches rooms
    # mid-way. Non-adjacent blocks (other day / separated) may use different rooms.
    course_comps = defaultdict(list)
    for c in components:
        if not c.needs_lab:
            course_comps[c.course.row_id].append(c)
    for rid, cs in course_comps.items():
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                u, v = tt.comp_vars[cs[i].cid], tt.comp_vars[cs[j].cid]
                common = [r for r in u.room_lits if r in v.room_lits]
                if not common:
                    continue
                t1 = m.new_bool_var(f"adj1_{u.comp.cid}_{v.comp.cid}")
                m.add(u.start + u.comp.length == v.start).only_enforce_if(t1)
                m.add(u.start + u.comp.length != v.start).only_enforce_if(t1.Not())
                t2 = m.new_bool_var(f"adj2_{u.comp.cid}_{v.comp.cid}")
                m.add(v.start + v.comp.length == u.start).only_enforce_if(t2)
                m.add(v.start + v.comp.length != u.start).only_enforce_if(t2.Not())
                adj = m.new_bool_var(f"adj_{u.comp.cid}_{v.comp.cid}")
                m.add_bool_or([t1, t2]).only_enforce_if(adj)
                m.add_bool_and([t1.Not(), t2.Not()]).only_enforce_if(adj.Not())
                for r in common:
                    m.add(u.room_lits[r] == v.room_lits[r]).only_enforce_if(adj)

    # pins + blocks: fixed intervals consuming their room (and instructor for pins).
    # Each fixed common session belongs to a student cohort (default Lisans-1;
    # override via config.fixed_session_cohorts substring -> "Level-Sem").
    room_pin_intervals = defaultdict(list)
    cohort_pins = defaultdict(list)   # (level, sem) -> [(interval, day)]
    for i, fx in enumerate(fixed):
        st = fx.day * NP + fx.period
        iv = m.new_interval_var(st, fx.length, st + fx.length, f"pin_{i}")
        room_pin_intervals[fx.room].append(iv)
        if fx.instructor:
            tt.by_instructor[fx.instructor].append(iv)
        cohort = pin_cohort(fx, config)
        cohort_pins[cohort].append(
            (m.new_interval_var(st, fx.length, st + fx.length, f"cpin_{i}"), fx.day,
             pin_group(fx, config)))
    tt.cohort_pin_days = {co: sorted({d for _, d, _g in pins}) for co, pins in cohort_pins.items()}
    for j, bl in enumerate(blocked):
        st = bl.day * NP + bl.period
        iv = m.new_interval_var(st, bl.length, st + bl.length, f"blk_{j}")
        room_pin_intervals[bl.room].append(iv)

    # different-day courses: a split course's components land on DIFFERENT weekdays
    diff_comps = defaultdict(list)
    for c in components:
        if c.course.name in config.different_day_courses:
            diff_comps[c.course.row_id].append(tt.comp_vars[c.cid])
    for rid, cvs in diff_comps.items():
        if len(cvs) < 2:
            raise ValueError(
                f"different_day_courses: {cvs[0].comp.course.name!r} has only one "
                f"component — add it to split_tu so its T and U are separate blocks")
        for i in range(len(cvs)):
            for j in range(i + 1, len(cvs)):
                m.add(cvs[i].d != cvs[j].d)

    # same-day groups: all components of the listed courses share ONE weekday
    for group in config.same_day_courses:
        cvs = [tt.comp_vars[c.cid] for c in components if c.course.name in group]
        if len(cvs) < 2:
            raise ValueError(
                f"same_day_courses entry {group} matched fewer than 2 components — "
                f"check the course names in config.yaml")
        for cv in cvs[1:]:
            m.add(cv.d == cvs[0].d)

    # dual-room courses additionally reserve the computer lab at their slot
    # (first weeks in the classroom, later in the lab -> both must stay free weekly)
    dual_lab_intervals = [cv.interval for cv in tt.comp_vars.values()
                          if cv.comp.course.name in config.dual_room_courses
                          and not cv.comp.needs_lab]

    # H2 room no-overlap
    for r in tt.rooms:
        ivs = [cv.room_intervals[r] for cv in tt.comp_vars.values() if r in cv.room_intervals]
        ivs += room_pin_intervals.get(r, [])
        if r == config.lab_room:
            ivs += dual_lab_intervals
        if len(ivs) > 1:
            m.add_no_overlap(ivs)

    # H1 instructor no-overlap
    for instr, ivs in tt.by_instructor.items():
        if len(ivs) > 1:
            m.add_no_overlap(ivs)

    # H4/H5/H6 cohort + pick-k group disjointness (block-aware; within-block members
    # may overlap since a student takes one per block).
    add_student_conflicts(tt, components, config)

    # At most N same-cohort electives running simultaneously (e.g. max 2 parallel).
    if config.max_parallel_electives > 0:
        elect_by_cohort = defaultdict(list)
        for c in components:
            if c.course.ctype == "S":
                elect_by_cohort[(c.course.level, c.course.semester)].append(
                    tt.comp_vars[c.cid].interval)
        for cohort, ivs in elect_by_cohort.items():
            if len(ivs) > config.max_parallel_electives:
                m.add_cumulative(ivs, [1] * len(ivs), config.max_parallel_electives)

    # Every course of a pinned cohort must avoid that cohort's fixed common sessions
    # (pairwise, so legitimately-parallel electives of the cohort are not broken).
    # EXCEPTION: a course in the SAME pick-1 elective group as the fixed session
    # (config.fixed_session_groups) may overlap it — students take one or the other.
    for cohort, pins in cohort_pins.items():
        cohort_comps = [c for c in components
                        if (c.course.level, c.course.semester) == cohort]
        for c in cohort_comps:
            cg = config.groups.get(c.course.name)
            civ = tt.comp_vars[c.cid].interval
            for piv, _day, pg in pins:
                if pg is not None and cg and cg[0] == pg:
                    continue
                m.add_no_overlap([civ, piv])

    # Per-cohort used-weekday bools + HARD free-day guarantee (always enforced).
    tt.cohort_used, tt.cohort_day_meta = cohort_used_days(tt, components, config)
    if config.require_free_day:
        for cohort, any_ons in tt.cohort_used.items():
            if len(any_ons) == 5:
                m.add(sum(any_ons) <= 4)  # >=1 completely free day for this cohort

    # Per-instructor used-weekday bools (for the concentration objective).
    tt.instructor_used = instructor_used_days(tt, components, fixed)

    return tt


def cohort_used_days(tt, components, config):
    """For every cohort, return (used, day_meta).

    used[cohort][d] (any_on) is True iff ANY of the cohort's courses — mandatory or
    ANY elective a student could pick — is on weekday d. It is computed over ALL
    members (not deduped) so that a day free for every student regardless of picks is
    truly empty, and so the free-day objective rewards parallelising electives (which
    keeps them on one day). The within-day compactness meta (starts/ends/busy) is
    computed over the STUDENT's representative load only (one per pick-block) so that
    parallel courses are not double-counted (which would make busy exceed the day span).
    """
    m = tt.model
    by_cohort = defaultdict(list)
    for c in components:
        by_cohort[(c.course.level, c.course.semester)].append(c)
    used = {}
    day_meta = {}
    NP = tg.NUM_PERIODS
    for (lvl, sem), comps in by_cohort.items():
        all_cvs = [tt.comp_vars[c.cid] for c in comps]
        load_cvs = [tt.comp_vars[c.cid] for c in _student_load(comps, config)]
        used[(lvl, sem)] = []
        day_meta[(lvl, sem)] = []
        pin_days = set(getattr(tt, "cohort_pin_days", {}).get((lvl, sem), []))
        for di in range(5):
            # any_on over ALL members -> free-day guarantee + reward for parallel.
            # A fixed common session pinned to this cohort makes its day used
            # unconditionally (students must attend it).
            on_all = []
            for cv in all_cvs:
                onb = m.new_bool_var(f"onA_{lvl}{sem}_{cv.comp.cid}_{di}")
                m.add(cv.d == di).only_enforce_if(onb)
                m.add(cv.d != di).only_enforce_if(onb.Not())
                on_all.append(onb)
            any_on = m.new_bool_var(f"any_{lvl}{sem}_{di}")
            if di in pin_days:
                m.add(any_on == 1)
            else:
                m.add_max_equality(any_on, on_all)
            used[(lvl, sem)].append(any_on)
            # compactness meta over the representative student load
            starts, ends, busy_terms, load_on = [], [], [], []
            for cv in load_cvs:
                L = cv.comp.length
                onb = m.new_bool_var(f"onL_{lvl}{sem}_{cv.comp.cid}_{di}")
                m.add(cv.d == di).only_enforce_if(onb)
                m.add(cv.d != di).only_enforce_if(onb.Not())
                s_on = m.new_int_var(0, NP, f"son_{lvl}{sem}_{cv.comp.cid}_{di}")
                m.add(s_on == cv.p).only_enforce_if(onb)
                m.add(s_on == NP).only_enforce_if(onb.Not())
                e_on = m.new_int_var(0, NP, f"eon_{lvl}{sem}_{cv.comp.cid}_{di}")
                m.add(e_on == cv.p + L).only_enforce_if(onb)
                m.add(e_on == 0).only_enforce_if(onb.Not())
                bz = m.new_int_var(0, L, f"bz_{lvl}{sem}_{cv.comp.cid}_{di}")
                m.add(bz == L).only_enforce_if(onb)
                m.add(bz == 0).only_enforce_if(onb.Not())
                starts.append(s_on)
                ends.append(e_on)
                busy_terms.append(bz)
                load_on.append(onb)
            load_any = m.new_bool_var(f"anyL_{lvl}{sem}_{di}")
            if load_on:
                m.add_max_equality(load_any, load_on)
            else:
                m.add(load_any == 0)
            day_meta[(lvl, sem)].append((starts, ends, busy_terms, load_any))
    return used, day_meta


def add_objective(tt, components, config):
    """PRIMARY objective: maximize each cohort's empty days (minimize used weekdays),
    guaranteeing >=1 completely free day per cohort (hard, if require_free_day).
    Secondary: minimize within-day student idle gaps, avoid P1, minimize Amfi use.
    """
    m = tt.model
    w = config.weights
    NP = tg.NUM_PERIODS
    terms = []

    used, day_meta = tt.cohort_used, tt.cohort_day_meta

    for cohort, any_ons in used.items():
        lvl, sem = cohort
        # PRIMARY: each used weekday is penalized -> maximizes empty days.
        # SOFT cohort day preference: a NON-preferred used day costs extra, so the
        # solver shifts the cohort onto its preferred days when otherwise costless.
        pref = config.cohort_day_pref.get(f"{lvl}-{sem}")
        pref_idx = {tg.day_index(x) for x in pref} if pref else None
        for di, any_on in enumerate(any_ons):
            terms.append(w.get("free_day", 0) * any_on)
            if pref_idx is not None and di not in pref_idx:
                terms.append(w.get("cohort_day_pref", 0) * any_on)
        # SECONDARY: within-day compactness (idle-gap) per used day
        for di, (starts, ends, busy_terms, any_on) in enumerate(day_meta[cohort]):
            first = m.new_int_var(0, NP, f"first_{lvl}{sem}_{di}")
            last = m.new_int_var(0, NP, f"last_{lvl}{sem}_{di}")
            m.add_min_equality(first, starts)
            m.add_max_equality(last, ends)
            busy = m.new_int_var(0, NP, f"busy_{lvl}{sem}_{di}")
            m.add(busy == sum(busy_terms))
            # raw span-minus-busy may be NEGATIVE when load courses legitimately
            # overlap (e.g. grad courses with no disjointness constraint); the gap
            # penalty is max(0, raw) so overlap is never hard-forbidden by the
            # objective machinery.
            raw = m.new_int_var(-NP, NP, f"rawgap_{lvl}{sem}_{di}")
            m.add(raw == last - first - busy).only_enforce_if(any_on)
            m.add(raw == 0).only_enforce_if(any_on.Not())
            gap = m.new_int_var(0, NP, f"gap_{lvl}{sem}_{di}")
            m.add_max_equality(gap, [raw, 0])
            terms.append(w.get("student_gap", 0) * gap)

    # PRIMARY (equal to free_day): concentrate each instructor onto as few days as possible.
    for instr, any_ons in tt.instructor_used.items():
        for any_on in any_ons:
            terms.append(w.get("instructor_day", 0) * any_on)

    # Strong P1-avoidance for every department course (all levels); yields only if forced.
    for cv in tt.comp_vars.values():
        at_p1 = m.new_bool_var(f"p1_{cv.comp.cid}")
        m.add(cv.p == 0).only_enforce_if(at_p1)
        m.add(cv.p != 0).only_enforce_if(at_p1.Not())
        terms.append(w.get("avoid_first", 0) * at_p1)

    # Monday late start (ulaşım): dept courses preferably start 10:20+ (P3) on
    # Monday — soft penalty for a Monday P2 (09:25) start; fixed commons unaffected.
    mls = w.get("monday_late_start", 0)
    if mls:
        for cv in tt.comp_vars.values():
            is_mon = m.new_bool_var(f"ismon_{cv.comp.cid}")
            m.add(cv.d == 0).only_enforce_if(is_mon)
            m.add(cv.d != 0).only_enforce_if(is_mon.Not())
            is_p2 = m.new_bool_var(f"isp2_{cv.comp.cid}")
            m.add(cv.p == 1).only_enforce_if(is_p2)
            m.add(cv.p != 1).only_enforce_if(is_p2.Not())
            mon_early = m.new_bool_var(f"mon2_{cv.comp.cid}")
            m.add_bool_and([is_mon, is_p2]).only_enforce_if(mon_early)
            m.add_bool_or([is_mon.Not(), is_p2.Not()]).only_enforce_if(mon_early.Not())
            terms.append(mls * mon_early)

    # SOFT room priority, PER LEVEL: rooms earlier in the level's priority list are
    # cheaper; a booking in a lower-priority (or unlisted) room pays rank * room_pref.
    # Grad borrowing a Lisans classroom (D-724/D-733) ranks below Lisansüstü Sınıfı
    # but above TUSAŞ Lab; Lisans keeps its own D-731-first order. Pure tiebreak —
    # weight stays far below every scheduling objective, so it only steers room CHOICE.
    rp = w.get("room_pref", 0)
    if rp and config.room_priority:
        for cv in tt.comp_vars.values():
            level = cv.comp.course.level
            if isinstance(config.room_priority, dict):
                # per-level keys ("yl"/"dr") override the shared "grad" list
                if level == "YL":
                    prio = config.room_priority.get("yl") or config.room_priority.get("grad", [])
                elif level == "DR":
                    prio = config.room_priority.get("dr") or config.room_priority.get("grad", [])
                else:
                    prio = config.room_priority.get("lisans", [])
            else:
                prio = config.room_priority
            rank = {r: i for i, r in enumerate(prio)}
            worst = len(prio)
            for r, lit in cv.room_lits.items():
                terms.append(rp * rank.get(r, worst) * lit)

    # Slot-sharing is NOT a goal in itself: a SMALL penalty per shared slot breaks
    # ties toward keeping electives separate (maximum student choice). Any real
    # gain elsewhere (a free day 1000, day-pref 300, even a gap 10) dwarfs it, so
    # the solver still pairs whenever pairing actually buys something or is needed
    # for feasibility.
    pp = w.get("pair_penalty", 0)
    if pp:
        for same in getattr(tt, "group_same_lits", []):
            terms.append(pp * same)

    if terms:
        m.minimize(sum(terms))
