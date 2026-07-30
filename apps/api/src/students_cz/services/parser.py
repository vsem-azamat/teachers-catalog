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


def is_whole_word(haystack: str, needle: str) -> bool:
    """Does `needle` appear in `haystack` as a word of its own?

    For keywords that are words rather than stems. "визу" is the accusative of
    "виза" and also the first four letters of "визуализация", and
    `starts_a_word` deliberately lets a match run into the middle of a word —
    which read "визуализация данных" as a residence-permit question.
    """
    return tokenise(needle) in haystack


def starts_a_word(haystack: str, needle: str) -> bool:
    """Does `needle` begin at a word boundary in `haystack`?

    The keywords are stems, not words — "нострифик" has to reach
    "нострификация", "написа" has to reach "написать". So the match may run
    into the middle of a word, but it may not *start* there: otherwise "osp"
    fires on "gospodarka" and every short keyword becomes a trap.
    """
    return tokenise(needle).rstrip() in haystack


class Word(str):
    """A keyword that has to match a whole word rather than a stem.

    Every other entry below may run into the middle of a word, which is what
    lets "нострифик" reach "нострификации". For a short ordinary word that is a
    trap: "визу" is the accusative of "виза" and the first four letters of
    "визуализация". Written here rather than in a parallel set of strings, so
    adding a form cannot quietly make it a stem again.
    """

    __slots__ = ()


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
    # Above the study kinds, unlike the rest of the non-study block below.
    # "присяжный перевод диплома" was answered as thesis writing on the strength
    # of the word "диплом", and "перевод аттестата" as nostrification, and the
    # only thing that fixes those is order.
    "translation": (
        # Stems for the noun in each language, because a multi-word keyword
        # tolerates inflection only on its last word — so "присяжного перевода
        # диплома", the commonest way to ask, reached none of the phrases that
        # used to be listed here and fell through to thesis writing on "диплом".
        # No subject in the catalog is named after translation, in any language,
        # so the stems cost nothing a phrase would have saved.
        "перевод",
        "переклад",
        "preklad",
        # The English four are what make this block reach past documents:
        # "translation studies tutor" reads as a document translation. Taken
        # deliberately — a foreign student in Czechia asking about "translation"
        # wants a stamped paper far more often than a seminar on translation
        # theory, and that field is not in the catalog at all.
        Word("translation"),
        Word("translations"),
        "translate",
        "translating",
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
    # Help that is not about studying. Last, and after tutoring: an incidental
    # mention of where somebody lives must not outrank an explicit study word,
    # and "нужен репетитор, живу в общежитии" did become housing when these sat
    # first. They still come before the weak verbs below, which is what makes
    # "помочь снять квартиру" housing rather than tutoring.
    "insurance": (
        "страховк",
        # Words, not stems: the genitive "страхования" belongs to a subject —
        # "экономика страхования" — and "pojistna matematika" is actuarial
        # mathematics, which the stem "pojist" read as somebody wanting a policy.
        Word("страхование"),
        Word("страхування"),
        "pojisten",
        "pojistk",
        "insurance",
    ),
    "bank_letter": (
        "справка из банк",
        "справку из банк",
        "выписка со счет",
        "выписку со счет",
        "из банка",
        "довідка з банк",
        "довідку з банк",
        "з банку",
        "vypis z ban",
        "vypis z uct",
        "zustatek",
        "potvrzeni z ban",
        "potvrzeni o vedeni",
        "zustatku",
        "bank statement",
        "bank letter",
        "proof of funds",
    ),
    "residence": (
        "внж",
        # A stem, so the genitive "вида на жительство" is reached too.
        "жительств",
        # Words for the visa, and a stem for the stay. A multi-word keyword
        # tolerates inflection only on its last word, so the three phrases that
        # used to be here reached none of "prodlouzeni dlouhodobeho pobytu" —
        # the standard Czech phrasing — which "pobyt" does.
        Word("виза"),
        Word("визы"),
        Word("визу"),
        Word("визой"),
        Word("візу"),
        Word("візи"),
        Word("віза"),
        "посвідк",
        Word("vizum"),
        Word("viza"),
        "pobyt",
        "residence permit",
        Word("visa"),
        Word("visas"),
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
        "na koleji",
        "housing",
        "dormitory",
    ),
}

# The kinds of help in the `life` group — the ones that are not about studying
# and carry no subject at all. Not "requires_subject is false", which is also
# true of exam help and nostrification and would be the wrong set: it is the
# group. Written out because the parser reads no tables, and pinned to the seed
# by test_subjectless_is_exactly_the_life_group so a sixth one cannot be added
# without this list noticing.
SUBJECTLESS = frozenset(
    {"insurance", "bank_letter", "translation", "residence", "housing"}
)

