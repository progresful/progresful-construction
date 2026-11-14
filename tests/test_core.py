import json

import pytest

from constructor.answer import answer
from constructor.extractors import raster
from constructor.batch import run
from constructor.ingest import cache_path
from constructor.mapper import map_rules
from constructor.reviews import apply_reviews
from constructor.schema import Drawing, Element
from constructor.scoring import is_correct
from constructor.split import group_of, split_of
from constructor import templates


@pytest.fixture(autouse=True)
def no_calibration(monkeypatch):
    """Tests use the spec's plain estimate maths, not whatever calibration.json holds."""
    monkeypatch.setattr(templates, "calibration", lambda: {})


def raster_windows() -> Drawing:
    # The spec's example: 12 confirmed, uncertain at 0.6 and 0.5, one dropped.
    els = [Element(id=i, type="window", source="script+vlm", exact=False, conf=0.9) for i in range(1, 13)]
    els += [
        Element(id=13, type="window", source="script", exact=False, conf=0.6),
        Element(id=14, type="window", source="script", exact=False, conf=0.5),
        Element(id=15, type="window", source="script", exact=False, conf=0.2),
    ]
    return Drawing(drawing="colorful-1.png", kind="raster", extractor_version="raster-0.0", units="px", elements=els)


def ifc_rooms() -> Drawing:
    def room(i, label, area, source):
        return Element(id=i, type="room", source=f"g{i}", exact=True, label=label, storey="1. Sal",
                       quantities={"area_m2": area}, quantity_source={"area_m2": source})
    return Drawing(
        drawing="house.ifc",
        kind="ifc",
        extractor_version="ifc-0.0",
        units="m",
        elements=[
            room(1, "Kontor (Rum nr. 405)", 12.5, "quantity_set"),
            room(2, "Køkken", 8.0, "geometry"),
            Element(id=3, type="window", source="g3", exact=True, storey="1. Sal"),
            Element(id=4, type="window", source="g4", exact=True, storey="2. Sal"),
            Element(id=5, type="storey", source="s1", exact=True, storey="1. Sal"),
            Element(id=6, type="storey", source="s2", exact=True, storey="2. Sal"),
        ],
    )


@pytest.mark.parametrize(
    "question, template, params",
    [
        # CubiCasa: phrasings where a room word and a fixture word share one question.
        ("How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan?",
         "count_elements", {"element": "sink"}),
        ("How many bathrooms or washrooms (e.g. KH, KPH, PH, PESUH, SH) are on this floor plan, not counting separate WC rooms?",
         "count_rooms", {"room_type": "bathroom"}),
        ("How many separate WC rooms (toilet rooms marked WC) are on this floor plan?", "count_rooms", {"room_type": "wc_room"}),
        ("Kuinka monta erillistä WC-tilaa pohjapiirustuksessa on?", "count_rooms", {"room_type": "wc_room"}),
        ("Kuinka monta WC-istuinta pohjapiirustukseen on piirretty?", "count_elements", {"element": "wc"}),
        ("How many showers and bathtubs are drawn on this floor plan in total?", "count_elements", {"element": "shower_or_bathtub"}),
        ("Kuinka monta ikkunaa pohjapiirustuksessa on?", "count_elements", {"element": "window"}),
        ("Kuinka monta kerrosta pohjapiirustuksessa on esitetty?", "count_storeys", {}),
        # Swiss: quoted labels, including one with an apostrophe inside.
        ("How many rooms labelled 'Cage d'escalier' are there on this floor?", "count_rooms", {"label": "Cage d'escalier"}),
        ("Combien de pièces portant la désignation « Couloir » y a-t-il à cet étage ?", "count_rooms", {"label": "Couloir"}),
        ("Wie gross ist die Nettofläche von Raum U1.15 («Korridor») in m²?", "room_area", {"number": "U1.15", "label": "Korridor"}),
        ("Qual è la superficie netta dell'appartamento C in m² (somma di tutti i locali, esclusi balconi, logge, terrazze e altri spazi esterni)?",
         "apartment_area", {"apartment": "C"}),
        ("Combien de portes (portes intérieures et portes d'entrée confondues) sont dessinées sur ce plan ?", "count_elements", {"element": "door"}),
        ("What is the total net floor area in m² of all numbered indoor rooms on this floor (excluding balconies, loggias, terraces and other outdoor spaces, shafts and voids)?",
         "total_area", {"scope": "numbered_indoor"}),
        # IFC: storey or model scope, in three quoting styles.
        ("What is the net floor area of the room 'TUALETTRUUM (43-3)' on '3.korrus', in m²?", "room_area", {"name": "TUALETTRUUM (43-3)", "storey": "3.korrus"}),
        ("Kui suur on ruumi „ESIK (1-1)“ netopõrandapind korrusel „1.korrus“ (m²)?", "room_area", {"name": "ESIK (1-1)", "storey": "1.korrus"}),
        ("Hvor mange søjler er vist på plantegningen for 'Kælder'?", "count_elements", {"element": "column", "storey": "Kælder"}),
        ("Mitu tala on mudelis „Maleva tänav 18 korterelamu (Esplanades example model)“?", "count_elements",
         {"element": "beam", "model": "Maleva tänav 18 korterelamu (Esplanades example model)"}),
        ("Wie groß ist das gesamte Netto-Volumen aller Decken und Bodenplatten im Geschoss „Dachgeschoss“ in m³?", "element_volume",
         {"element": "slab", "storey": "Dachgeschoss"}),
        ("Hvad er den samlede længde af alle vægge på '2. Sal' i meter?", "wall_length", {"storey": "2. Sal"}),
        ("What is the total net side area of all walls on '2. Sal', in m²?", "wall_side_area", {"storey": "2. Sal"}),
        ("What colour is the roof?", None, {}),
    ],
)
def test_mapper(question, template, params):
    m = map_rules(question)
    assert (m.template, m.params) == (template, params)


