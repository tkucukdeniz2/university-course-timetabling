import copy

from ortools.sat.python import cp_model

from src.domain import Course, generate_components
from src.config import load_config, Availability
from src import model as M


def _cfg():
    """Real config, minus production entries that reference real courses absent from
    these synthetic instances (they would trip the unmatched-entry validations)."""
    cfg = copy.deepcopy(load_config("config.yaml"))
    cfg.fixed_placements = []
    cfg.same_day_courses = []
    return cfg


def _solve(components, fixed=None, blocked=None):
    cfg = _cfg()
    tt = M.build_hard(components, fixed or [], blocked or [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.random_seed = 42
    s.parameters.num_search_workers = 1
    return s, s.solve(tt.model), tt


def _flat(s, cv):
    return s.value(cv.d) * 13 + s.value(cv.p)


def test_same_instructor_two_courses_do_not_overlap():
    c1 = Course(1, "GÜZ", "YL", 1, None, "A", "HOCA", 3, 0, 0, "S", True)
    c2 = Course(2, "GÜZ", "YL", 1, None, "B", "HOCA", 3, 0, 0, "S", True)
    comps = generate_components([c1, c2], set())
    s, status, tt = _solve(comps)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    cvs = list(tt.comp_vars.values())
    a = set(range(_flat(s, cvs[0]), _flat(s, cvs[0]) + cvs[0].comp.length))
    b = set(range(_flat(s, cvs[1]), _flat(s, cvs[1]) + cvs[1].comp.length))
    assert a.isdisjoint(b)


def test_cohort_mandatory_disjoint():
    c1 = Course(1, "GÜZ", "Lisans", 3, None, "Z1", "H1", 3, 0, 0, "Z", True)
    c2 = Course(2, "GÜZ", "Lisans", 3, None, "Z2", "H2", 3, 0, 0, "Z", True)
    s, status, tt = _solve(generate_components([c1, c2], set()))
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    a, b = list(tt.comp_vars.values())
    sa = set(range(_flat(s, a), _flat(s, a) + 3))
    sb = set(range(_flat(s, b), _flat(s, b) + 3))
    assert sa.isdisjoint(sb)


def test_adjacent_split_blocks_share_room():
    # back-to-back T and U blocks of one course form a contiguous run -> same room
    c = Course(1, "GÜZ", "Lisans", 5, None, "SplitCourse", "HOCA", 3, 2, 0, "Z", True)
    comps = generate_components([c], set(), split_tu={"HOCA"})
    assert len(comps) == 2
    cfg = _cfg()
    cfg.fixed_placements = [
        {"course": "SplitCourse", "kind": "T", "day": "Pazartesi", "period": 2},
        {"course": "SplitCourse", "kind": "U", "day": "Pazartesi", "period": 5},
    ]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.random_seed = 42
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    rooms = [next(r for r, l in cv.room_lits.items() if s.value(l)) for cv in tt.comp_vars.values()]
    assert len(set(rooms)) == 1


def test_non_adjacent_split_blocks_may_use_different_rooms():
    # blocks on different days (or separated in time) are NOT tied to one room:
    # forcing two different rooms must stay feasible
    c = Course(1, "GÜZ", "Lisans", 5, None, "SplitCourse", "HOCA", 3, 2, 0, "Z", True)
    comps = generate_components([c], set(), split_tu={"HOCA"})
    cfg = _cfg()
    cfg.fixed_placements = [
        {"course": "SplitCourse", "kind": "T", "day": "Pazartesi", "period": 2},
        {"course": "SplitCourse", "kind": "U", "day": "Salı", "period": 2},
    ]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    u, v = tt.comp_vars.values()
    r1, r2 = sorted(set(u.room_lits) & set(v.room_lits))[:2]
    tt.model.add(u.room_lits[r1] == 1)
    tt.model.add(v.room_lits[r2] == 1)
    s = cp_model.CpSolver()
    s.parameters.random_seed = 42
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_adjacent_split_blocks_different_rooms_infeasible():
    # the converse: adjacency + forced different rooms must be INFEASIBLE
    c = Course(1, "GÜZ", "Lisans", 5, None, "SplitCourse", "HOCA", 3, 2, 0, "Z", True)
    comps = generate_components([c], set(), split_tu={"HOCA"})
    cfg = _cfg()
    cfg.fixed_placements = [
        {"course": "SplitCourse", "kind": "T", "day": "Pazartesi", "period": 2},
        {"course": "SplitCourse", "kind": "U", "day": "Pazartesi", "period": 5},
    ]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    u, v = tt.comp_vars.values()
    r1, r2 = sorted(set(u.room_lits) & set(v.room_lits))[:2]
    tt.model.add(u.room_lits[r1] == 1)
    tt.model.add(v.room_lits[r2] == 1)
    s = cp_model.CpSolver()
    s.parameters.random_seed = 42
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) == cp_model.INFEASIBLE


def test_objective_prefers_compact_day():
    c1 = Course(1, "GÜZ", "Lisans", 3, None, "Z1", "H1", 1, 0, 0, "Z", True)
    c2 = Course(2, "GÜZ", "Lisans", 3, None, "Z2", "H2", 1, 0, 0, "Z", True)
    comps = generate_components([c1, c2], set())
    cfg = _cfg()
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.random_seed = 42
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    a, b = list(tt.comp_vars.values())
    fa, fb = _flat(s, a), _flat(s, b)
    # optimum: same day, adjacent -> zero student gap AND single campus-day
    assert s.value(a.d) == s.value(b.d) and abs(fa - fb) == 1


def test_cross_group_electives_disjoint():
    # sem-7 student takes from F AND G -> an F elective may never overlap a G elective
    f1 = Course(1, "GÜZ", "Lisans", 7, None, "Sezgisel Optimizasyon", "H1", 3, 0, 0, "S", True)
    g1 = Course(2, "GÜZ", "Lisans", 7, None, "Endüstri 4.0 ve Dijital Dönüşüm", "H2", 3, 0, 0, "S", True)
    comps = generate_components([f1, g1], set())
    s, status, tt = _solve(comps)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    a, b = list(tt.comp_vars.values())
    sa = set(range(_flat(s, a), _flat(s, a) + 3))
    sb = set(range(_flat(s, b), _flat(s, b) + 3))
    assert sa.isdisjoint(sb)


def test_same_group_pickk_share_slot_exactly_or_disjoint():
    # dynamic pairing: any two pick-k group courses either share EXACTLY the same
    # slot or are fully disjoint — partial overlap is impossible
    d1 = Course(1, "GÜZ", "Lisans", 5, None, "Lean Production", "H1", 3, 0, 0, "S", True)
    d2 = Course(2, "GÜZ", "Lisans", 5, None, "Technology and R&D Management", "H2", 3, 0, 0, "S", True)
    comps = generate_components([d1, d2], set())
    s, status, tt = _solve(comps)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    a, b = list(tt.comp_vars.values())
    sa = set(range(_flat(s, a), _flat(s, a) + 3))
    sb = set(range(_flat(s, b), _flat(s, b) + 3))
    assert sa == sb or sa.isdisjoint(sb)


def test_same_group_partial_overlap_infeasible():
    # forcing a 1-period offset between two same-group courses must be INFEASIBLE
    d1 = Course(1, "GÜZ", "Lisans", 5, None, "Lean Production", "H1", 3, 0, 0, "S", True)
    d2 = Course(2, "GÜZ", "Lisans", 5, None, "Technology and R&D Management", "H2", 3, 0, 0, "S", True)
    comps = generate_components([d1, d2], set())
    cfg = _cfg()
    cfg.fixed_placements = [
        {"course": "Lean Production", "day": "Pazartesi", "period": 2},
        {"course": "Technology and R&D Management", "day": "Pazartesi", "period": 3},
    ]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) == cp_model.INFEASIBLE


