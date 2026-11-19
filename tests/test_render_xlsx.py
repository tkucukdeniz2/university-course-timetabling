import openpyxl

from src.solve import ScheduledBlock
from src.config import load_config
from src.render_xlsx import render


def test_render_produces_expected_sheets(tmp_path):
    cfg = load_config("config.yaml")
    blocks = [
        ScheduledBlock("Systems Simulation", "ENMU4065", "Lisans", 7, "T", 2, 0, 6, "D-731", "Hoca B", "", False),
        ScheduledBlock("İş Zekası", "", "YL", 1, "T", 3, 1, 8, "TUSAŞ Lab", "Hoca C", "", False),
    ]
    out = tmp_path / "timetable.xlsx"
    render(blocks, [], cfg, str(out))
    wb = openpyxl.load_workbook(out)
    for s in ["Lisans-7", "YL", "By-Instructor", "By-Room", "External-Dependencies"]:
        assert s in wb.sheetnames
    ws = wb["Lisans-7"]
    assert any(cell.value and "Systems Simulation" in str(cell.value)
               for row in ws.iter_rows() for cell in row)


def test_rich_text_highlights_amfi_and_preserves_order():
    from src.render_xlsx import _rich
    from openpyxl.cell.rich_text import CellRichText
    v = _rich("Ders X\nHoca Y\nAmfi\nSEÇMELİ (F)", "Amfi")
    assert isinstance(v, CellRichText)
    assert str(v) == "Ders X\nHoca Y\nAmfi\nSEÇMELİ (F)"   # nothing lost or reordered
    assert _rich("no highlight here", "Amfi") == "no highlight here"


def test_render_amfi_cell_is_rich(tmp_path):
    import openpyxl
    from openpyxl.cell.rich_text import CellRichText
    cfg = load_config("config.yaml")
    blocks = [ScheduledBlock("Quality Engineering", "", "Lisans", 5, "TU", 4, 0, 2,
                             "Amfi", "Hoca B", "", False)]
    out = tmp_path / "t.xlsx"
    render(blocks, [], cfg, str(out))
    wb = openpyxl.load_workbook(out, rich_text=True)
    ws = wb["Lisans-5"]
    assert any(isinstance(c.value, CellRichText) for row in ws.iter_rows() for c in row)


def test_mandatory_course_name_rendered_bold(tmp_path):
    import openpyxl
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    cfg = load_config("config.yaml")
    blocks = [ScheduledBlock("Zorunlu Ders", "", "Lisans", 7, "T", 2, 0, 2,
                             "D-731", "H", "", False, mandatory=True)]
    out = tmp_path / "b.xlsx"
    render(blocks, [], cfg, str(out))
    wb = openpyxl.load_workbook(out, rich_text=True)
    ws = wb["Lisans-7"]
    found = False
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, CellRichText):
                for part in c.value:
                    if isinstance(part, TextBlock) and part.text == "Zorunlu Ders" and part.font.b:
                        found = True
    assert found


def test_room_and_instructor_sheets(tmp_path):
    import openpyxl, copy
    cfg = copy.deepcopy(load_config("config.yaml"))
    cfg.instructor_sheets = ["Öğr. Üyesi 15"]
    blocks = [
        ScheduledBlock("Systems Simulation", "", "Lisans", 7, "TU", 4, 3, 2,
                       "D-724 / End.Müh. Bilg. Lab.", "Öğr. Üyesi 15", "", False, True),
        ScheduledBlock("Quality Engineering", "", "Lisans", 5, "TU", 4, 0, 2,
                       "Amfi", "Öğr. Üyesi 15", "", False, True),
    ]
    out = tmp_path / "r.xlsx"
    render(blocks, [], cfg, str(out))
    wb = openpyxl.load_workbook(out)
    # dual-room block appears on BOTH room sheets
    for sheet in ["D-724", "End.Müh. Bilg. Lab.", "Amfi", "Öğr. Üyesi 15"]:
        assert sheet in wb.sheetnames, f"missing sheet {sheet}"
        ws = wb[sheet]
        assert any(c.value for row in ws.iter_rows(min_row=2, min_col=2) for c in row)
    # instructor sheet has both her courses
    ws = wb["Öğr. Üyesi 15"]
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "Systems Simulation" in text and "Quality Engineering" in text


