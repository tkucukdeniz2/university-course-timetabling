import csv

from src import timegrid as tg


def write_csv(blocks, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["course", "code", "level", "semester", "kind", "length",
                    "day", "period", "room", "instructor", "group", "en_medium"])
        for b in sorted(blocks, key=lambda x: (x.level, x.semester, x.day, x.period)):
            w.writerow([b.course_name, b.code, b.level, b.semester, b.kind, b.length,
                        tg.DAYS[b.day], tg.PERIODS[b.period][0], b.room, b.instructor,
                        b.group, int(b.en_medium)])