def test_estimate_maths_matches_spec_example():
    a = answer(raster_windows(), "How many windows are shown on this floor plan?")
    assert a.value == 13
    assert a.range == [12, 14]
    assert not a.exact
    assert len(a.evidence_ids) == 12 and a.uncertain_ids == [13, 14]
    assert 15 not in a.evidence_ids + a.uncertain_ids


def test_calibration_widens_estimate_ranges(monkeypatch):
    monkeypatch.setattr(templates, "calibration", lambda: {"window": {"lo": -1, "hi": 3}, "whole:bedrooms": {"lo": 0, "hi": 1}})
    d = raster_windows()
    d.covers = ["window"]
    a = answer(d, "How many windows are shown on this floor plan?")
    assert (a.value, a.range) == (13, [12, 16])  # misses widen the top: marks under-count
    d = Drawing(drawing="data/cubicasa5k/colorful-1.png", kind="raster", extractor_version="x", units="px",
                elements=[], covers=[], counts={"bedrooms": 2})
    assert answer(d, "How many bedrooms are on this floor plan?").range == [2, 3]


def test_exact_count_has_no_range():
    a = answer(ifc_rooms(), "How many windows are shown on this floor plan?")
    assert (a.value, a.exact, a.range) == (2, True, None)


def test_area_exactness_follows_quantity_source():
    office = answer(ifc_rooms(), "What is the net floor area of the room 'Kontor (Rum nr. 405)' on '1. Sal', in m²?")
    assert (office.value, office.exact) == (12.5, True)
    kitchen = answer(ifc_rooms(), "What is the net floor area of the room 'Køkken' on '1. Sal', in m²?")
    assert (kitchen.value, kitchen.exact) == (8.0, False)  # computed from geometry
    total = answer(ifc_rooms(), "What is the total net floor area of all rooms (spaces) on '1. Sal', in m²?")
    assert (total.value, total.exact) == (20.5, False)


def test_unknown_storey_is_unanswerable_not_zero():
    assert answer(ifc_rooms(), "How many windows are shown on the floor plan of '9. Sal'?").value is None
    assert answer(ifc_rooms(), "How many windows are shown on the floor plan of '2. Sal'?").value == 1


def test_cannot_answer():
    a = answer(ifc_rooms(), "What colour is the roof?")
    assert a.template is None and a.value is None and not a.answered


def test_storeys_need_storey_elements():
    assert answer(raster_windows(), "How many floors (storeys) does this floor plan show?").value is None
    assert answer(ifc_rooms(), "How many floors (storeys) does this floor plan show?").value == 2


def test_reviews():
    d = apply_reviews(raster_windows(), [
        {"id": 13, "action": "accept"},
        {"id": 14, "action": "reject"},
        {"id": 1, "action": "retype", "type": "door"},
    ])
    a = answer(d, "How many windows are shown on this floor plan?")
    assert a.value == 12 and a.range == [12, 12]  # 11 original + accepted 13


