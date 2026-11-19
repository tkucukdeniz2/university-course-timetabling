from dataclasses import dataclass, field

import yaml

from src import timegrid as tg
from src.data_loader import canonicalize_instructor


@dataclass
class Config:
    room_pools: dict
    lab_room: str
    lab_courses: set
    groups: dict
    weights: dict
    unlock_evening: bool
    en_medium: set
    require_free_day: bool = True
    forbid_first_period: bool = True
    excluded_courses: set = field(default_factory=set)
    cohort_days: dict = field(default_factory=dict)  # "Level-Sem" -> [allowed Turkish day names]
    latest_period: int = 11  # last 1-based period a dept course may occupy (P11=17:40 by default)
    split_tu: set = field(default_factory=set)  # instructors/courses whose T and U schedule separately
    instructor_overrides: dict = field(default_factory=dict)  # course name -> new instructor
    uygulama_assistants: dict = field(default_factory=dict)  # course name -> assistant who runs the U hours
    fixed_placements: list = field(default_factory=list)  # pin a component to an exact day/start period
    amfi_room: str = "Amfi"  # large amphitheater (requested from faculty) for high-enrollment courses
    amfi_courses: set = field(default_factory=set)  # courses too big for regular rooms -> Amfi only
    lab_only_courses: set = field(default_factory=set)  # courses taught ENTIRELY in the computer lab
    dual_room_courses: set = field(default_factory=set)  # need a classroom AND the lab at the same slot
    same_day_courses: list = field(default_factory=list)  # lists of courses that must share one day
    different_day_courses: set = field(default_factory=set)  # split courses whose parts must be on DIFFERENT days
    course_rooms: dict = field(default_factory=dict)  # course name -> required room list (hard)
    watermark: str = ""  # e.g. "TASLAK" — sheet-background + print-header watermark
    course_days: dict = field(default_factory=dict)  # course name -> allowed weekday names
    cohort_day_pref: dict = field(default_factory=dict)  # "Level-Sem" -> PREFERRED weekdays (soft)
    instructor_sheets: list = field(default_factory=list)  # instructors who get their own Excel sheet
    ctype_overrides: dict = field(default_factory=dict)  # course name -> "Z" | "S" (fix wrong master data)
    room_priority: list = field(default_factory=list)  # preferred room order; unlisted rooms come last
    blocked_slots: list = field(default_factory=list)  # campus-wide forbidden slots, e.g. Friday prayer
    single_block_courses: set = field(default_factory=set)  # ALL hours (T+U+L) as ONE contiguous block
    max_parallel_electives: int = 2  # max same-cohort electives running simultaneously (0 = unlimited)
    fixed_session_cohorts: dict = field(default_factory=dict)  # pin-text substring -> "Level-Sem" (default Lisans-1)
    allow_first_courses: set = field(default_factory=set)  # courses exempt from the P1 (08:30) ban
    amfi_assignments: dict = field(default_factory=dict)  # amfi course (or "course:KIND") -> granted room
    hide_instructors: set = field(default_factory=set)  # names hidden in ALL outputs (assignment pending)
    default_pin_cohort: str = "Lisans-1"  # cohort of fixed commons not matched by fixed_session_cohorts
    course_windows: dict = field(default_factory=dict)  # course -> {min: first start P, max: last occupied P} (1-based)
    room_windows: dict = field(default_factory=dict)  # room -> AVAILABLE windows [{day, periods}]; rest is blocked
    fixed_session_groups: dict = field(default_factory=dict)  # pin-text substring -> elective group letter

    def is_excluded(self, course):
        return course.name in self.excluded_courses or (
            course.code and course.code in self.excluded_courses)

    def eligible_rooms(self, component):
        if component.needs_lab:
            return [self.lab_room]
        if component.course.name in self.lab_only_courses:
            # course taught entirely in the computer lab (e.g. hands-on optimization)
            return [self.lab_room]
        if component.course.name in self.amfi_courses:
            # high-enrollment: the GRANTED faculty room — per-component ("Ders:U")
            # entry wins over the per-course entry; else the request-only placeholder
            room = (self.amfi_assignments.get(f"{component.course.name}:{component.kind}")
                    or self.amfi_assignments.get(component.course.name, self.amfi_room))
            return list(room) if isinstance(room, list) else [room]
        if component.course.name in self.dual_room_courses:
            # needs a CLASSROOM here; the lab is reserved additionally by the model
            pool = "grad" if component.course.level in ("YL", "DR") else "lisans"
            return list(self.room_pools[pool])
        if component.course.level in ("YL", "DR"):
            # grad: 2 dedicated classrooms + the computer lab (all grad courses may use it)
            return list(self.room_pools["grad"]) + [self.lab_room]
        # Lisans classrooms; suitable (bilgisayar) courses may ALSO use the lab
        rooms = list(self.room_pools["lisans"])
        if component.course.name in self.lab_courses:
            rooms = rooms + [self.lab_room]
        # per-course room requirement (e.g. high enrollment -> the big D-731)
        req = self.course_rooms.get(component.course.name)
        if req:
            rooms = [r for r in rooms if r in req]
            if not rooms:
                raise ValueError(
                    f"course_rooms for {component.course.name!r} leaves no eligible room "
                    f"(required {req})")
        return rooms


