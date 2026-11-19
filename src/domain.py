from dataclasses import dataclass


@dataclass
class Course:
    row_id: int
    term: str
    level: str          # "Lisans" | "YL" | "DR"
    semester: int
    code: str | None
    name: str
    instructor: str
    T: int
    U: int
    L: int
    ctype: str          # "Z" | "S"
    dept_faculty: bool  # True = IE faculty, False = external/service

    @property
    def key(self):
        return (self.level, self.semester, self.name)


@dataclass
class Component:
    cid: str
    course: Course
    kind: str           # "T" | "U" | "L"
    length: int
    needs_lab: bool
    instructor: str | None = None  # per-component override (e.g. an assistant runs the U hours)

    @property
    def eff_instructor(self):
        return self.instructor or self.course.instructor


@dataclass
class FixedSession:
    course_name: str
    instructor: str | None
    day: int
    period: int
    length: int
    room: str


@dataclass
class BlockedInterval:
    room: str
    day: int
    period: int
    length: int
    label: str


def generate_components(courses, lab_courses, split_tu=frozenset(), uygulama_assistants=None,
                        single_block=frozenset()):
    """One block per course for theory+application (T+U kept together, never split);
    lab hours (L) form a separate block in the computer lab. Zero-hour courses and
    '**'-marked rows (fixed sem-1 common) are excluded.

    Exceptions:
    - if a course's instructor OR name is in ``split_tu``, its T and U are emitted as
      SEPARATE blocks (they may then land on different days);
    - if a course name is in ``uygulama_assistants``, it is force-split and its U block
      is assigned to the named assistant instead of the course's main instructor;
    - if a course name is in ``single_block``, ALL its hours (T+U+L) form ONE
      contiguous block (in the lab when it has lab hours).
    """
    uygulama_assistants = uygulama_assistants or {}
    comps = []
    for c in courses:
        if c.name.strip().endswith("**"):
            continue
        if (c.T + c.U + c.L) == 0:
            continue
        if c.name in single_block:
            total = c.T + c.U + c.L
            comps.append(Component(f"{c.row_id}:ALL", c, "TUL", total, c.L > 0))
            continue
        split = (c.instructor in split_tu or c.name in split_tu or c.name in uygulama_assistants)
        if split:
            for kind, ln in (("T", c.T), ("U", c.U)):
                if ln > 0:
                    instr = uygulama_assistants.get(c.name) if kind == "U" else None
                    comps.append(Component(f"{c.row_id}:{kind}", c, kind, ln, False, instructor=instr))
        else:
            tu = c.T + c.U
            if tu > 0:
                kind = "TU" if (c.T > 0 and c.U > 0) else ("T" if c.T > 0 else "U")
                comps.append(Component(f"{c.row_id}:TU", c, kind, tu, False))
        if c.L > 0:
            comps.append(Component(f"{c.row_id}:L", c, "L", c.L, True))
    return comps