def test_reviewer_can_add_and_take_back_elements(tmp_path, monkeypatch):
    from constructor import reviews

    monkeypatch.setattr(reviews, "REVIEWS_DIR", tmp_path)
    cache_file = tmp_path / "x.json"
    d = raster_windows()
    d.covers = ["window"]
    add = {"action": "add", "type": "window", "bbox": [0, 0, 5, 5], "id": reviews.next_added_id([])}
    reviews.save_review(cache_file, add)
    edits = reviews.load_reviews(cache_file)
    assert edits[0]["id"] == reviews.ADDED_ID_BASE
    a = answer(apply_reviews(d, edits), "How many windows are shown on this floor plan?")
    assert a.value == 14 and reviews.ADDED_ID_BASE in a.evidence_ids  # 12 + round(1.1) + the added one
    # An added door makes doors countable from marks on a drawing that did not mark them.
    reviews.save_review(cache_file, {"action": "add", "type": "door", "bbox": [9, 9, 12, 12], "id": reviews.next_added_id(edits)})
    edits = reviews.load_reviews(cache_file)
    assert answer(apply_reviews(d, edits), "How many doors are shown on this floor plan?").value == 1
    # Rejecting an addition removes it from the file, not just from the answer.
    reviews.save_review(cache_file, {"id": reviews.ADDED_ID_BASE, "action": "reject"})
    assert [e["type"] for e in reviews.load_reviews(cache_file)] == ["door"]


def test_reshape_moves_an_element_and_keeps_its_verdict(tmp_path, monkeypatch):
    from constructor import reviews

    monkeypatch.setattr(reviews, "REVIEWS_DIR", tmp_path)
    cache_file = tmp_path / "x.json"
    reviews.save_review(cache_file, {"id": 13, "action": "reshape", "bbox": [1, 1, 3, 3]})
    reviews.save_review(cache_file, {"id": 13, "action": "accept"})  # a verdict does not undo the reshape
    d = apply_reviews(raster_windows(), reviews.load_reviews(cache_file))
    el = next(e for e in d.elements if e.id == 13)
    assert (el.bbox, el.conf) == ([1, 1, 3, 3], 1.0)
    # A room outline: bbox follows it; a computed area is recomputed in metres.
    room = Element(id=50, type="room", source="x", exact=True, bbox=[0, 0, 2, 2], polygon=[[0, 0], [2, 0], [2, 2], [0, 2]],
                   quantities={"area_m2": 4.0}, quantity_source={"area_m2": "geometry"})
    ifc = Drawing(drawing="m.ifc", kind="ifc", extractor_version="x", units="m", elements=[room])
    out = apply_reviews(ifc, [{"id": 50, "action": "reshape", "polygon": [[0, 0], [3, 0], [3, 2], [0, 2]]}]).elements[0]
    assert (out.bbox, out.quantities["area_m2"], out.quantity_source["area_m2"]) == ([0, 0, 3, 2], 6.0, "reviewer")
    # An image plan: pixels times its scale, with the scale's error; a printed area is left alone.
    px_room = Element(id=51, type="room", source="x", exact=False, bbox=[0, 0, 100, 100], polygon=[[0, 0], [100, 0], [100, 100], [0, 100]],
                      quantities={"area_m2": 9.0, "area_m2_err": 2.7}, quantity_source={"area_m2": "scale"})
    printed = Element(id=52, type="room", source="x", exact=False, bbox=[0, 0, 50, 50], quantities={"area_m2": 11.0}, quantity_source={"area_m2": "label"})
    img = Drawing(drawing="p.png", kind="raster", extractor_version="x", units="px", elements=[px_room, printed], covers=[],
                  scale={"m_per_px": 0.03, "source": "door width", "n": 5, "rel_err": 0.3})
    edits = [{"id": 51, "action": "reshape", "bbox": [0, 0, 200, 100]}, {"id": 52, "action": "reshape", "bbox": [0, 0, 80, 80]}]
    a, b = apply_reviews(img, edits).elements
    assert (a.quantities["area_m2"], a.quantities["area_m2_err"]) == (18.0, 5.4)
    assert b.quantities["area_m2"] == 11.0


