from src.solve import ScheduledBlock
from src.config import load_config
from src.checker import check


def _b(name, level="YL", sem=1, kind="T", length=3, day=0, period=1,
       room="TUSAŞ Lab", instr="H", group=""):
    return ScheduledBlock(name, "", level, sem, kind, length, day, period,
                          room, instr, group, False)


def test_clean_schedule_passes():
    cfg = load_config("config.yaml")
    blocks = [_b("A")]
    assert check(blocks, [], [], cfg) == []


def test_detects_instructor_clash():
    cfg = load_config("config.yaml")
    blocks = [_b("A", length=2, period=1, room="TUSAŞ Lab", instr="HOCA"),
              _b("B", length=2, period=2, room="Lisansüstü Sınıfı", instr="HOCA")]
    v = check(blocks, [], [], cfg)
    assert any("instructor clash" in msg for msg in v)


def test_detects_room_clash():
    cfg = load_config("config.yaml")
    blocks = [_b("A", length=2, period=1, instr="H1"),
              _b("B", length=2, period=2, instr="H2")]
    v = check(blocks, [], [], cfg)
    assert any("room clash" in msg for msg in v)


def test_detects_p1_and_late_violations():
    cfg = load_config("config.yaml")
    early = [_b("A", period=0)]
    assert any("P1 violation" in msg for msg in check(early, [], [], cfg))
    late = [_b("B", period=8, length=3)]  # P9..P11 crosses latest_period=10
    assert any("late violation" in msg for msg in check(late, [], [], cfg))


def test_detects_amfi_and_lab_violations():
    cfg = load_config("config.yaml")
    # amfi course wrongly in a classroom
    wrong = [_b("Quality Engineering", level="Lisans", sem=5, room="D-731", instr="S")]
    assert any("amfi violation" in msg for msg in check(wrong, [], [], cfg))
    # L-hours wrongly outside the lab (course NOT in lab_only, so the generic branch fires)
    lab = [_b("Systems Simulation", level="Lisans", sem=7, kind="L",
              length=2, room="D-731", instr="S")]
    assert any("lab violation" in msg for msg in check(lab, [], [], cfg))
    # a lab_only course anywhere outside the lab trips the stricter branch
    lo = [_b("Bilgisayar Programlama", level="Lisans", sem=3, kind="T",
             length=2, room="D-731", instr="Ö")]
    assert any("lab-only violation" in msg for msg in check(lo, [], [], cfg))


def test_detects_cross_group_elective_clash():
    cfg = load_config("config.yaml")
    blocks = [
        _b("Sezgisel Optimizasyon", level="Lisans", sem=7, day=1, period=2,
           room="D-731", instr="T", group="F"),
        _b("Endüstri 4.0 ve Dijital Dönüşüm", level="Lisans", sem=7, day=1, period=2,
           room="D-733", instr="Y", group="G"),
    ]
    v = check(blocks, [], [], cfg)
    assert any("cross-group elective clash" in msg for msg in v)


def test_detects_free_day_violation():
    cfg = load_config("config.yaml")
    blocks = [_b(f"C{d}", level="Lisans", sem=7, day=d, period=1 + d,
                 room="D-731", instr=f"H{d}", group="") for d in range(5)]
    v = check(blocks, [], [], cfg)
    assert any("free-day violation" in msg for msg in v)


def test_detects_availability_violation():
    from src.config import Availability
    cfg = load_config("config.yaml")
    av = Availability({"HOCA": {(0, 1)}})
    blocks = [_b("A", instr="HOCA", day=0, period=1)]
    v = check(blocks, [], [], cfg, availability=av)
    assert any("availability violation" in msg for msg in v)


def test_detects_fixed_pin_clash():
    from src.domain import FixedSession
    cfg = load_config("config.yaml")
    pin = FixedSession("Matematik I (Grup 1) Endüstri", None, 0, 1, 3, "K-B03")
    clash = [_b("Ders", level="Lisans", sem=1, day=0, period=2, room="D-731", instr="H")]
    v = check(clash, [pin], [], cfg)
    assert any("fixed-pin clash" in msg for msg in v)
    # same slot but a DIFFERENT cohort (sem-3) -> no pin clash
    ok = [_b("Ders", level="Lisans", sem=3, day=0, period=2, room="D-731", instr="H")]
    assert not any("fixed-pin clash" in msg for msg in check(ok, [pin], [], cfg))


