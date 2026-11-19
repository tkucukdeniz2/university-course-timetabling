import io
import os
import re
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import replace

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

from src import timegrid as tg

_WRAP = Alignment(wrap_text=True, vertical="center", horizontal="center")
_HEAD = Font(bold=True)
_AMFI_FONT = InlineFont(color="FFC00000", b=True)  # dark red, bold — highlights the amfi name
_BOLD = InlineFont(b=True)                          # bold — zorunlu (Z) course names


def _rich_parts(text, amfi_name):
    """Split text into str / TextBlock parts, coloring the amfi room name."""
    if not amfi_name or amfi_name not in text:
        return [text] if text else []
    parts = []
    for i, seg in enumerate(text.split(amfi_name)):
        if i > 0:
            parts.append(TextBlock(_AMFI_FONT, amfi_name))
        if seg:
            parts.append(seg)
    return parts


def _rich(text, amfi_name="Amfi"):
    """Cell value with every occurrence of the amfi room name dark-red bold."""
    parts = _rich_parts(text, amfi_name)
    if all(isinstance(p, str) for p in parts):
        return text
    return CellRichText(parts)


def _compose(pieces, amfi_name):
    """Build a cell value from (name, rest, bold) pieces: bold mandatory course
    names, amfi highlighting in the rest; plain string when no styling is needed.
    Plain str parts stay as str — openpyxl serializes them as runs WITHOUT rPr,
    which is the schema-valid form. Never emit an empty <rPr/> (Excel 'repairs'
    those as corrupt string properties)."""
    parts = []
    for i, (name, rest, bold) in enumerate(pieces):
        if i > 0:
            parts.append(" || ")
        if bold:
            parts.append(TextBlock(_BOLD, name))
        else:
            parts.extend(_rich_parts(name, amfi_name))
        if rest:
            parts.extend(_rich_parts("\n" + rest, amfi_name))
    if all(isinstance(p, str) for p in parts):
        return "".join(parts)
    return CellRichText(parts)


_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _watermark_png(text):
    """A tileable, diagonal, light-gray watermark image (PNG bytes)."""
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            font = ImageFont.truetype(p, 64)
            break
    if font is None:
        font = ImageFont.load_default()
    tile = Image.new("RGBA", (520, 380), (255, 255, 255, 0))
    txt = Image.new("RGBA", (420, 110), (255, 255, 255, 0))
    ImageDraw.Draw(txt).text((10, 10), text, font=font, fill=(190, 190, 190, 90))
    txt = txt.rotate(30, expand=True)
    tile.alpha_composite(txt, (30, 60))
    # white base (Excel tiles the image as the sheet background)
    base = Image.new("RGB", tile.size, (255, 255, 255))
    base.paste(tile, mask=tile.split()[3])
    buf = io.BytesIO()
    base.save(buf, format="PNG")
    return buf.getvalue()


_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _apply_watermark(path, sheet_titles, text):
    """Inject the watermark image as the sheet BACKGROUND of the given sheets
    (Excel's Page Layout > Background) via careful xlsx surgery."""
    png = _watermark_png(text)
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    # sheet title -> worksheet part name (attribute order varies: parse per tag)
    wb_xml = parts["xl/workbook.xml"].decode("utf-8")
    rels_xml = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    rid_to_target = {}
    for tag in re.findall(r"<Relationship\b[^>]*/>", rels_xml):
        mid = re.search(r'Id="([^"]+)"', tag)
        mtg = re.search(r'Target="([^"]+)"', tag)
        if mid and mtg:
            rid_to_target[mid.group(1)] = mtg.group(1)
    title_to_part = {}
    for tag in re.findall(r"<sheet\b[^>]*/>", wb_xml):
        mname = re.search(r'name="([^"]+)"', tag)
        mrid = re.search(r'r:id="([^"]+)"', tag)
        if not (mname and mrid):
            continue
        target = rid_to_target.get(mrid.group(1), "")
        if target.startswith("/"):
            part = target.lstrip("/")          # absolute target: /xl/worksheets/sheetN.xml
        else:
            part = "xl/" + target              # relative to xl/
        title_to_part[mname.group(1)] = part
    parts["xl/media/watermark1.png"] = png
    ct = parts["[Content_Types].xml"].decode("utf-8")
    if 'Extension="png"' not in ct:
        ct = ct.replace("</Types>",
                        '<Default Extension="png" ContentType="image/png"/></Types>')
        parts["[Content_Types].xml"] = ct.encode("utf-8")
    for title in sheet_titles:
        part = title_to_part.get(title)
        if not part or part not in parts:
            continue
        sheet_file = part.rsplit("/", 1)[-1]
        rels_name = f"xl/worksheets/_rels/{sheet_file}.rels"
        if rels_name in parts:
            rx = parts[rels_name].decode("utf-8")
            new_id = f"rIdWm{len(re.findall('<Relationship ', rx)) + 1}"
            rx = rx.replace("</Relationships>",
                            f'<Relationship Id="{new_id}" Type="{_REL_NS}/image" '
                            f'Target="../media/watermark1.png"/></Relationships>')
        else:
            new_id = "rIdWm1"
            rx = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                  f'<Relationship Id="{new_id}" Type="{_REL_NS}/image" '
                  f'Target="../media/watermark1.png"/></Relationships>')
        parts[rels_name] = rx.encode("utf-8")
        sx = parts[part].decode("utf-8")
        # CT_Worksheet: <picture> is one of the LAST elements — append before </worksheet>
        sx = sx.replace("</worksheet>",
                        f'<picture xmlns:r="{_REL_NS}" r:id="{new_id}"/></worksheet>')
        parts[part] = sx.encode("utf-8")
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(os.path.abspath(path)) or ".")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, data in parts.items():
            zout.writestr(n, data)
    os.replace(tmp, path)