# The four of those whose keywords are ordinary words that turn up as asides —
# where somebody lives, what they are insured for. A subject named beside one of
# these is the question, and the aside is not. `translation` is deliberately not
# here: "присяжный перевод диплома" is not something anybody writes in passing,
# so when it appears the document is the request and a subject beside it is not
# one this kind of help can be filtered by.
ASIDES = SUBJECTLESS - {"translation"}

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

    result.service_type, keyword = _match_service(norm)

    subjects = await find_subjects(session, text, lang, limit=4)
    # When the words naming the kind of help were the whole query, there is no
    # subject in it to find, and a trigram guess is the scorer answering a
    # question nobody asked: "bank statement" came back as Probability and
    # Statistics at 0.61. A synonym hit survives, because that is not a guess —
    # "курсовая" and "нострификация" are curated names for real subjects, and
    # dropping them would lose a certainty to protect against a maybe.
    if keyword and not _without(norm, keyword):
        subjects = [match for match in subjects if _is_named(match)]

    # A kind of help that never carries a subject cannot be the answer to a
    # query that *names* one. `catalog.search` ANDs the two, and no offer in the
    # non-study group has a subject, so the pair matches nobody: "нужен матан,
    # живу в общежитии" is a question about calculus with an aside in it, and
    # reading it as housing turned a list of tutors into an empty screen. Read
    # again as if those kinds did not exist.
    #
    # Which of the two gives way depends on whether the subject was named, and on
    # whether the kind of help could have been an aside. A named subject beside
    # an aside wins: read the kind of help again as if the
    # non-study ones did not exist. A trigram score is a guess, and a guess
    # cannot narrow a kind of help that has no subjects to narrow by — so the
    # guess goes instead. Keeping both was a guaranteed empty screen, and
    # keeping the subject over the service undid the reason translation sits
    # above the study kinds: "присяжный перевод диплома" scores «Академическое
    # письмо» at 0.55.
    if subjects and result.service_type in SUBJECTLESS:
        if _is_named(subjects[0]) and result.service_type in ASIDES:
            result.service_type, _ = _match_service(norm, ignore=SUBJECTLESS)
        else:
            subjects = []

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


def _match_service(
    norm: str, *, ignore: frozenset[str] = frozenset()
) -> tuple[str | None, str | None]:
    """The kind of help, and the keyword that decided it.

    First keyword wins, and the dictionary is ordered by specificity. "помощь на
    экзамене" must not be read as plain exam preparation, so exam_live_help is
    checked before exam_prep and generic tutoring last. Weak verbs are
    considered only after every specific rule has passed.

    The keyword comes back so the caller can ask whether anything else was in the
    query at all. A weak verb yields none: "помоги" names no kind of help by
    itself, so there is nothing to say it took the whole sentence.

    `ignore` re-reads the same text as if some kinds did not exist — see
    SUBJECTLESS at the call site.
    """
    tokens = tokenise(norm)
    for code, keywords in SERVICE_KEYWORDS.items():
        if code in ignore:
            continue
        for keyword in keywords:
            match = is_whole_word if isinstance(keyword, Word) else starts_a_word
            if match(tokens, keyword):
                return code, keyword

    if any(starts_a_word(tokens, verb) for verb in WEAK_HELP):
        if any(starts_a_word(tokens, word) for word in EXAM_MENTION):
            return None, None  # an exam is mentioned but not placed in time
        return "tutoring", None
    return None, None


def _is_named(match: Match) -> bool:
    """Did the query name this subject, rather than score against it?

    A 1.0 is either a curated synonym or a name the query reproduced exactly.
    Everything below it is the trigram scorer's opinion — the external-code
    branch stops at 0.95 and the synonym-similarity branch at 0.92, so the line
    is exactly where certainty is.

    `matched_on == "synonym"` was the first spelling of this and it was too
    narrow: "Чешский язык B1, нужна виза" names the subject in full, scores 1.0,
    and reports `name` — so the subject the person typed out was thrown away as
    a guess.
    """
    return match.score >= 1.0


def _without(norm: str, keyword: str) -> str:
    """`norm` minus the words the keyword touched.

    Whole words, not the keyword's characters: the keywords are stems, so
    removing "нострифик" from "нострификация" would leave "ация", and the caller
    is asking whether anything is left — a fragment would answer yes.
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
