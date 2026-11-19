import os
from dataclasses import dataclass

from ortools.sat.python import cp_model

from src import model as M


@dataclass
class ScheduledBlock:
    course_name: str
    code: str
    level: str
    semester: int
    kind: str
    length: int
    day: int
    period: int
    room: str
    instructor: str
    group: str
    en_medium: bool
    mandatory: bool = False  # Z (zorunlu) course -> name rendered bold in the Excel


@dataclass
class SolveResult:
    status: str
    blocks: list
    objective: float
    feasible: bool


def solve(components, fixed, blocked, config, availability, time_limit=60, optimize=True, workers=None):
    tt = M.build_hard(components, fixed, blocked, config, availability)
    if optimize:
        M.add_objective(tt, components, config)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.random_seed = 42
    # Use all CPU cores to search for the best schedule. NOTE: multi-worker portfolio
    # search under a wall-clock limit is NOT run-to-run deterministic even with a fixed
    # seed; pass workers=1 when exact reproducibility matters more than speed.
    solver.parameters.num_search_workers = workers or max(1, os.cpu_count() or 8)
    status = solver.solve(tt.model)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    blocks = []
    if feasible:
        for cv in tt.comp_vars.values():
            c = cv.comp
            room = next(r for r, lit in cv.room_lits.items() if solver.value(lit))
            if c.course.name in config.dual_room_courses and not c.needs_lab:
                room = f"{room} / {config.lab_room}"   # classroom + reserved lab
            # elective groups are a Lisans concept; a grad course sharing a name
            # with a Lisans elective (e.g. Deney Tasarımı) must not inherit its label
            g = config.groups.get(c.course.name) if c.course.level == "Lisans" else None
            blocks.append(ScheduledBlock(
                course_name=c.course.name, code=c.course.code or "", level=c.course.level,
                semester=c.course.semester, kind=c.kind, length=c.length,
                day=solver.value(cv.d), period=solver.value(cv.p), room=room,
                instructor=c.eff_instructor, group=(g[0] if g else ""),
                en_medium=c.course.name in config.en_medium,
                mandatory=(c.course.ctype == "Z"),
            ))
    obj = solver.objective_value if (feasible and optimize) else None
    return SolveResult(solver.status_name(status), blocks, obj, feasible)