def test_no_empty_rpr_in_workbook(tmp_path):
    """Excel 'repairs' empty <rPr/> as corrupt string properties — never emit one."""
    import zipfile, copy
    cfg = copy.deepcopy(load_config("config.yaml"))
    cfg.instructor_sheets = ["Öğr. Üyesi 15"]
    blocks = [
        # mixed bold + amfi + plain pieces exercise every rich-text path
        ScheduledBlock("Quality Engineering", "", "Lisans", 5, "TU", 4, 0, 2,
                       "Amfi", "Öğr. Üyesi 15", "", False, True),
        ScheduledBlock("Systems Simulation", "", "Lisans", 7, "TU", 4, 1, 2,
                       "D-724 / End.Müh. Bilg. Lab.", "Öğr. Üyesi 15", "", False, True),
        ScheduledBlock("Lean Production", "", "Lisans", 5, "T", 3, 2, 2,
                       "D-731", "Hoca D", "D", False, False),
    ]
    out = tmp_path / "v.xlsx"
    render(blocks, [], cfg, str(out))
    z = zipfile.ZipFile(out)
    for n in z.namelist():
        if n.startswith("xl/worksheets/"):
            content = z.read(n).decode("utf-8")
            assert "<rPr/>" not in content, f"empty rPr in {n}"
            # no bare <t> mixed with <r> runs inside one inline string
            import re
            for m in re.finditer(r"<is>(.*?)</is>", content, re.DOTALL):
                body = m.group(1)
                if "<r>" in body:
                    assert not re.match(r"\s*<t[ >]", body), f"mixed t+r in {n}"


def test_watermark_injected_as_sheet_background(tmp_path):
    import zipfile, copy
    cfg = copy.deepcopy(load_config("config.yaml"))
    cfg.watermark = "TASLAK"
    cfg.instructor_sheets = []
    blocks = [ScheduledBlock("Ders", "", "Lisans", 7, "T", 2, 0, 2, "D-731", "H", "", False)]
    out = tmp_path / "w.xlsx"
    render(blocks, [], cfg, str(out))
    z = zipfile.ZipFile(out)
    assert "xl/media/watermark1.png" in z.namelist()
    assert b'Extension="png"' in z.read("[Content_Types].xml")
    # the Lisans-7 grid sheet carries a <picture> background; list sheets don't
    found = any(b"<picture " in z.read(n) for n in z.namelist()
                if n.startswith("xl/worksheets/sheet"))
    assert found
    # file still opens cleanly
    import openpyxl
    wb = openpyxl.load_workbook(out)
    assert "Lisans-7" in wb.sheetnames


def test_hidden_instructor_absent_from_all_output(tmp_path):
    # görevlendirmesi yapılmamış hoca: hiçbir sheet'te / listede ismi görünmez
    cfg = load_config("config.yaml")
    assert "Öğr. Üyesi 26" in cfg.hide_instructors
    blocks = [
        ScheduledBlock("Elektronik Ticaret ve Pazarlama", "", "Lisans", 5, "T", 3,
                       0, 1, "D-724", "Öğr. Üyesi 26", "D", False),
        ScheduledBlock("İş Zekası", "", "YL", 1, "T", 3, 1, 8, "TUSAŞ Lab",
                       "Öğr. Üyesi 10", "", False),
    ]
    out = tmp_path / "t.xlsx"
    render(blocks, [], cfg, str(out))
    wb = openpyxl.load_workbook(out, rich_text=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value:
                    assert "Öğr. Üyesi 26" not in str(c.value), (ws.title, c.coordinate)
    # görünür hoca etkilenmez
    ws = wb["YL"]
    assert any(c.value and "Öğr. Üyesi 10" in str(c.value)
               for row in ws.iter_rows() for c in row)
