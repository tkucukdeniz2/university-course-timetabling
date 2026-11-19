import re
import warnings
from collections import defaultdict

import openpyxl

from src.domain import Course, FixedSession, BlockedInterval
from src import timegrid as tg


def canonicalize_instructor(name):
    return re.sub(r"\s+", " ", (name or "").strip())


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def load_courses(xlsx_path, term="GÜZ"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Sayfa1"]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    out = []
    for rid, r in enumerate(rows[1:], start=1):
        if all(c is None for c in r):
            continue

        def cell(col):
            return r[idx[col]] if col in idx and idx[col] < len(r) else None

        if str(cell("DÖNEM") or "").strip().upper() != term.upper():
            continue
        name = str(cell("DersAd") or "").strip()
        if not name:
            continue
        out.append(Course(
            row_id=rid, term=term,
            level=str(cell("Kategori") or "").strip(),
            semester=_to_int(cell("Yarıyıl")),
            code=(str(cell("DersKodu")).strip() if cell("DersKodu") else None),
            name=name,
            instructor=canonicalize_instructor(cell("DersiVeren")),
            T=_to_int(cell("T")), U=_to_int(cell("U")), L=_to_int(cell("L")),
            ctype=str(cell("Zorunlu/Seçmeli") or "S").strip(),
            dept_faculty=(_to_int(cell("Bölüm?")) == 1),
        ))
    return out


def apply_instructor_overrides(courses, overrides):
    """Reassign a course's instructor (e.g. a newly hired hoca). Keyed by course name or code."""
    for c in courses:
        if c.name in overrides:
            c.instructor = canonicalize_instructor(overrides[c.name])
        elif c.code and c.code in overrides:
            c.instructor = canonicalize_instructor(overrides[c.code])
    return courses


def _norm_cell(v):
    return re.sub(r"\s+", " ", str(v).replace("\n", " ").strip()) if v is not None else ""


_ROOM_NAME_MAP = {"D721": "D-721", "D724": "D-724", "D731": "D-731", "D733": "D-733"}


def _canon_room(r):
    return _ROOM_NAME_MAP.get(r.replace(" ", ""), r)


def _tr_fold(s):
    """Turkish-aware case fold (İ->i, I->ı, then lower)."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def _match_instructor(cell_text, known_instructors):
    """Return the known instructor whose full name appears in the cell text
    (Turkish-case-insensitively), or None."""
    folded = _tr_fold(cell_text)
    for name in known_instructors or []:
        if _tr_fold(name) in folded:
            return name
    return None


def _runs(periods):
    """Split a sorted period list into maximal consecutive runs."""
    runs, cur = [], [periods[0]]
    for p in periods[1:]:
        if p == cur[-1] + 1:
            cur.append(p)
        else:
            runs.append(cur)
            cur = [p]
    runs.append(cur)
    return runs


def load_fixed_and_blocked(avcilar_path, our_rooms, dept_regex="End[uü]stri",
                           known_instructors=None, sheet_name="Derslik Programı Güz"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(avcilar_path, data_only=True)
    ws = wb[sheet_name]
    # locate room-block header rows (col B == PAZARTESİ)
    header_rows = []
    for row in ws.iter_rows(values_only=False):
        for c in row:
            if c.value and str(c.value).strip().upper().startswith("PAZARTES"):
                header_rows.append(c.row)
                break
    header_rows = sorted(set(header_rows)) + [ws.max_row + 1]
    dept = re.compile(dept_regex, re.IGNORECASE)
    raw = []  # (room, day, period, text)
    for i in range(len(header_rows) - 1):
        hr, nxt = header_rows[i], header_rows[i + 1]
        room = _canon_room(_norm_cell(ws.cell(hr, 1).value))
        for rr in range(hr + 1, nxt):
            label = _norm_cell(ws.cell(rr, 1).value)
            pidx = tg.start_label_to_index(label)
            if pidx is None:
                day_cells = [_norm_cell(ws.cell(rr, dcol).value) for dcol in range(2, 7)]
                if label and any(day_cells):
                    print(f"UYARI: '{room}' satırındaki saat etiketi çözümlenemedi, "
                          f"satır atlandı: '{label}'")
                continue
            for dcol in range(2, 7):
                txt = _norm_cell(ws.cell(rr, dcol).value)
                if txt:
                    raw.append((room, dcol - 2, pidx, txt))
    groups = defaultdict(list)
    for room, day, pidx, txt in raw:
        groups[(room, day, txt)].append(pidx)
    fixed, blocked = [], []
    for (room, day, txt), periods in groups.items():
        # a course may occupy two separate runs on one day (e.g. morning + afternoon):
        # split into maximal consecutive runs instead of assuming contiguity
        for run in _runs(sorted(periods)):
            p0, ln = run[0], len(run)
            if dept.search(txt):
                instr = _match_instructor(txt, known_instructors)
                fixed.append(FixedSession(txt, instr, day, p0, ln, room))
            elif room in our_rooms and not re.search(r"20\d\d.*Oturum", txt):
                blocked.append(BlockedInterval(room, day, p0, ln, txt))
    return fixed, blocked