def _cell_rest(b):
    parts = [b.instructor, b.room]
    if b.group:
        parts.append(f"SEÇMELİ ({b.group})")
    return "\n".join(p for p in parts if p)


def _cell_rest_room(b):
    """Cell detail for a ROOM sheet: instructor + cohort (room is the sheet itself)."""
    parts = [b.instructor, f"{b.level}-{b.semester}"]
    if b.group:
        parts.append(f"SEÇMELİ ({b.group})")
    return "\n".join(p for p in parts if p)


def _cell_rest_instructor(b):
    """Cell detail for an INSTRUCTOR sheet: room + cohort (hoca is the sheet itself)."""
    parts = [b.room, f"{b.level}-{b.semester}"]
    if b.group:
        parts.append(f"SEÇMELİ ({b.group})")
    return "\n".join(p for p in parts if p)


def _block_rooms(b):
    """Rooms a block occupies (dual-room blocks list both)."""
    return [p.strip() for p in b.room.split(" / ")]


def _grid_sheet(wb, title, blocks, fixed=None, amfi_name="Amfi", rest_fn=None):
    ws = wb.create_sheet(title)
    ws.cell(1, 1, "Saat").font = _HEAD
    for di, day in enumerate(tg.DAYS):
        c = ws.cell(1, 2 + di, day)
        c.font = _HEAD
        c.alignment = _WRAP
    for pi, (lbl, st, en) in enumerate(tg.PERIODS):
        ws.cell(2 + pi, 1, f"{lbl}  {st}-{en}").font = _HEAD

    cells = defaultdict(list)  # (row, col) -> list of (name, rest, bold) pieces

    def place(day, period, length, name, rest, bold):
        for k in range(length):
            cells[(2 + period + k, 2 + day)].append((name, rest, bold))

    rest = rest_fn or _cell_rest
    for fx in (fixed or []):
        # fixed commons are mandatory for their cohort -> bold as well
        place(fx.day, fx.period, fx.length, fx.course_name, fx.room, True)
    for b in blocks:
        place(b.day, b.period, b.length, b.course_name, rest(b),
              getattr(b, "mandatory", False))
    for (r, col), pieces in cells.items():
        cell = ws.cell(r, col)
        cell.value = _compose(pieces, amfi_name)
        cell.alignment = _WRAP
    for di in range(len(tg.DAYS)):
        ws.column_dimensions[chr(66 + di)].width = 26
    return ws


def _list_sheet(wb, title, headers, rows):
    ws = wb.create_sheet(title)
    for ci, h in enumerate(headers, 1):
        ws.cell(1, ci, h).font = _HEAD
    for ri, row in enumerate(rows, 2):
        for ci, v in enumerate(row, 1):
            ws.cell(ri, ci, v)
    return ws


