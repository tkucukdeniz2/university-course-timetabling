from src.domain import Course, generate_components


def mk(name, T, U, L, level="Lisans", sem=3, ctype="Z"):
    return Course(0, "GÜZ", level, sem, None, name, "X HOCA", T, U, L, ctype, True)


def test_theory_and_application_merged_into_one_block():
    comps = generate_components([mk("Operations Research I", 3, 2, 0)], set())
    assert len(comps) == 1
    assert comps[0].kind == "TU" and comps[0].length == 5 and comps[0].needs_lab is False


def test_split_tu_keeps_theory_and_application_separate():
    # instructor "X HOCA" is in split_tu -> T and U become separate blocks
    comps = generate_components([mk("Operations Research I", 3, 2, 0)], set(), split_tu={"X HOCA"})
    kinds = sorted((c.kind, c.length) for c in comps)
    assert kinds == [("T", 3), ("U", 2)]


def test_zero_hour_course_excluded():
    assert generate_components([mk("Seminer", 0, 0, 0)], set()) == []


def test_double_star_excluded():
    assert generate_components([mk("Bilgisayar Temelleri**", 2, 0, 2)], set()) == []


def test_lab_flag():
    comps = generate_components([mk("Bilgisayar Programlama", 2, 0, 2)], {"Bilgisayar Programlama"})
    lab = [c for c in comps if c.needs_lab]
    assert len(lab) == 1 and lab[0].kind == "L" and lab[0].length == 2


def test_uygulama_assistant_decouples_u_block():
    comps = generate_components(
        [mk("Operations Research I", 3, 2, 0)], set(),
        uygulama_assistants={"Operations Research I": "OR I Asistanı"})
    kinds = {c.kind: c for c in comps}
    assert set(kinds) == {"T", "U"}
    assert kinds["T"].eff_instructor == "X HOCA"
    assert kinds["U"].eff_instructor == "OR I Asistanı"


def test_single_block_merges_all_hours():
    comps = generate_components(
        [mk("Bilgisayar Programlama", 2, 0, 2)], {"Bilgisayar Programlama"},
        single_block={"Bilgisayar Programlama"})
    assert len(comps) == 1
    c = comps[0]
    assert c.kind == "TUL" and c.length == 4 and c.needs_lab is True
