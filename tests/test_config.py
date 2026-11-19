from src.config import load_config, load_availability
from src.domain import Course, Component


def test_config_defaults():
    cfg = load_config("config.yaml")
    assert cfg.groups["Sezgisel Optimizasyon"] == ("F", 3)
    assert cfg.weights["student_gap"] == 10
    assert cfg.lab_room == "End.Müh. Bilg. Lab."
    assert cfg.unlock_evening is False


def test_eligible_rooms():
    cfg = load_config("config.yaml")
    lis = Course(1, "GÜZ", "Lisans", 5, None, "Lean Production", "H", 3, 0, 0, "S", True)
    yl = Course(2, "GÜZ", "YL", 1, None, "İş Zekası", "H", 3, 0, 0, "S", True)
    assert cfg.eligible_rooms(Component("x", lis, "T", 3, False))[0].startswith("D-")
    amfi = Course(3, "GÜZ", "Lisans", 5, None, "Quality Engineering", "H", 2, 2, 0, "Z", True)
    # amfi course goes to its GRANTED faculty room (K-B01), not the generic Amfi
    assert cfg.eligible_rooms(Component("a", amfi, "TU", 4, False)) == ["K-B01"]
    grad_rooms = cfg.eligible_rooms(Component("y", yl, "T", 3, False))
    # grad pool: Lisansüstü + borrowable D-724/D-733 + TUSAŞ (+ lab appended)
    assert grad_rooms[0] == "Lisansüstü Sınıfı" and "TUSAŞ Lab" in grad_rooms
    assert "D-724" in grad_rooms and "D-733" in grad_rooms
    assert cfg.eligible_rooms(Component("z", lis, "L", 2, True)) == ["End.Müh. Bilg. Lab."]


def test_availability_blocked():
    av = load_availability("availability.yaml")
    assert av.is_blocked("Anyone", 0, 0) is False


def test_grad_rooms_include_lab():
    cfg = load_config("config.yaml")
    yl = Course(9, "GÜZ", "YL", 1, None, "Herhangi", "H", 3, 0, 0, "S", True)
    rooms = cfg.eligible_rooms(Component("g", yl, "T", 3, False))
    assert cfg.lab_room in rooms


def test_availability_loads_and_converts_windows(tmp_path):
    p = tmp_path / "av.yaml"
    p.write_text(
        'blocks:\n  "Test  Hoca":\n    - {day: "Cuma", periods: [1, 2]}\n',
        encoding="utf-8")
    av = load_availability(str(p))
    # key canonicalized (double space collapsed); day/period converted to 0-based
    assert av.is_blocked("Test Hoca", 4, 0) and av.is_blocked("Test Hoca", 4, 1)
    assert not av.is_blocked("Test Hoca", 4, 2)


def test_availability_unknown_key_raises(tmp_path):
    import pytest
    p = tmp_path / "av.yaml"
    p.write_text('blocks:\n  "Yok Boyle Hoca":\n    - {day: "Cuma", periods: [1]}\n',
                 encoding="utf-8")
    with pytest.raises(ValueError, match="no known instructor"):
        load_availability(str(p), known_instructors={"Gerçek Hoca"})


def test_lab_only_course_gets_only_the_lab():
    cfg = load_config("config.yaml")
    c = Course(7, "GÜZ", "Lisans", 7, None, "Sezgisel Optimizasyon", "T", 3, 0, 0, "S", True)
    assert cfg.eligible_rooms(Component("s", c, "T", 3, False)) == [cfg.lab_room]


def test_course_rooms_restricts_to_required_room():
    cfg = load_config("config.yaml")
    c = Course(5, "GÜZ", "Lisans", 3, None, "Olasılık Teorisi ve İstatistiğe Giriş",
               "F", 3, 0, 0, "Z", True)
    assert cfg.eligible_rooms(Component("o", c, "T", 3, False)) == ["D-731"]


def test_amfi_assignment_component_specific():
    cfg = load_config("config.yaml")
    ori = Course(11, "GÜZ", "Lisans", 5, None, "Operations Research I", "Hoca A", 3, 2, 0, "Z", True)
    fac = Course(12, "GÜZ", "Lisans", 5, None, "Facilities Planning", "Hoca E", 2, 2, 0, "Z", True)
    # OR I: T bloku K-B04, U bloku K-B01 ("Ders:U" girdisi ders girdisini ezer)
    assert cfg.eligible_rooms(Component("t", ori, "T", 3, False)) == ["K-B04"]
    assert cfg.eligible_rooms(Component("u", ori, "U", 2, False)) == ["K-B01"]
    # Facilities: U tahsisli K-B01; T tahsissiz -> Amfi yer tutucu
    assert cfg.eligible_rooms(Component("ft", fac, "T", 2, False)) == ["Amfi"]
    assert cfg.eligible_rooms(Component("fu", fac, "U", 2, False)) == ["K-B01"]


def test_bahar_config_loads_with_new_fields():
    cfg = load_config("config_bahar.yaml")
    assert cfg.default_pin_cohort == "Lisans-2"
    assert cfg.course_windows["Karar Kuramı"]["max"] == 5
    assert "K-B02" in cfg.room_windows
    assert cfg.fixed_session_groups["İş Hukuku"] == "I"
    ori = Course(1, "BAHAR", "Lisans", 6, None, "Operations Research II", "Hoca A", 3, 2, 0, "Z", True)
    assert cfg.eligible_rooms(Component("t", ori, "T", 3, False)) == ["K-B01", "K-B02"]


def test_room_window_blocks_complement():
    from src.main import room_window_blocks
    cfg = load_config("config_bahar.yaml")
    blocks = room_window_blocks(cfg, [])
    kb2 = [(b.day, b.period, b.length) for b in blocks if b.room == "K-B02"]
    cells = set()
    for d, p, ln in kb2:
        for k in range(ln):
            cells.add((d, p + k))
    # Salı P4-P6 (idx 3-5) pencere içi -> bloklanmaz; Salı P2 (idx 1) pencere dışı -> bloklanır
    assert (1, 3) not in cells and (1, 4) not in cells and (1, 5) not in cells
    assert (1, 1) in cells and (0, 5) in cells  # Pazartesi tamamen bloklu