def render(blocks, fixed, config, out_path):
    # instructors whose görevlendirme is still pending stay in the MODEL (their
    # clash constraints hold) but their name is blanked in EVERY rendered output
    hide = getattr(config, "hide_instructors", set())
    if hide:
        blocks = [replace(b, instructor="") if b.instructor in hide else b
                  for b in blocks]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    watermark = getattr(config, "watermark", "")
    grid_titles = []

    def grid(title, *args, **kwargs):
        ws = _grid_sheet(wb, title, *args, **kwargs)
        grid_titles.append(ws.title)
        if watermark:
            # print-layout watermark (large light-gray text in the page header)
            ws.oddHeader.center.text = f"&KC8C8C8&44{watermark}"
        return ws

    # one sheet per cohort present in the schedule (term-agnostic: GÜZ 1/3/5/7,
    # BAHAR 2/4/6/8, grad any semester); each cohort's fixed common sessions are
    # drawn on ITS sheet (cohort mapping mirrors the model's pin_cohort).
    from src.model import pin_cohort
    fixed_by_cohort = defaultdict(list)
    for fx in (fixed or []):
        fixed_by_cohort[pin_cohort(fx, config)].append(fx)
    order = {"Lisans": 0, "YL": 1, "DR": 2}
    cohort_keys = sorted({(b.level, b.semester) for b in blocks} | set(fixed_by_cohort),
                         key=lambda t: (order.get(t[0], 9), t[1]))
    for lvl, sem in cohort_keys:
        title = f"Lisans-{sem}" if lvl == "Lisans" else lvl
        cohort_blocks = [b for b in blocks if b.level == lvl and b.semester == sem]
        grid(title, cohort_blocks, fixed_by_cohort.get((lvl, sem)),
             amfi_name=config.amfi_room)

    # one weekly grid per room (dual-room blocks appear on BOTH rooms' sheets)
    all_rooms = []
    for pool in config.room_pools.values():
        all_rooms += pool
    all_rooms += [config.lab_room, config.amfi_room]
    for v in getattr(config, "amfi_assignments", {}).values():
        all_rooms += list(v) if isinstance(v, list) else [v]
    seen = set()
    for room in all_rooms:
        if room in seen:
            continue
        seen.add(room)
        room_blocks = [b for b in blocks if room in _block_rooms(b)]
        room_fixed = [fx for fx in (fixed or []) if fx.room == room]
        if room_blocks or room_fixed:
            grid(room, room_blocks, room_fixed,
                 amfi_name=config.amfi_room, rest_fn=_cell_rest_room)

    # one weekly grid per department instructor (from config.instructor_sheets),
    # alphabetically ordered with Turkish collation
    _TR = "AaBbCcÇçDdEeFfGgĞğHhIıİiJjKkLlMmNnOoÖöPpQqRrSsŞşTtUuÜüVvWwXxYyZz"
    _TR_KEY = {ch: i for i, ch in enumerate(_TR)}

    def tr_key(s):
        return [_TR_KEY.get(ch, 100 + ord(ch)) for ch in s]

    for name in sorted(getattr(config, "instructor_sheets", []), key=tr_key):
        i_blocks = [b for b in blocks if b.instructor == name]
        i_fixed = [fx for fx in (fixed or []) if fx.instructor == name]
        if i_blocks or i_fixed:
            grid(name[:31], i_blocks, i_fixed,
                 amfi_name=config.amfi_room, rest_fn=_cell_rest_instructor)

    def fmt(b):
        lbl = tg.PERIODS[b.period][0]
        return f"{tg.DAYS[b.day]} {lbl}(+{b.length})"

    def fmt_fx(fx):
        lbl = tg.PERIODS[fx.period][0]
        return f"{tg.DAYS[fx.day]} {lbl}(+{fx.length})"

    # By-Instructor includes the fixed common sessions of dept instructors (e.g. the
    # pinned programming lab), so each hoca sees their COMPLETE week.
    instr_rows = [[b.instructor, fmt(b), b.course_name, b.room, b.level] for b in blocks]
    instr_rows += [[fx.instructor, fmt_fx(fx), fx.course_name.split("(")[0].strip(),
                    fx.room, "Sabit"] for fx in (fixed or []) if fx.instructor]
    instr_rows.sort(key=lambda r: (r[0], r[1]))
    _list_sheet(wb, "By-Instructor", ["Instructor", "When", "Course", "Room", "Level"], instr_rows)
    by_room = sorted(blocks, key=lambda b: (b.room, b.day, b.period))
    _list_sheet(wb, "By-Room", ["Room", "When", "Course", "Instructor", "Level"],
                [[b.room, fmt(b), b.course_name, b.instructor, b.level] for b in by_room])
    amfi = [b for b in blocks if b.course_name in config.amfi_courses]
    _list_sheet(wb, "External-Dependencies", ["Item", "Course", "When", "Note"],
                [["Amfi", b.course_name, fmt(b),
                  f"Tahsis: {b.room}" if b.room != config.amfi_room else "Büyük amfi talep edilecek"]
                 for b in amfi]
                + [["Fixed common", fx.course_name.split("(")[0].strip(),
                    fmt_fx(fx), fx.room] for fx in (fixed or [])])
    # atomic save: write to a temp file then replace, so a reader (e.g. Excel
    # opening mid-solve) can never see a partially-written workbook
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(os.path.abspath(out_path)) or ".")
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    if watermark and grid_titles:
        _apply_watermark(out_path, grid_titles, watermark)
    return wb
