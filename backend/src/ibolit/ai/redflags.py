"""Deterministic red-flag engine."""

from __future__ import annotations

import re
from dataclasses import dataclass

KAZAKH_FOLD = str.maketrans({"ә": "а", "ғ": "г", "қ": "к", "ң": "н", "ө": "о", "ұ": "у", "ү": "у", "һ": "х", "і": "и", "ё": "е"})
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize(text: str) -> str:
    folded = text.casefold().translate(KAZAKH_FOLD)
    return " " + _NON_WORD.sub(" ", folded).strip() + " "


@dataclass(frozen=True)
class RedFlagRule:
    id: str
    label: str
    patterns: tuple[str, ...]


RULES: tuple[RedFlagRule, ...] = (
    RedFlagRule("sudden_severe_headache", "Sudden severe headache", (
        "sudden severe headache", "severe sudden headache", "worst headache", "thunderclap", "sudden headache",
        "head is exploding", "worst pain of my life",
        "внезапная сильная головная боль", "внезапно сильно болит голова", "резкая головная боль", "сильнейшая головная боль",
        "резко заболела голова", "голова раскалывается",
        "кенеттен катты бас ауыру", "басым кенеттен катты ауырды", "басым катты ауырып кетти",
    )),
    RedFlagRule("stroke_signs", "Sudden weakness, numbness or speech problems", (
        "sudden weakness", "weakness on one side", "one side of my body", "face drooping", "face is drooping", "drooping face",
        "slurred speech", "cant speak", "can't speak", "cannot speak", "trouble speaking", "numbness on one side",
        "arm went numb", "cant move my arm", "can't move my arm", "weakness",
        "внезапная слабость", "слабость в руке", "онемела половина", "онемение половины", "перекосило лицо", "лицо перекосило",
        "невнятная речь", "не могу говорить", "отнялась рука", "отнялась нога", "слабость",
        "кенеттен алсиздик", "бетим кисайып", "бети кисайды", "сойлей алмаймын", "колым жансызданды", "алсиздик",
    )),
    RedFlagRule("fainting", "Fainting or loss of consciousness", (
        "faint", "fainted", "fainting", "passed out", "pass out", "lost consciousness", "unconscious", "blacked out",
        "обморок", "потерял сознание", "потеряла сознание", "без сознания", "упал в обморок", "упала в обморок", "теряю сознание",
        "есинен танды", "есимнен тандым", "талып калдым", "талып калды", "есин жогалтты",
    )),
    RedFlagRule("chest_pain", "Chest pain or pressure", (
        "chest pain", "pain in my chest", "pain in the chest", "chest tightness", "tight chest", "pressure in my chest",
        "chest pressure", "heart attack", "crushing chest",
        "боль в груди", "болит в груди", "болит грудь", "давит в груди", "жжение в груди", "сердечный приступ", "инфаркт",
        "кеуде ауырады", "кеудем ауырады", "кеудем кысып", "журек талмасы", "инфаркт",
    )),
    RedFlagRule("breathing", "Severe shortness of breath", (
        "shortness of breath", "short of breath", "cant breathe", "can't breathe", "cannot breathe", "difficulty breathing",
        "trouble breathing", "struggling to breathe", "choking", "gasping",
        "не могу дышать", "задыхаюсь", "одышка", "трудно дышать", "нечем дышать", "удушье",
        "дем ала алмаймын", "тыныс ала алмаймын", "тунщыгып", "тұншығып", "демикпе",
    )),
    RedFlagRule("suicidal", "Thoughts of suicide or self-harm", (
        "suicide", "suicidal", "kill myself", "end my life", "want to die", "self harm", "self-harm", "hurt myself",
        "dont want to live", "don't want to live",
        "суицид", "покончить с собой", "хочу умереть", "убить себя", "навредить себе", "не хочу жить", "покончу с собой",
        "озимди олтиргим", "омир сургим келмейди", "озиме кол жумсау", "олгим келеди",
    )),
    RedFlagRule("severe_bleeding", "Heavy bleeding", (
        "heavy bleeding", "bleeding wont stop", "bleeding won't stop", "vomiting blood", "coughing up blood", "blood in vomit",
        "сильное кровотечение", "кровь не останавливается", "рвота с кровью", "кашляю кровью",
        "кан токтамай", "катты кан кету", "кан куса",
    )),
    RedFlagRule("seizure", "Seizure", (
        "seizure", "convulsion", "convulsions", "fitting",
        "судороги", "припадок", "эпилептический",
        "курысу", "курысып", "талма",
    )),
    RedFlagRule("anaphylaxis", "Severe allergic reaction", (
        "throat swelling", "throat is swelling", "swollen throat", "anaphylaxis", "anaphylactic", "severe allergic reaction",
        "tongue swelling", "lips swelling",
        "отек горла", "отёк горла", "опухло горло", "анафилак", "сильная аллергическая реакция", "отекает язык",
        "тамагым исип", "тамак исти", "анафилаксия",
    )),
    RedFlagRule("overdose_poisoning", "Overdose or poisoning", (
        "overdose", "overdosed", "poisoning", "poisoned", "swallowed pills", "took too many pills",
        "передозировка", "отравление", "отравился", "отравилась", "выпил таблетки",
        "уланып", "уланды", "дари артык ишип",
    )),
)

_COMPILED: tuple[tuple[RedFlagRule, tuple[str, ...]], ...] = tuple(
    (rule, tuple(normalize(p).strip() for p in rule.patterns)) for rule in RULES
)


def _match(normalized: str, pattern: str) -> bool:
    # Patterns match on word starts so "faint" also catches "fainted", but "weakness"
    # inside an unrelated longer word does not.
    return f" {pattern}" in normalized


def detect(text: str) -> list[RedFlagRule]:
    normalized = normalize(text)
    return [rule for rule, patterns in _COMPILED if any(_match(normalized, p) for p in patterns)]
