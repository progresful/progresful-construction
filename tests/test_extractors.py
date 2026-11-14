"""Extractors on real preview files (train split only). Skipped when the dataset is not downloaded."""

from pathlib import Path

import pytest

from constructor.answer import answer
from constructor.split import split_of

DATA = Path("data/preview/junction-dataset-preview")
SWISS = DATA / "data/swiss_dwellings/site2150_bldg3001_floor13690.dxf"
MOLIO = DATA / "data/ifc_models/bsc-molio_molio-with-uris.ifc"

needs_data = pytest.mark.skipif(not DATA.exists(), reason="preview dataset not downloaded")


@needs_data
def test_fixtures_are_train_drawings():
    for f in (SWISS, MOLIO):
        assert split_of(str(f)) == "train"


@needs_data
def test_swiss_dxf():
    from constructor.extractors import dxf

    d = dxf.extract(SWISS)
    ask = lambda q: answer(d, q).value  # noqa: E731
    assert ask("How many doors (interior doors and entrance doors together) are drawn on this floor plan?") == 32
    assert ask("How many apartments (residential units) are shown on this floor plan?") == 3
    # 2.05, 2.12, 2.18 are balconies drawn with only a number; the railing rule must exclude them.
    assert ask("What is the total net floor area in m² of all numbered indoor rooms on this floor "
               "(excluding balconies, loggias, terraces and other outdoor spaces, shafts and voids)?") == pytest.approx(220.29, rel=0.02)
    assert ask("What is the net floor area of apartment B in m², summing all its rooms except balconies, "
               "loggias, terraces and other outdoor spaces?") == pytest.approx(37.6, rel=0.02)


@needs_data
@pytest.mark.slow
def test_molio_ifc():
    from constructor.extractors import ifc

    d = ifc.extract(MOLIO)
    a = answer(d, "Hvad er nettoarealet af rummet 'Kontor (Rum nr. 405)' på '4. Sal' i m²?")
    assert a.value == pytest.approx(20.05, rel=0.02) and a.exact
    # Stair flights aggregated into a stair must not be counted as stairs.
    assert answer(d, "How many stairs are there in the model 'Molio Demo-hus'?").value == 15
