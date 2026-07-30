"""Free text in, structured query out.

This is the piece that lets the interface have one input field instead of a
tree of categories. "нужен человек помочь с матаном на ČVUT, экзамен 14 февраля"
has to become a subject, an institution, a kind of help and a date.

Deliberately rule-based for now. The rules are cheap, they run in milliseconds,
they never invent a subject that does not exist, and every failure is visible in
`search_queries`. A model can replace `parse()` later without anything upstream
changing — the seam is the `ParsedQuery` it returns, not how it got there.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.services.lookup import Match, find_institutions, find_subjects, normalise

_NON_WORD = re.compile(r"[^a-z0-9\u0400-\u04ff]+")


def tokenise(value: str) -> str:
    """Reduce text to " token token " with single spaces."""
    return f" {_NON_WORD.sub(' ', normalise(value)).strip()} "


def starts_a_word(haystack: str, needle: str) -> bool:
    """Does `needle` begin at a word boundary in `haystack`?

    The keywords are stems, not words — "нострифик" has to reach
    "нострификация", "написа" has to reach "написать". So the match may run
    into the middle of a word, but it may not *start* there: otherwise "osp"
    fires on "gospodarka" and every short keyword becomes a trap.
    """
    return tokenise(needle).rstrip() in haystack


# Keywords that name a kind of help, across the four interface languages plus
# the transliterations students actually type. These are matching rules, not
# display text, so they live in code rather than in the translation catalogue.
SERVICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "exam_live_help": (
        "на экзамене",
        "u zkousky",
        "во время экзамена",
        "в день экзамена",
        "подстрахов",
        "помощь на экза",
        "na zkousce",
        "behem zkousky",
        "during the exam",
        "на іспиті",
        "під час іспиту",
        "spisyvan",
        "списыв",
    ),
    "exam_prep": (
        "к экзамену",
        "подготовиться к экза",
        "сдать экзамен",
        "зачет",
        "zapocet",
        "na zkousku",
        "priprava na zkousku",
        "exam prep",
        "до іспиту",
        "перескладання",
        "пересдач",
        "opravny termin",
    ),
    "entrance_prep": (
        "вступительн",
        "поступлен",
        "prijimack",
        "přijímačk",
        "prijimaci",
        "entrance",
        "вступн",
        "tsp",
        "osp",
        "nastupni",
    ),
    "nostrification": (
        "нострифик",
        "nostrifik",
        "аттестат",
        "признание диплома",
        "uznani",
        "нострифік",
        "атестат",
    ),
    # Help that is not about studying. These come before the study kinds
    # because they are unambiguous: nobody writing "страховка" means a tutor,
    # while the weak verbs at the bottom would happily read "помочь снять
    # квартиру" as tutoring — and did.
    "insurance": (
        "страховк",
        "страхован",
        "страхуван",
        "pojisten",
        "pojiste",
        "insurance",
        "vzp",
        "pvzp",
    ),
    "bank_letter": (
        "справка из банк",
        "справку из банк",
        "выписка со счет",
        "выписку со счет",
        "из банка",
        "довидка з банк",
        "довидку з банк",
        "з банку",
        "vypis z ban",
        "potvrzeni z ban",
        "potvrzeni o vedeni",
        "bank statement",
        "bank letter",
        "proof of funds",
    ),
    "translation": (
        "перевод документ",
        "переводом документ",
        "судебный перевод",
        "перевод с печат",
        "присяжный перевод",
        "переклад документ",
        "судовий переклад",
        "soudni preklad",
        "uredni preklad",
        "preklad dokument",
        "s razitkem",
        "sworn translation",
        "certified translation",
        "official translation",
    ),
    "residence": (
        # "внж" and "вnж" are both typed; the transliteration is handled by the
        # normaliser, not by listing every spelling.
        "внж",
        "вид на жительство",
        "долгосрочная виза",
        "продлить визу",
        "продлить внж",
        "продовження внж",
        "посвидка на проживанн",
        "pobytov",
        "prodlouzeni pobytu",
        "povoleni k pobytu",
        "dlouhodoby pobyt",
        "residence permit",
        "long term visa",
        "long-term visa",
    ),
    "housing": (
        "жиль",
        "квартир",
        "общежит",
        "переезд",
        "житло",
        "гуртожит",
        "bydlen",
        "ubytovan",
        "kolej",
        "housing",
        "accommodation",
        "dormitory",
        "flatshare",
    ),
    "writing": (
        "написать",
        "написа",
        "курсов",
        "семестров",
        "диплом",
        "бакалавр",
        "реферат",
        "эссе",
        "seminarn",
        "bakalars",
        "diplomov",
        "napsat",
        "write",
        "essay",
        "thesis",
        "написати",
        "курсову",
    ),
    "tutoring": (
        "репетитор",
        "объяснить",
        "разобрать",
        "подтянуть",
        "позанимат",
        "doucovani",
        "doucit",
        "vysvetlit",
        "tutor",
        "explain",
        "репетитора",
        "пояснити",
        "підтягнути",
        *(),  # weak verbs follow, see WEAK_HELP
    ),
}

# "помочь с X" is the commonest phrasing there is, but on its own it says
# nothing about *which* kind of help. It counts as tutoring only when the text
# gives no other clue — see _match_service.
WEAK_HELP: tuple[str, ...] = ("помо", "pomo", "help", "допомо", "нужен", "потрібн")

# Words that put an exam in the picture without saying whether the help is
# wanted before it or during it. When one of these appears next to nothing but
# a weak verb, the honest move is to ask rather than to pick.
EXAM_MENTION: tuple[str, ...] = (
    "экзамен",
    "экза",
    "zkous",
    "іспит",
    "exam",
    "termin",
)

# Month names, unaccented and lowercased, in the order the client will have
# typed them. Czech has both nominative and genitive forms in circulation.
MONTHS: dict[str, int] = {}
for _idx, _names in enumerate(
    (
        ("янв", "leden", "ledna", "jan", "січ"),
        ("фев", "unor", "unora", "feb", "лют"),
        ("мар", "brezen", "brezna", "mar", "берез"),
        ("апр", "duben", "dubna", "apr", "квіт"),
        ("мая", "мае", "май", "kveten", "kvetna", "may", "трав"),
        ("июн", "cerven", "cervna", "jun", "черв"),
        ("июл", "cervenec", "cervence", "jul", "лип"),
        ("авг", "srpen", "srpna", "aug", "серп"),
        ("сен", "zari", "sep", "верес"),
        ("окт", "rijen", "rijna", "oct", "жовт"),
        ("ноя", "listopad", "listopadu", "nov", "листоп"),
        ("дек", "prosinec", "prosince", "dec", "груд"),
    ),
    start=1,
):
    for _name in _names:
        MONTHS[_name] = _idx

# Czech writes an ordinal day with a full stop: "3. brezna".
_DAY_MONTH_WORD = re.compile(r"\b(\d{1,2})[\s.]*([a-zа-яіїєґ]{3,10})")
_DAY_MONTH_NUM = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_BUDGET = re.compile(
    r"(?:до|max|maximalne|not more than|не более|не більше)?\s*"
    r"(\d{2,5})\s*(?:kc|kč|czk|крон|korun)?\b"
)


@dataclass
class ParsedQuery:
    raw: str
    subject: Match | None = None
    institution: Match | None = None
    service_type: str | None = None
    deadline: date | None = None
    budget_max: float | None = None
    unmatched: bool = False
    alternatives: dict[str, list[Match]] = field(default_factory=dict)


async def parse(
    session: AsyncSession, text: str, lang: str, *, today: date | None = None
) -> ParsedQuery:
    norm = normalise(text)
    result = ParsedQuery(raw=text)

    # The kind of help first, because the words that name it are not part of the
    # subject and they bring trigrams of their own: with "помощь на экзамене"
    # still in the query, «Чешский язык B1» scored 0.59 against a question about
    # physics while «Физика 1» sat at 0.56.
    result.service_type, matched_on = _service_match(norm)
    asked = _without(norm, matched_on) if matched_on else norm

    subjects: list[Match] = []
    if asked:
        subjects = await find_subjects(session, asked, lang, limit=4)
        # The remainder is preferred, not trusted: a query can name a subject in
        # words the kind of help took with it, and the trigram scorer will
        # happily find something in whatever is left.
        if not subjects and asked != norm:
            subjects = await find_subjects(session, norm, lang, limit=4)
    # Nothing is left when the kind of help was the whole query — "bank
    # statement", "нострификация". There is no subject in it to find, and
    # looking anyway is how "bank statement" came back as Probability and
    # Statistics: a filter narrower than the question, on a subject nobody named.
    institutions = await find_institutions(session, text, lang, limit=3)

    if subjects:
        result.subject = subjects[0]
        # Keep the runners-up so the chip can offer "did you mean" instead of
        # silently committing to a 0.52-confidence guess.
        result.alternatives["subject"] = subjects[1:]
    if institutions:
        result.institution = institutions[0]
        result.alternatives["institution"] = institutions[1:]

    result.deadline = _match_deadline(norm, today or date.today())
    result.budget_max = _match_budget(norm)

    result.unmatched = not any((result.subject, result.institution, result.service_type))
    return result


def _match_service(norm: str) -> str | None:
    """Which kind of help the text names, if any."""
    return _service_match(norm)[0]


def _service_match(norm: str) -> tuple[str | None, str | None]:
    """The kind of help, and the keyword that decided it.

    First keyword wins, and the dictionary is ordered by specificity. "помощь на
    экзамене" must not be read as plain exam preparation, so exam_live_help is
    checked before exam_prep and generic tutoring last. Weak verbs are
    considered only after every specific rule has passed.

    The keyword comes back because the caller takes it out of the query before
    looking for a subject. A weak verb yields no keyword: "помоги" says nothing
    about which kind of help, so there is nothing to remove that would sharpen
    anything.
    """
    tokens = tokenise(norm)
    for code, keywords in SERVICE_KEYWORDS.items():
        for keyword in keywords:
            if starts_a_word(tokens, keyword):
                return code, keyword

    if any(starts_a_word(tokens, verb) for verb in WEAK_HELP):
        if any(starts_a_word(tokens, word) for word in EXAM_MENTION):
            return None, None  # an exam is mentioned but not placed in time
        return "tutoring", None
    return None, None


def _without(norm: str, keyword: str) -> str:
    """`norm` minus the words the keyword touched.

    Whole words, not the keyword's characters: the keywords are stems, so
    removing "нострифик" from "нострификация" would leave "ация" and hand the
    subject lookup a fragment to score against.
    """
    tokens = tokenise(norm)
    needle = tokenise(keyword).rstrip()
    at = tokens.find(needle)
    if at < 0:
        return norm
    end = tokens.find(" ", at + len(needle))
    return (tokens[:at] + (tokens[end:] if end >= 0 else " ")).strip()


def _match_deadline(norm: str, today: date) -> date | None:
    match = _DAY_MONTH_WORD.search(norm)
    if match:
        day, word = int(match.group(1)), match.group(2)
        month = next((m for name, m in MONTHS.items() if word.startswith(name)), None)
        if month and 1 <= day <= 31:
            return _next_occurrence(day, month, today)

    match = _DAY_MONTH_NUM.search(norm)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = match.group(3)
        if 1 <= day <= 31 and 1 <= month <= 12:
            if year:
                y = int(year)
                return _safe_date(y + 2000 if y < 100 else y, month, day)
            return _next_occurrence(day, month, today)
    return None


def _next_occurrence(day: int, month: int, today: date) -> date | None:
    """Bare "14 February" means the next one, not one in the past.

    Exams cluster in January–February and May–June, so a date typed in
    December almost always means next year.
    """
    candidate = _safe_date(today.year, month, day)
    if candidate is None:
        return None
    if candidate < today:
        return _safe_date(today.year + 1, month, day)
    return candidate


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _match_budget(norm: str) -> float | None:
    """Only read a number as money when it is marked as money.

    Otherwise "14 февраля" becomes a budget of 14 crowns, and "физика 2"
    becomes a budget of 2.
    """
    for match in _BUDGET.finditer(norm):
        whole = match.group(0)
        has_currency = re.search(r"kc|kč|czk|крон|korun", whole)
        has_limit_word = re.match(
            r"\s*(до|max|maximalne|not more than|не более|не більше)", whole
        )
        if has_currency or has_limit_word:
            value = float(match.group(1))
            if 50 <= value <= 100_000:
                return value
    return None
