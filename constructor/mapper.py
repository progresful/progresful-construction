"""Question -> (template, params).

Rule-based first: free, deterministic, and the dataset's questions are templated in
seven languages (en, fi, fr, it, de, da, et). Unmatched questions go to an optional
text-model mapper, whose cost is reported. Rules are written against the train split only.

Order matters throughout: more specific phrases are checked before the words they
contain ("showers and bathtubs" before "showers", "bathrooms" before "WC rooms").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .templates import TEMPLATES


@dataclass
class Mapping:
    template: str | None
    params: dict = field(default_factory=dict)
    cost_usd: float = 0.0


LLMMapper = Callable[[str], Mapping]

# Quoted parameters: 'x', «x», „x“, “x”. A straight-quoted value may contain an
# apostrophe ('Cage d'escalier'), so its closing quote must be followed by a boundary.
QUOTED = re.compile(r"«\s*([^»]+?)\s*»|„([^“”]+)[“”]|“([^”]+)”|(?<![\w])'(.+?)'(?=[\s,.)?:;]|$)")


def quoted(q: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None) for m in QUOTED.finditer(q)]


def _any(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


COUNT = _any(
    r"\bhow many\b", r"\bkuinka monta\b", r"\bmontako\b", r"\bcombien\b", r"\bquant[ie]\b",
    r"\bwie viele\b", r"\bhvor mange\b", r"\bmitu\b",
    r"\bhoeveel\b", r"\bcuál es el número\b", r"\bcu[aá]nt[oa]s\b", r"\bile\b", r"\bliczba\b",
)
AREA = _any(r"\barea\b", r"areal", r"fläche", r"\bsurface\b", r"\bsuperficie\b", r"pind\b", r"oppervlakte", r"powierzchni")
VOLUME = _any(r"\bvolume\b", r"volumen", r"m³", r"objętoś")
LENGTH = _any(r"\blength\b", r"længde", r"\bwie lang\b", r"\blengte\b", r"\blongitud\b", r"długoś")
BY_KIND = _any(r"\bby (?:type|kind)\b", r"\bof each (?:type|kind)\b", r"\bper (?:type|kind)\b", r"\bwhat (?:types|kinds)\b")
MODEL = _any(r"\bmodel\b", r"\bmodellen\b", r"\bmudelis\b", r"\bmodell\b", r"\bmodelo\b", r"\bmodelu\b")

# Fixtures and building elements. First match wins.
ELEMENTS: list[tuple[str, re.Pattern]] = [
    ("shower_or_bathtub", _any(r"showers and bathtubs", r"suihkua ja kylpyammetta")),
    ("sink", _any(r"\bsinks?\b", r"washbasins?", r"pesu- ja tiskial", r"\blavab", r"waschbecken")),
    ("wc", _any(r"toilet bowls?", r"wc-istuin", r"\btoilets \(wc\)", r"\bwcs?\b(?! ?rooms?)(?!-til)")),
    ("shower", _any(r"\bshowers?\b", r"\bdouches?\b", r"\bdocce\b", r"\bduschen?\b")),
    ("bathtub", _any(r"\bbathtubs?\b", r"\bbaignoires?\b", r"vasche da bagno", r"badewannen?")),
    ("window", _any(r"\bwindows?\b", r"\bikkun", r"\bfenêtres?\b", r"\bfinestr", r"\bfenster\b", r"\bvinduer?\b", r"\baken", r"\bramen\b", r"\bventanas?\b", r"\bok(?:ien|na)\b")),
    ("door", _any(r"\bdoors?\b", r"\bove[at]?\b", r"\bportes?\b(?! d)", r"\bport[ae]\b", r"\btüren?\b", r"\bdøre?\b", r"\bust\b", r"\buks", r"\bdeuren\b", r"\bpuertas?\b", r"\bdrzwi\b")),
    ("wall", _any(r"\bwalls?\b", r"\bvægge?\b", r"\bseina", r"\bwände\b", r"\bwanden\b", r"\bmuros?\b", r"\bścian")),
    ("column", _any(r"\bcolumns?\b", r"\bsøjler?\b", r"\bposti\b", r"\bstützen\b", r"\bkolommen\b", r"\bpilares\b", r"\bsłup")),
    ("beam", _any(r"\bbeams?\b", r"\bbjælker?\b", r"\btala\b", r"\bträger\b", r"\bbalken\b", r"\bvigas\b", r"\bbel(?:ek|ki)\b")),
    ("stair", _any(r"\bstairs?\b", r"\btrapper?\b", r"\btreppi?\b", r"\btreppen?\b", r"\btrappen\b", r"\bescaleras\b", r"\bschod")),
    ("valve", _any(r"\bvalves?\b", r"\bventtiil", r"\bventile?\b", r"\bkleppen\b", r"\bválvulas?\b")),
    ("pump", _any(r"\bpumps?\b", r"\bpump(?:pu|uj)", r"\bpumpen\b", r"\bbombas?\b")),
    ("slab", _any(r"\bslabs?\b", r"dæk og plader", r"decken und bodenplatten", r"\bvloeren\b", r"\blosas\b", r"\bstrop")),
    ("apartment", _any(r"\bapartments\b", r"\bappartements\b", r"\bappartamenti\b", r"\bwohnungen\b")),
    ("storey", _any(r"floors \(storeys\)", r"\bkerrosta\b", r"\bstoreys\b", r"\bstories\b", r"\bfloors\b")),
    ("space", _any(r"rooms \(spaces\)", r"\brum\b", r"\bruumi\b", r"\bräume\b", r"\brooms\b", r"\bruimtes\b", r"\blocales\b", r"\bpomieszcze")),
]

# CubiCasa room types, by plan label convention.
ROOM_TYPES: list[tuple[str, re.Pattern]] = [
    ("bathroom", _any(r"\bbathrooms?\b", r"kylpy- tai pesuhuone")),
    ("sauna", _any(r"\bsaunas?\b", r"\bsaunaa\b")),
    ("kitchen", _any(r"\bkitchens?\b", r"\bkeittiötä\b")),
    ("bedroom", _any(r"\bbedrooms?\b", r"\bmakuuhuonetta\b")),
    ("balcony", _any(r"\bbalconies\b", r"\bparveketta\b")),
]

ROOM_PHRASES: list[tuple[str, re.Pattern]] = [
    ("bathroom", _any(r"bathrooms or washrooms", r"kylpy- tai pesuhuone")),
    ("wc_room", _any(r"separate wc rooms?", r"erillistä wc-tilaa")),
]
LABELLED = _any(r"rooms labell?ed", r"pièces portant la désignation", r"locali con la denominazione", r"räume mit der bezeichnung")
ALL_LABELLED = _any(r"all rooms labell?ed", r"toutes les pièces désignées", r"tutti i locali denominati", r"aller räume mit der bezeichnung")
NUMBERED_INDOOR = _any(r"numbered indoor rooms", r"pièces intérieures numérotées", r"locali interni numerati", r"nummerierten innenräume")
APARTMENT = re.compile(r"\b(?:apartment|appartement|appartamento|wohnung)\s+([A-Z])\b", re.I)
ROOM_NUMBER = re.compile(r"\b(?:room|raum|pièce|locale)\s+([A-Z]{0,2}\d+(?:\.\d+)?)\b", re.I)
ALL_SPACES = _any(r"all rooms \(spaces\)", r"alle rum", r"kõigi ruumide", r"alle ruimtes", r"todos los locales", r"wszystkich pomieszcze")
WALL_SIDE = _any(r"side area", r"sideareal", r"seitenfläche")


def _first(table: list[tuple[str, re.Pattern]], q: str) -> str | None:
    return next((name for name, pattern in table if pattern.search(q)), None)


def _scope(q: str, quotes: list[str]) -> dict:
    """IFC questions name either a storey or the whole model, always in quotes."""
    if not quotes:
        return {}
    return {"model": quotes[-1]} if MODEL.search(q) else {"storey": quotes[-1]}


# Conditions no template expresses. The rules would drop them and answer a different question
# ("how many doors open inwards" is not "how many doors"), so such questions go to the LLM.
# Not listed: conditions a template already applies ("except balconies" in apartment areas).
CONDITION = re.compile(
    r"\b(opens?|opening|into|inwards?|outwards?|inside|outside|interior|exterior|internal|external|fac(?:e|es|ing)|"
    r"north|south|east|west|biggest|largest|smallest|bigger|larger|smaller|than|each|per|which|where|have|has|"
    r"with|without|between|leads?|toward|towards|next|adjacent|both|only|wider|narrower)\b",
    re.I,
)


def core(question: str) -> str:
    """The question itself: before the first "?", without parenthesised explanations or quoted names.
    The benchmark explains terms after the question ("Count doorways fitted with a door; ...") or in
    brackets, and a room named 'Open office' is not a condition."""
    head = QUOTED.sub(" ", question).split("?", 1)[0]
    head = BY_KIND.sub(" ", head)  # "by type" asks for a breakdown, which the count templates give
    return re.sub(r"\([^)]*\)", " ", head)


def map_rules(question: str) -> Mapping:
    q = question.strip()
    if CONDITION.search(core(q)):
        return Mapping(None)
    quotes = quoted(q)

    if VOLUME.search(q) and (element := _first(ELEMENTS, q)) in ("wall", "slab"):
        return Mapping("element_volume", {"element": element, **_scope(q, quotes)})
    if LENGTH.search(q) and _first(ELEMENTS, q) == "wall":
        return Mapping("wall_length", _scope(q, quotes))

    if AREA.search(q) and not COUNT.search(q):
        if WALL_SIDE.search(q):
            return Mapping("wall_side_area", _scope(q, quotes))
        if m := APARTMENT.search(q):
            return Mapping("apartment_area", {"apartment": m.group(1).upper()})
        if NUMBERED_INDOOR.search(q):
            return Mapping("total_area", {"scope": "numbered_indoor"})
        if ALL_LABELLED.search(q) and quotes:
            return Mapping("total_area", {"label": quotes[0]})
        if ALL_SPACES.search(q):
            return Mapping("total_area", _scope(q, quotes))
        if m := ROOM_NUMBER.search(q):
            return Mapping("room_area", {"number": m.group(1), **({"label": quotes[0]} if quotes else {})})
        if quotes:
            # IFC: the room name, then the storey.
            params = {"name": quotes[0]}
            if len(quotes) > 1:
                params["storey"] = quotes[1]
            return Mapping("room_area", params)
        return Mapping(None)

    if COUNT.search(q):
        if LABELLED.search(q) and quotes:
            return Mapping("count_rooms", {"label": quotes[0]})
        # Phrases that name a room type but also contain fixture words go first:
        # "bathrooms ... not counting separate WC rooms", "toilet rooms marked WC".
        # Then fixtures before generic room types ("sinks (kitchen and bathroom combined)").
        if room_type := _first(ROOM_PHRASES, q):
            return Mapping("count_rooms", {"room_type": room_type})
        if element := _first(ELEMENTS, q):
            if element == "storey":
                return Mapping("count_storeys")
            by = {"by": "kind"} if BY_KIND.search(q) else {}
            return Mapping("count_elements", {"element": element, **_scope(q, quotes), **by})
        if room_type := _first(ROOM_TYPES, q):
            return Mapping("count_rooms", {"room_type": room_type})

    return Mapping(None)


def map_question(question: str, llm: LLMMapper | None = None,
                 verify: Callable[[str, Mapping], Mapping] | None = None) -> Mapping:
    """Rules first, the LLM for what they miss. `verify` (app only) may overrule a rule match."""
    mapping = map_rules(question)
    if mapping.template is not None and verify is not None:
        mapping = verify(question, mapping)
    elif mapping.template is None and llm is not None:
        mapping = llm(question)
    if mapping.template is not None and mapping.template not in TEMPLATES:
        # A model may name a template we don't have; treat as unmapped, keep its cost.
        return Mapping(None, cost_usd=mapping.cost_usd)
    return mapping
