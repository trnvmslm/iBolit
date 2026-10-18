"""AI assistant provider."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ibolit.integrations.base import ProviderError, ProviderTimeout, note_mock, scenario_is

Mode = Literal[
    "triage",
    "prepare_questions",
    "explain_terms",
    "explain_labs",
    "explain_prescriptions",
    "translate",
]
Urgency = Literal["routine", "soon", "urgent", "emergency"]
Confidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class AiTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class AiRequest:
    mode: Mode
    turns: list[AiTurn]
    locale: str = "en"
    patient_first_name: str = ""


@dataclass(frozen=True)
class AiResult:
    reply_text: str
    recommended_specialty: str | None
    confidence_band: Confidence
    urgency: Urgency
    suggested_actions: list[str] = field(default_factory=list)
    provider_mode: str = "mock"


class AIProvider(Protocol):
    def complete(self, request: AiRequest) -> AiResult: ...

    def stream(self, request: AiRequest) -> Iterator[str]:
        """Yield reply text chunks."""
        ...


# Keyword → specialty map (en / ru / kk). Stems keep inflected forms matching.
SPECIALTY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "neurologist": (
        "headache",
        "head ache",
        "migraine",
        "dizzy",
        "dizziness",
        "vertigo",
        "numb",
        "nerve",
        "tingling",
        "sleep",
        "insomnia",
        "голов",
        "мигрен",
        "головокруж",
        "кружится",
        "онемен",
        "нерв",
        "бессонн",
        "сон",
        "бас ауы",
        "басым ауыр",
        "бас айнал",
        "жүйке",
        "ұйқы",
    ),
    "cardiologist": (
        "chest",
        "heart",
        "palpitation",
        "blood pressure",
        "pressure",
        "pulse",
        "сердц",
        "груд",
        "давлен",
        "пульс",
        "сердцеби",
        "жүрек",
        "кеуде",
        "қан қысым",
        "қысым",
    ),
    "ophthalmologist": (
        "eye",
        "vision",
        "blurry",
        "blurred",
        "sight",
        "глаз",
        "зрени",
        "видеть",
        "көз",
        "көру",
    ),
}

REPLIES: dict[str, dict[str, str]] = {
    "greeting": {
        "en": "Hello{name}. Tell me how you're feeling and when your symptoms started.",
        "ru": "Здравствуйте{name}. Расскажите, как вы себя чувствуете и когда начались симптомы.",
        "kk": "Сәлеметсіз бе{name}. Өзіңізді қалай сезінесіз және белгілер қашан басталды?",
    },
    "neurologist": {
        "en": "Based on your description, you may want to consult a neurologist. Would you like to book a consultation?",
        "ru": "Судя по описанию, вам может помочь консультация невролога. Хотите записаться?",
        "kk": "Сипаттамаңызға қарағанда, невропатологпен кеңескеніңіз жөн болар. Жазылғыңыз келе ме?",
    },
    "cardiologist": {
        "en": "Based on your description, you may want to consult a cardiologist. Would you like to book a consultation?",
        "ru": "Судя по описанию, вам может помочь консультация кардиолога. Хотите записаться?",
        "kk": "Сипаттамаңызға қарағанда, кардиологпен кеңескеніңіз жөн болар. Жазылғыңыз келе ме?",
    },
    "ophthalmologist": {
        "en": "Based on your description, you may want to consult an ophthalmologist. Would you like to book a consultation?",
        "ru": "Судя по описанию, вам может помочь консультация офтальмолога. Хотите записаться?",
        "kk": "Сипаттамаңызға қарағанда, офтальмологпен кеңескеніңіз жөн болар. Жазылғыңыз келе ме?",
    },
    "therapist": {
        "en": "A therapist can review general symptoms and everyday care, and refer you to a specialist if needed. Would you like to book a consultation?",
        "ru": "Терапевт может оценить общие симптомы и при необходимости направить к специалисту. Хотите записаться?",
        "kk": "Терапевт жалпы белгілерді бағалап, қажет болса маманға жібере алады. Жазылғыңыз келе ме?",
    },
    "prepare_questions": {
        "en": "Tell me when your headache started. I can help you organize your symptoms and questions.",
        "ru": "Расскажите, когда началась головная боль. Я помогу упорядочить симптомы и вопросы.",
        "kk": "Бас ауыруы қашан басталғанын айтыңыз. Белгілер мен сұрақтарды реттеуге көмектесемін.",
    },
    "explain_labs": {
        "en": "A complete blood count measures several types of blood cells, including red cells, white cells and platelets. It helps a doctor understand your general health. Your clinician should interpret the results alongside your symptoms and medical history. I can help explain the terminology.",
        "ru": "Общий анализ крови измеряет несколько типов клеток крови: эритроциты, лейкоциты и тромбоциты. Он помогает врачу оценить общее состояние здоровья. Результаты должен интерпретировать ваш врач с учётом симптомов и истории болезни.",
        "kk": "Жалпы қан талдауы қан жасушаларының бірнеше түрін өлшейді: эритроциттер, лейкоциттер және тромбоциттер. Нәтижелерді дәрігеріңіз түсіндіруі керек.",
    },
    "explain_terms": {
        "en": "I can explain medical terms in plain language. Which word or phrase would you like to understand?",
        "ru": "Я могу объяснить медицинские термины простым языком. Какое слово вы хотите понять?",
        "kk": "Медициналық терминдерді қарапайым тілмен түсіндіре аламын. Қай сөзді түсінгіңіз келеді?",
    },
    "explain_prescriptions": {
        "en": "I can explain what is written on a prescription, but I can't change doses or recommend medicines. Please follow your clinician's and pharmacist's instructions.",
        "ru": "Я могу объяснить, что написано в рецепте, но не могу менять дозировки или рекомендовать лекарства. Следуйте указаниям врача и фармацевта.",
        "kk": "Рецептте не жазылғанын түсіндіре аламын, бірақ дозаны өзгерте немесе дәрі ұсына алмаймын.",
    },
    "translate": {
        "en": "Paste the medical text you'd like translated between English, Russian and Kazakh. Translations are for understanding only; confirm details with your clinician.",
        "ru": "Вставьте медицинский текст для перевода между английским, русским и казахским. Перевод носит справочный характер.",
        "kk": "Ағылшын, орыс және қазақ тілдері арасында аударылатын медициналық мәтінді қойыңыз.",
    },
}

_WORD = re.compile(r"\w+", re.UNICODE)


def match_specialty(text: str) -> tuple[str, int]:
    lowered = text.casefold()
    best, best_hits = "therapist", 0
    for slug, keywords in SPECIALTY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best, best_hits = slug, hits
    return best, best_hits


def _loc(key: str, locale: str) -> str:
    table = REPLIES[key]
    return table.get(locale) or table["en"]


class MockAIProvider:
    """Deterministic rule-based responder (no model, no network)."""

    def complete(self, request: AiRequest) -> AiResult:
        if scenario_is("ai_timeout"):
            note_mock("ai")
            raise ProviderTimeout(code="ai_timeout", extra={"provider": "ai"})
        if scenario_is("ai_error"):
            note_mock("ai")
            raise ProviderError(extra={"provider": "ai"})
        note_mock("ai")
        user_text = " ".join(t.content for t in request.turns if t.role == "user")
        locale = request.locale if request.locale in ("en", "ru", "kk") else "en"

        if request.mode != "triage":
            return AiResult(_loc(request.mode, locale), None, "medium", "routine", [])

        if not _WORD.search(user_text):
            name = f", {request.patient_first_name}" if request.patient_first_name else ""
            return AiResult(_loc("greeting", locale).format(name=name), None, "low", "routine", [])

        slug, hits = match_specialty(user_text)
        confidence: Confidence = "high" if hits >= 2 else "medium" if hits == 1 else "low"
        return AiResult(
            reply_text=_loc(slug, locale),
            recommended_specialty=slug,
            confidence_band=confidence,
            urgency="routine",
            suggested_actions=["book_consultation", "see_recommended_specialists"],
        )

    def stream(self, request: AiRequest) -> Iterator[str]:
        result = self.complete(request)
        words = result.reply_text.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