@dataclass
class Availability:
    blocked: dict = field(default_factory=dict)

    def is_blocked(self, instructor, day, period):
        return (day, period) in self.blocked.get(instructor, set())


def load_config(path):
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    return Config(
        room_pools=d["room_pools"],
        lab_room=d["lab_room"],
        lab_courses=set(d.get("lab_courses", [])),
        groups={k: (v[0], int(v[1])) for k, v in d.get("groups", {}).items()},
        weights=d.get("weights", {}),
        unlock_evening=bool(d.get("unlock_evening", False)),
        en_medium=set(d.get("en_medium", [])),
        require_free_day=bool(d.get("require_free_day", True)),
        forbid_first_period=bool(d.get("forbid_first_period", True)),
        excluded_courses=set(d.get("excluded_courses", [])),
        cohort_days=d.get("cohort_days", {}) or {},
        latest_period=int(d.get("latest_period", 11)),
        split_tu=set(d.get("split_tu", [])),
        instructor_overrides=d.get("instructor_overrides", {}) or {},
        uygulama_assistants={k: canonicalize_instructor(v)
                             for k, v in (d.get("uygulama_assistants", {}) or {}).items()},
        fixed_placements=d.get("fixed_placements", []) or [],
        amfi_room=d.get("amfi_room", "Amfi"),
        amfi_courses=set(d.get("amfi_courses", [])),
        lab_only_courses=set(d.get("lab_only_courses", [])),
        dual_room_courses=set(d.get("dual_room_courses", [])),
        same_day_courses=d.get("same_day_courses", []) or [],
        different_day_courses=set(d.get("different_day_courses", [])),
        course_rooms=d.get("course_rooms", {}) or {},
        watermark=d.get("watermark", "") or "",
        course_days=d.get("course_days", {}) or {},
        cohort_day_pref=d.get("cohort_day_pref", {}) or {},
        instructor_sheets=[canonicalize_instructor(x) for x in d.get("instructor_sheets", []) or []],
        ctype_overrides=d.get("ctype_overrides", {}) or {},
        room_priority=d.get("room_priority", []) or [],
        blocked_slots=d.get("blocked_slots", []) or [],
        single_block_courses=set(d.get("single_block_courses", [])),
        max_parallel_electives=int(d.get("max_parallel_electives", 2)),
        fixed_session_cohorts=d.get("fixed_session_cohorts", {}) or {},
        allow_first_courses=set(d.get("allow_first_courses", [])),
        amfi_assignments=d.get("amfi_assignments", {}) or {},
        hide_instructors=set(d.get("hide_instructors", [])),
        default_pin_cohort=d.get("default_pin_cohort", "Lisans-1"),
        course_windows=d.get("course_windows", {}) or {},
        room_windows=d.get("room_windows", {}) or {},
        fixed_session_groups=d.get("fixed_session_groups", {}) or {},
    )


def load_availability(path, known_instructors=None):
    """Load per-instructor blocked windows. Keys are canonicalized; if
    known_instructors is given, keys matching no known instructor raise a
    ValueError instead of silently dropping a HARD constraint."""
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    blocked = {}
    unknown = []
    for instr, windows in (d.get("blocks") or {}).items():
        name = canonicalize_instructor(instr)
        if known_instructors is not None and name not in known_instructors:
            if windows:  # a real constraint on an unknown name is a dangerous typo
                unknown.append(instr)
            continue  # empty entry for an absent instructor (e.g. excluded) is harmless
        s = set()
        for w in windows or []:
            di = tg.day_index(w["day"])
            for p in w["periods"]:
                s.add((di, p - 1))
        blocked[name] = s
    if unknown:
        raise ValueError(
            f"availability.yaml keys match no known instructor (typo?): {unknown}")
    return Availability(blocked)
