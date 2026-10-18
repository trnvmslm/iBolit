"""Emergency 103 copy (English text; ru/kk drafts need native review)."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from ibolit.core.i18n import localize

COPY: dict[str, dict[str, str]] = {
    "title": {"en": "Need an ambulance?", "ru": "Нужна скорая помощь?", "kk": "Жедел жәрдем керек пе?"},
    "body": {
        "en": "{number} is Kazakhstan's ambulance emergency number. Call for a serious or life-threatening medical emergency.",
        "ru": "{number} — номер скорой медицинской помощи в Казахстане. Звоните при серьёзном или угрожающем жизни состоянии.",
        "kk": "{number} — Қазақстандағы жедел медициналық жәрдем нөмірі. Ауыр немесе өмірге қауіпті жағдайда қоңырау шалыңыз.",
    },
    "call_label": {"en": "Call {number} now", "ru": "Позвонить {number}", "kk": "{number} нөміріне қоңырау шалу"},
    "dialer_note": {
        "en": "Calling opens your phone dialer. Tell the dispatcher your location and what happened.",
        "ru": "Звонок откроет номеронабиратель. Сообщите диспетчеру, где вы находитесь и что произошло.",
        "kk": "Қоңырау телефон тергішін ашады. Диспетчерге қайда екеніңізді және не болғанын айтыңыз.",
    },
    "location_note": {
        "en": "Confirm your actual location with the dispatcher.",
        "ru": "Уточните своё фактическое местоположение у диспетчера.",
        "kk": "Нақты орналасқан жеріңізді диспетчерге растаңыз.",
    },
    "home_banner": {
        "en": "Sudden severe headache, weakness or fainting? Call Emergency {number} now.",
        "ru": "Внезапная сильная головная боль, слабость или обморок? Срочно звоните {number}.",
        "kk": "Кенеттен қатты бас ауыруы, әлсіздік немесе талу? Дереу {number} нөміріне қоңырау шалыңыз.",
    },
    "ai_banner": {
        "en": "Urgent symptoms? Don't wait for AI. Call {number}.",
        "ru": "Срочные симптомы? Не ждите ИИ. Звоните {number}.",
        "kk": "Шұғыл белгілер ме? ЖИ-ді күтпеңіз. {number} нөміріне қоңырау шалыңыз.",
    },
}


def text(key: str) -> str:
    return localize(COPY[key]).format(number=settings.EMERGENCY_NUMBER)


def emergency_payload() -> dict[str, Any]:
    number = settings.EMERGENCY_NUMBER
    return {
        "number": number,
        "dial_uri": f"tel:{number}",
        "title": text("title"),
        "body": text("body"),
        "call_label": text("call_label"),
        "dialer_note": text("dialer_note"),
        "location_note": text("location_note"),
        "home_banner": text("home_banner"),
        "ai_banner": text("ai_banner"),
    }
