import re

DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma"]
NUM_PERIODS = 13
LAST_DAYTIME_INDEX = 10  # P1..P11 -> index 0..10

PERIODS = [
    ("P1", "08.30", "09.20"), ("P2", "09.25", "10.15"), ("P3", "10.20", "11.10"),
    ("P4", "11.15", "12.05"), ("P5", "12.10", "13.00"), ("P6", "13.05", "13.55"),
    ("P7", "14.00", "14.50"), ("P8", "14.55", "15.45"), ("P9", "15.50", "16.40"),
    ("P10", "16.45", "17.35"), ("P11", "17.40", "18.30"), ("P12", "18.40", "19.30"),
    ("P13", "19.35", "20.25"),
]
_DAY_IDX = {d: i for i, d in enumerate(DAYS)}
_START_ALIASES = {"18.35": 11}  # Avcılar uses 18.35 for P12


def day_index(name: str) -> int:
    return _DAY_IDX[name.strip()]


def flat(day: int, period: int) -> int:
    return day * NUM_PERIODS + period


def start_label_to_index(s: str):
    if not s:
        return None
    head = re.split(r"[-–—]", s.strip())[0]
    head = re.sub(r"\s+", "", head).replace(":", ".")
    for i, (_, st, _e) in enumerate(PERIODS):
        if head.startswith(st):
            return i
    return _START_ALIASES.get(head)