def test_split_is_about_20_percent_and_keeps_copies_together():
    names = [f"data/cubicasa5k/colorful-{i}.png" for i in range(5000)]
    held = sum(split_of(n) == "heldout" for n in names)
    assert 0.17 < held / len(names) < 0.23
    assert split_of("data/cubicasa5k/colorful-7.png") == split_of("/abs/data/cubicasa5k/colorful-7.png")
    swiss = "data/swiss_dwellings/site1_bldg2_floor3"
    assert group_of(f"{swiss}.pdf") == group_of(f"{swiss}.dxf") == group_of(f"{swiss}.png")
    assert group_of("data/ifc_models/m_x.ifc") == group_of("data/ifc_models/m_x_plan-02-klder.pdf")
    assert group_of("data/opening_design/CTR/a/b.pdf") == group_of("data/opening_design/CTR/c.dwg")
    # Full paths with an outer data/ folder must split exactly like dataset-relative paths.
    rel = "data/swiss_dwellings/site2150_bldg3001_floor13690.dxf"
    assert group_of(f"data/preview/junction-dataset-preview/{rel}") == group_of(rel)
    assert group_of(f"/abs/data/preview/x/{rel}") == group_of(rel)


def test_scoring():
    assert is_correct(13, "13", "count")
    assert not is_correct(13, 14, "count")
    assert is_correct(10.15, "10", "m2")
    assert not is_correct(10.3, 10, "m2")
    assert is_correct(10.0, 107.64, "ft2", "m2")  # converted
    assert is_correct("Kitchen", "kitchen", "text")
    assert not is_correct(None, 0, "count")


def test_batch_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = raster_windows()
    d.drawing = "data/cubicasa5k/colorful-1.png"
    d.extractor_version = raster.VERSION  # a fresh cache: the batch must not re-extract the empty image
    (tmp_path / "data/cubicasa5k").mkdir(parents=True)
    (tmp_path / d.drawing).write_bytes(b"")
    d.save(cache_path(tmp_path / d.drawing))
    qs = tmp_path / "questions.jsonl"
    qs.write_text("\n".join(json.dumps(r) for r in [
        {"path": d.drawing, "question": "How many windows are shown on this floor plan?", "answer": 13, "unit": "count", "type": "count"},
        {"path": d.drawing, "question": "What colour is the roof?", "answer": "red", "unit": None, "type": "text"},
        {"path": "data/cubicasa5k/colorful-999.png", "question": "How many doors?", "answer": 2, "unit": "count", "type": "count"},
    ]))
    groups = run(qs, "all", None, None)
    total = groups["total"]["all"]
    assert (total.questions, total.correct, total.answered, total.not_extracted) == (3, 1, 1, 1)
    assert groups["template"]["(unmapped)"].questions == 1
    assert groups["tier"]["cubicasa/colorful"].questions == 3


def test_whole_image_counts_answer_uncovered_types_without_marks():
    d = Drawing(drawing="data/cubicasa5k/colorful-1.png", kind="raster", extractor_version="x", units="px",
                elements=[Element(id=1, type="room", source="script", exact=False, conf=0.9, room_type="bedroom")],
                covers=[], counts={"windows": 7, "bedrooms": 2, "storeys": 1})
    a = answer(d, "How many windows are shown on this floor plan?")
    assert (a.value, a.exact, a.evidence_ids, a.range) == (7, False, [], None)
    # OCR found one bedroom label, but labels are not trusted for counting yet (covers is empty).
    assert answer(d, "How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?").value == 2
    assert answer(d, "How many floors (storeys) does this floor plan show?").value == 1
    # No whole-image count for this type: still unanswerable, never 0.
    assert answer(d, "How many saunas are on this floor plan?").value is None


def test_overview_uses_answer_and_never_claims_exact_without_elements():
    from constructor import overview

    d = raster_windows()
    d.elements.append(Element(id=99, type="room", source="script+vlm", exact=False, conf=0.9, room_type="bedroom", label="MH"))
    d.covers = ["window", "wc_room"]
    d.counts = {"bedrooms": 2}
    facts = {f["key"]: f["answer"] for f in overview.facts(d, lambda a: "")}
    assert facts["window"]["value"] == 13
    # Zero WC rooms found on an image is an estimate, not a certainty.
    assert facts["wc_room"]["value"] == 0 and facts["wc_room"]["exact"] is False
    assert facts["bedroom"]["value"] == 2  # whole-image count
    assert "sauna" not in facts  # no count, no marks: not shown rather than 0
    assert "How many windows?" in overview.suggestions(d)
