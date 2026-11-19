import csv

from src.main import main


def test_end_to_end_produces_valid_workbook(tmp_path):
    out = tmp_path / "timetable.xlsx"
    csvp = tmp_path / "schedule.csv"
    rc = main([
        "--course-xlsx", "data/courses.xlsx",
        "--avcilar-xlsx", "data/faculty_rooms.xlsx",
        "--config", "config.yaml", "--availability", "availability.yaml",
        "--out", str(out), "--csv", str(csvp), "--time-limit", "60",
    ])
    assert rc == 0                      # 0 => feasible AND checker found no violations
    assert out.exists() and csvp.exists()
    with open(csvp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 40              # one row per scheduled block (T+U merged, Seminer/excluded dropped)


def test_next_version_scans_existing(tmp_path):
    from src.main import next_version
    assert next_version(str(tmp_path)) == 1
    (tmp_path / "timetable_v3.xlsx").write_bytes(b"x")
    (tmp_path / "timetable_v10.xlsx").write_bytes(b"x")
    (tmp_path / "timetable kopyası 7.xlsx").write_bytes(b"x")  # informal copies ignored
    assert next_version(str(tmp_path)) == 11