def test_detects_fixed_pin_clash_for_grad_target():
    # a pin mapped to YL-1 via fixed_session_cohorts must be checker-visible too
    import copy
    from src.domain import FixedSession
    cfg = copy.deepcopy(load_config("config.yaml"))
    cfg.fixed_session_cohorts = {"YL Ortak": "YL-1"}
    pin = FixedSession("YL Ortak Ders", None, 1, 2, 3, "Lisansüstü Sınıfı")
    clash = [_b("Seminer Dersi", level="YL", sem=1, day=1, period=3, room="TUSAŞ Lab", instr="H")]
    v = check(clash, [pin], [], cfg)
    assert any("fixed-pin clash" in msg for msg in v)


def test_detects_lab_only_violation():
    cfg = load_config("config.yaml")
    wrong = [_b("Sezgisel Optimizasyon", level="Lisans", sem=7, room="D-731", instr="T", group="F")]
    v = check(wrong, [], [], cfg)
    assert any("lab-only violation" in msg for msg in v)


def test_dual_room_block_occupies_both_rooms():
    cfg = load_config("config.yaml")
    dual = _b("Systems Simulation", level="Lisans", sem=7, kind="TU", length=4,
              day=0, period=1, room="D-731 / End.Müh. Bilg. Lab.", instr="S")
    assert check([dual], [], [], cfg) == []
    # anything else in the lab at that time clashes
    other = _b("İş Zekası", level="YL", sem=1, kind="T", length=3, day=0, period=2,
               room="End.Müh. Bilg. Lab.", instr="E")
    v = check([dual, other], [], [], cfg)
    assert any("room clash" in msg and "Bilg. Lab" in msg for msg in v)
    # dual course missing its lab reservation is flagged
    wrong = _b("Systems Simulation", level="Lisans", sem=7, kind="TU", length=4,
               day=0, period=1, room="D-731", instr="S")
    assert any("dual-room violation" in msg for msg in check([wrong], [], [], cfg))


def test_detects_blocked_slot_violation():
    import copy
    cfg = copy.deepcopy(load_config("config.yaml"))
    cfg.blocked_slots = [{"day": "Cuma", "periods": [6]}]
    bad = [_b("A", level="Lisans", sem=7, day=4, period=4, length=3, room="D-731")]  # P5-P7 covers P6
    assert any("blocked-slot" in msg for msg in check(bad, [], [], cfg))


def test_detects_partial_overlap_and_selection_violations():
    cfg = load_config("config.yaml")
    # partial overlap within a pick-k group (offset by 1 period)
    bad = [
        _b("Lean Production", level="Lisans", sem=5, day=0, period=2, room="D-731",
           instr="Y", group="D"),
        _b("İşletme Finansı", level="Lisans", sem=5, day=0, period=3, room="D-733",
           instr="F", group="D"),
    ]
    v = check(bad, [], [], cfg)
    assert any("partial-overlap violation" in msg for msg in v)
    # fewer distinct slots than pick_k: all 3 F-ish picks collapsed to 2 slots
    few = [
        _b("Lean Production", level="Lisans", sem=5, day=0, period=2, room="D-731",
           instr="A", group="D"),
        _b("İşletme Finansı", level="Lisans", sem=5, day=0, period=2, room="D-733",
           instr="B", group="D"),
        _b("Technology and R&D Management", level="Lisans", sem=5, day=1, period=2,
           room="D-731", instr="C", group="D"),
        _b("Veri Madenciliği ve Bilgi Keşfi", level="Lisans", sem=5, day=1, period=2,
           room="D-733", instr="D", group="D"),
    ]
    v2 = check(few, [], [], cfg)
    assert any("selection violation" in msg for msg in v2)


def test_detects_course_room_violation():
    cfg = load_config("config.yaml")
    bad = [_b("Endüstri Mühendisliğine Giriş", level="Lisans", sem=1, length=2,
              room="D-724", instr="Ş")]
    assert any("course-room violation" in msg for msg in check(bad, [], [], cfg))