def test_same_group_exact_share_feasible_and_capped():
    # exact same slot for two D courses is allowed (different rooms); but pairing
    # more than n-k pairs is not: with 4 courses pick-3 only ONE pair may share
    cs = [Course(i, "GÜZ", "Lisans", 5, None, name, f"H{i}", 3, 0, 0, "S", True)
          for i, name in enumerate(["Lean Production", "Technology and R&D Management",
                                    "İşletme Finansı", "Veri Madenciliği ve Bilgi Keşfi"], 1)]
    comps = generate_components(cs, set())
    cfg = _cfg()
    cfg.course_days = {}
    # force two pairs to share slots: (1,2)@Mon P2 and (3,4)@Tue P2 -> 2 same-pairs > n-k=1 -> INFEASIBLE
    cfg.fixed_placements = [
        {"course": "Lean Production", "day": "Pazartesi", "period": 2},
        {"course": "Technology and R&D Management", "day": "Pazartesi", "period": 2},
        {"course": "İşletme Finansı", "day": "Salı", "period": 2},
        {"course": "Veri Madenciliği ve Bilgi Keşfi", "day": "Salı", "period": 2},
    ]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) == cp_model.INFEASIBLE
    # a single shared pair is fine
    cfg2 = _cfg()
    cfg2.fixed_placements = [
        {"course": "Lean Production", "day": "Pazartesi", "period": 2},
        {"course": "Technology and R&D Management", "day": "Pazartesi", "period": 2},
    ]
    comps2 = generate_components(cs, set())
    tt2 = M.build_hard(comps2, [], [], cfg2, Availability({}))
    s2 = cp_model.CpSolver()
    s2.parameters.num_search_workers = 1
    assert s2.solve(tt2.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_availability_window_enforced():
    from src.config import load_config, Availability
    c = Course(1, "GÜZ", "YL", 1, None, "X", "HOCA", 3, 0, 0, "S", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    # block HOCA everywhere except Cuma P2-P4
    blocked = {(d, p) for d in range(5) for p in range(13) if not (d == 4 and 1 <= p <= 3)}
    tt = M.build_hard(comps, [], [], cfg, Availability({"HOCA": blocked}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    cv = list(tt.comp_vars.values())[0]
    assert s.value(cv.d) == 4 and s.value(cv.p) == 1


def test_fixed_placement_unmatched_raises():
    import copy
    from src.config import load_config, Availability
    import pytest
    c = Course(1, "GÜZ", "YL", 1, None, "X", "HOCA", 3, 0, 0, "S", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.fixed_placements = [{"course": "Nonexistent Course", "day": "Salı", "period": 2}]
    with pytest.raises(ValueError, match="matched no"):
        M.build_hard(comps, [], [], cfg, Availability({}))


def test_grad_overlap_not_forbidden_by_objective():
    # two YL courses (different instructors, no student-conflict rule) pinned to the
    # same slot must stay FEASIBLE even with the objective added (gap = max(0, ...))
    import copy
    from src.config import load_config, Availability
    c1 = Course(1, "GÜZ", "YL", 1, None, "A", "H1", 3, 0, 0, "S", True)
    c2 = Course(2, "GÜZ", "YL", 1, None, "B", "H2", 3, 0, 0, "S", True)
    comps = generate_components([c1, c2], set())
    cfg = _cfg()
    cfg.fixed_placements = [
        {"course": "A", "day": "Pazartesi", "period": 2},
        {"course": "B", "day": "Pazartesi", "period": 2},
    ]
    cfg.max_parallel_electives = 0  # not testing the cap here
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_fixed_pins_count_toward_cohort_free_days():
    # a sem-1 pin on Monday makes Monday a used day for Lisans-1: with require_free_day
    # and pins on 4 days, the dept course must land on a pin day (Thursday stays free)
    from src.config import load_config, Availability
    from src.domain import FixedSession
    import copy
    c = Course(1, "GÜZ", "Lisans", 1, None, "Endüstri Mühendisliğine Giriş", "H", 2, 0, 0, "Z", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    pins = [FixedSession(f"Common {d}", None, d, 1, 3, "K-B03") for d in (0, 1, 2, 4)]
    tt = M.build_hard(comps, pins, [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    cv = list(tt.comp_vars.values())[0]
    assert s.value(cv.d) in (0, 1, 2, 4)  # NOT Thursday — that is the free day


def test_pinned_cohort_course_cannot_overlap_pin():
    # a Lisans-1 course forced onto a pin's slot (different room) must be INFEASIBLE;
    # the same overlap for a non-pinned cohort (Lisans-3) is fine
    from src.domain import FixedSession
    pin = FixedSession("Ortak Zorunlu Ders", None, 0, 1, 3, "K-B03")  # Mon P2-P4

    def build(level, sem):
        c = Course(1, "GÜZ", level, sem, None, "X", "H", 3, 0, 0, "Z", True)
        comps = generate_components([c], set())
        cfg = _cfg()
        cfg.fixed_placements = [{"course": "X", "day": "Pazartesi", "period": 2}]
        tt = M.build_hard(comps, [pin], [], cfg, Availability({}))
        s = cp_model.CpSolver()
        s.parameters.num_search_workers = 1
        return s.solve(tt.model)

    assert build("Lisans", 1) == cp_model.INFEASIBLE
    assert build("Lisans", 3) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_fixed_session_cohorts_override_redirects_enforcement():
    # mapping the pin to Lisans-3 inverts the roles: sem-3 blocked, sem-1 free
    from src.domain import FixedSession
    pin = FixedSession("Ortak Zorunlu Ders", None, 0, 1, 3, "K-B03")

    def build(level, sem):
        c = Course(1, "GÜZ", level, sem, None, "X", "H", 3, 0, 0, "Z", True)
        comps = generate_components([c], set())
        cfg = _cfg()
        cfg.fixed_session_cohorts = {"Ortak Zorunlu": "Lisans-3"}
        cfg.fixed_placements = [{"course": "X", "day": "Pazartesi", "period": 2}]
        tt = M.build_hard(comps, [pin], [], cfg, Availability({}))
        s = cp_model.CpSolver()
        s.parameters.num_search_workers = 1
        return s.solve(tt.model)

    assert build("Lisans", 3) == cp_model.INFEASIBLE
    assert build("Lisans", 1) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_dual_room_course_reserves_lab_too():
    # a dual-room course and a lab-only course cannot share a slot (lab conflict),
    # even though the dual course sits in a classroom
    def build(same_slot):
        dual = Course(1, "GÜZ", "Lisans", 7, None, "Systems Simulation", "H1", 2, 2, 0, "Z", True)
        lab = Course(2, "GÜZ", "Lisans", 7, None, "Sezgisel Optimizasyon", "H2", 3, 0, 0, "S", True)
        comps = generate_components([dual, lab], set())
        cfg = _cfg()
        cfg.fixed_placements = [
            {"course": "Systems Simulation", "day": "Pazartesi", "period": 2},
            {"course": "Sezgisel Optimizasyon", "day": "Pazartesi" if same_slot else "Salı", "period": 2},
        ]
        tt = M.build_hard(comps, [], [], cfg, Availability({}))
        s = cp_model.CpSolver()
        s.parameters.num_search_workers = 1
        return s.solve(tt.model)

    assert build(same_slot=True) == cp_model.INFEASIBLE   # both need the lab Mon P2+
    assert build(same_slot=False) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_same_day_courses_share_a_day():
    a = Course(1, "GÜZ", "Lisans", 7, None, "ZA", "H1", 2, 2, 0, "Z", True)
    b = Course(2, "GÜZ", "Lisans", 7, None, "ZB", "H2", 2, 2, 0, "Z", True)
    comps = generate_components([a, b], set())
    cfg = _cfg()
    cfg.same_day_courses = [["ZA", "ZB"]]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    days = {s.value(cv.d) for cv in tt.comp_vars.values()}
    assert len(days) == 1


def test_same_day_unmatched_raises():
    import pytest
    a = Course(1, "GÜZ", "Lisans", 7, None, "ZA", "H1", 3, 0, 0, "Z", True)
    comps = generate_components([a], set())
    cfg = _cfg()
    cfg.same_day_courses = [["ZA", "Yok Böyle Ders"]]
    with pytest.raises(ValueError, match="fewer than 2"):
        M.build_hard(comps, [], [], cfg, Availability({}))


def test_course_days_restricts_weekday():
    c = Course(1, "GÜZ", "YL", 1, None, "GünlüDers", "H", 3, 0, 0, "S", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.course_days = {"GünlüDers": ["Salı"]}
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert s.value(list(tt.comp_vars.values())[0].d) == 1  # Salı


def test_cohort_day_pref_steers_but_does_not_force():
    # soft preference: an unconstrained cohort course lands on a preferred day...
    c = Course(1, "GÜZ", "Lisans", 5, None, "Tercihli", "H", 3, 0, 0, "Z", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.cohort_day_pref = {"Lisans-5": ["Pazartesi"]}
    cfg.weights = dict(cfg.weights, cohort_day_pref=300)
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert s.value(list(tt.comp_vars.values())[0].d) == 0  # Pazartesi
    # ...but an availability block overrides it (soft, not hard)
    blocked = {(0, p) for p in range(13)}  # Monday fully blocked
    tt2 = M.build_hard(comps, [], [], cfg, Availability({"H": blocked}))
    M.add_objective(tt2, comps, cfg)
    s2 = cp_model.CpSolver()
    s2.parameters.num_search_workers = 1
    assert s2.solve(tt2.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert s2.value(list(tt2.comp_vars.values())[0].d) != 0


def test_room_priority_steers_choice():
    # a single unconstrained Lisans course must land in the top-priority room
    c = Course(1, "GÜZ", "Lisans", 7, None, "OdaTesti", "H", 3, 0, 0, "S", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.room_priority = ["D-733"]  # deliberately not the pool's first room
    cfg.weights = dict(cfg.weights, room_pref=2)
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    cv = list(tt.comp_vars.values())[0]
    room = next(r for r, l in cv.room_lits.items() if s.value(l))
    assert room == "D-733"


def test_blocked_slots_keep_friday_prayer_free():
    # a 4h course must not cover Cuma P6 (13:05-13:55)
    c = Course(1, "GÜZ", "Lisans", 7, None, "UzunDers", "H", 4, 0, 0, "Z", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.course_days = {"UzunDers": ["Cuma"]}   # force Friday
    cfg.blocked_slots = [{"day": "Cuma", "periods": [6]}]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    cv = list(tt.comp_vars.values())[0]
    p = s.value(cv.p)
    covered = set(range(p, p + 4))
    assert 5 not in covered   # P6 (0-based 5) untouched


def test_pairing_not_preferred_when_costless_to_separate():
    # two same-group courses with NO pressure to pair must stay separate
    # (pair_penalty tiebreak), even though sharing a slot is allowed
    d1 = Course(1, "GÜZ", "Lisans", 5, None, "Lean Production", "H1", 3, 0, 0, "S", True)
    d2 = Course(2, "GÜZ", "Lisans", 5, None, "Technology and R&D Management", "H2", 3, 0, 0, "S", True)
    comps = generate_components([d1, d2], set())
    cfg = _cfg()
    cfg.cohort_day_pref = {}
    cfg.weights = dict(cfg.weights, pair_penalty=5)
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    a, b = list(tt.comp_vars.values())
    assert (s.value(a.d), s.value(a.p)) != (s.value(b.d), s.value(b.p))


def test_different_day_courses_split_across_days():
    c = Course(1, "GÜZ", "Lisans", 5, None, "BölünenDers", "H", 2, 2, 0, "Z", True)
    comps = generate_components([c], set(), split_tu={"H"})
    assert len(comps) == 2
    cfg = _cfg()
    cfg.different_day_courses = {"BölünenDers"}
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    a, b = list(tt.comp_vars.values())
    assert s.value(a.d) != s.value(b.d)


def test_different_day_requires_split_components():
    import pytest
    c = Course(1, "GÜZ", "Lisans", 5, None, "TekBlok", "H", 2, 2, 0, "Z", True)
    comps = generate_components([c], set())  # merged TU -> single component
    cfg = _cfg()
    cfg.different_day_courses = {"TekBlok"}
    with pytest.raises(ValueError, match="only one"):
        M.build_hard(comps, [], [], cfg, Availability({}))


def test_grad_room_priority_lisansustu_first():
    # a single unconstrained YL course must land in Lisansüstü Sınıfı (grad top priority)
    c = Course(1, "GÜZ", "YL", 1, None, "GradDers", "H", 3, 0, 0, "S", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.weights = dict(cfg.weights, room_pref=2)
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    cv = list(tt.comp_vars.values())[0]
    room = next(r for r, l in cv.room_lits.items() if s.value(l))
    assert room == "Lisansüstü Sınıfı"


def test_grad_may_borrow_d_rooms_when_lisansustu_busy():
    # two YL courses pinned to the same slot: one gets Lisansüstü, the other must
    # borrow D-724 (next grad priority), not TUSAŞ
    c1 = Course(1, "GÜZ", "YL", 1, None, "GradA", "H1", 3, 0, 0, "S", True)
    c2 = Course(2, "GÜZ", "YL", 1, None, "GradB", "H2", 3, 0, 0, "S", True)
    comps = generate_components([c1, c2], set())
    cfg = _cfg()
    cfg.weights = dict(cfg.weights, room_pref=2)
    cfg.max_parallel_electives = 0
    cfg.fixed_placements = [
        {"course": "GradA", "day": "Pazartesi", "period": 2},
        {"course": "GradB", "day": "Pazartesi", "period": 2},
    ]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    rooms = {next(r for r, l in cv.room_lits.items() if s.value(l))
             for cv in tt.comp_vars.values()}
    assert rooms == {"Lisansüstü Sınıfı", "D-724"}


def test_monday_prefers_late_start():
    # a Monday-only course with no other pressure starts at P3 (10:20), not P2
    c = Course(1, "GÜZ", "Lisans", 7, None, "PztDersi", "H", 3, 0, 0, "S", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.course_days = {"PztDersi": ["Pazartesi"]}
    cfg.weights = dict(cfg.weights, monday_late_start=150)
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    M.add_objective(tt, comps, cfg)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    cv = list(tt.comp_vars.values())[0]
    assert s.value(cv.p) >= 2   # P3+


def test_allow_first_courses_exempts_p1_ban():
    # exempt course may start at P1 (08:30); others still cannot
    c = Course(1, "GÜZ", "Lisans", 3, None, "ErkenDers", "H", 3, 0, 0, "Z", True)
    comps = generate_components([c], set())
    cfg = _cfg()
    cfg.allow_first_courses = {"ErkenDers"}
    cfg.fixed_placements = [{"course": "ErkenDers", "day": "Salı", "period": 1}]
    tt = M.build_hard(comps, [], [], cfg, Availability({}))
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    assert s.solve(tt.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert s.value(list(tt.comp_vars.values())[0].p) == 0  # P1
    # without the exemption the same pin must raise (outside legal window)
    import pytest
    cfg2 = _cfg()
    cfg2.fixed_placements = [{"course": "ErkenDers", "day": "Salı", "period": 1}]
    comps2 = generate_components([c], set())
    with pytest.raises(ValueError, match="outside the legal window"):
        M.build_hard(comps2, [], [], cfg2, Availability({}))