def test_split_room_only_flags_adjacent_blocks():
    cfg = load_config("config.yaml")
    # adjacent (Pzt P2-P4 + P5-P6) in DIFFERENT rooms -> violation
    adj = [_b("X", level="YL", sem=1, kind="T", length=3, day=0, period=1,
              room="TUSAŞ Lab", instr="H"),
           _b("X", level="YL", sem=1, kind="U", length=2, day=0, period=4,
              room="Lisansüstü Sınıfı", instr="H")]
    assert any("split-room" in msg for msg in check(adj, [], [], cfg))
    # same rooms adjacent -> clean
    adj_ok = [_b("X", kind="T", length=3, day=0, period=1, room="TUSAŞ Lab"),
              _b("X", kind="U", length=2, day=0, period=4, room="TUSAŞ Lab")]
    assert not any("split-room" in msg for msg in check(adj_ok, [], [], cfg))
    # NON-adjacent (different days) in different rooms -> allowed
    far = [_b("X", kind="T", length=3, day=0, period=1, room="TUSAŞ Lab"),
           _b("X", kind="U", length=2, day=1, period=1, room="Lisansüstü Sınıfı")]
    assert not any("split-room" in msg for msg in check(far, [], [], cfg))


def test_amfi_expected_room_is_component_specific():
    cfg = load_config("config.yaml")
    # OR I: T tahsisi K-B04, U tahsisi K-B01 (config amfi_assignments "Ders:U")
    ok = [_b("Operations Research I", level="Lisans", sem=5, kind="T", length=3,
             day=2, period=1, room="K-B04", instr="Ş"),
          _b("Operations Research I", level="Lisans", sem=5, kind="U", length=2,
             day=2, period=7, room="K-B01", instr="OR I Asistanı")]
    assert not any("amfi violation" in msg for msg in check(ok, [], [], cfg))
    # U bloku K-B04'te kalsaydı artık ihlal olurdu
    bad = [_b("Operations Research I", level="Lisans", sem=5, kind="U", length=2,
              day=2, period=7, room="K-B04", instr="OR I Asistanı")]
    assert any("amfi violation" in msg for msg in check(bad, [], [], cfg))


def test_course_window_violation_detected():
    from src.config import load_config as _lc
    cfg = _lc("config_bahar.yaml")
    # Karar Kuramı max P5: P4-P6'ya taşan blok ihlal
    bad = [_b("Karar Kuramı", level="DR", sem=2, kind="T", length=3, day=1,
              period=3, room="TUSAŞ Lab", instr="Öğr. Üyesi 12")]
    assert any("course-window" in m for m in check(bad, [], [], cfg))
    ok = [_b("Karar Kuramı", level="DR", sem=2, kind="T", length=3, day=1,
             period=2, room="TUSAŞ Lab", instr="Öğr. Üyesi 12")]
    assert not any("course-window" in m for m in check(ok, [], [], cfg))


def test_pin_group_exemption_in_fixed_clash():
    from src.config import load_config as _lc
    from src.domain import FixedSession
    cfg = _lc("config_bahar.yaml")
    # Uygulamalı Girişimcilik pini (J grubu) Pzt P1-P4; J üyesi Hizmet Pazarlaması
    # onunla çakışabilir, H üyesi Süreç Yönetimi çakışamaz
    pin = FixedSession("Uygulamalı Girişimcilik (Grup 6) Endüstri", "X", 0, 1, 3, "D732")
    j = [_b("Hizmet Pazarlaması", level="Lisans", sem=8, length=3, day=0, period=1,
            room="D-724", instr="Öğr. Üyesi 03", group="J")]
    assert not any("fixed-pin clash" in m for m in check(j, [pin], [], cfg))
    h = [_b("Süreç Yönetimi", level="Lisans", sem=8, length=3, day=0, period=1,
            room="D-724", instr="Öğr. Üyesi 19", group="H")]
    assert any("fixed-pin clash" in m for m in check(h, [pin], [], cfg))


def test_amfi_list_assignment_allows_either_room():
    from src.config import load_config as _lc
    cfg = _lc("config_bahar.yaml")
    for room in ("K-B01", "K-B02"):
        ok = [_b("Engineering Economics", level="Lisans", sem=6, length=3, day=1,
                 period=3, room=room, instr="Öğr. Üyesi 12")]
        assert not any("amfi violation" in m for m in check(ok, [], [], cfg))
    bad = [_b("Engineering Economics", level="Lisans", sem=6, length=3, day=1,
              period=3, room="D-731", instr="Öğr. Üyesi 12")]
    assert any("amfi violation" in m for m in check(bad, [], [], cfg))
