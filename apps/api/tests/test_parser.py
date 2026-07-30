from datetime import date

import pytest

from students_cz.services.lookup import normalise
from students_cz.services.parser import (
    _match_budget,
    _match_deadline,
    _match_service,
    parse,
)

TODAY = date(2026, 1, 20)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("нужна нострификация аттестата", "nostrification"),
        ("надо написать курсовую до марта", "writing"),
        ("prijimacky na cvut", "entrance_prep"),
        ("помощь на экзамене 14 февраля", "exam_live_help"),
        ("ищу репетитора по матану", "tutoring"),
        ("треба підтягнути фізику", "tutoring"),
        ("pomoc u zkousky", "exam_live_help"),
        ("матан", None),
        # A weak verb alone means tutoring...
        ("помоги с матаном", "tutoring"),
        # ...but not when an exam is in the picture and its timing is not.
        ("нужна помощь, экзамен 14 февраля", None),
    ],
)
def test_service_keywords(text, expected):
    assert _match_service(normalise(text)) == expected


def test_keyword_must_start_a_word():
    """ "osp" is a Scio test; it is also inside "gospodarka"."""
    assert _match_service(normalise("gospodarka a osnovy")) is None
    assert _match_service(normalise("готовлюсь к osp")) == "entrance_prep"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("экзамен 14 февраля", date(2026, 2, 14)),
        ("zkouska 3. brezna", date(2026, 3, 3)),
        ("до 14.02", date(2026, 2, 14)),
        ("сдать 01.06.2027", date(2027, 6, 1)),
        ("exam on 5 june", date(2026, 6, 5)),
        ("без даты", None),
        ("32 февраля", None),
    ],
)
def test_deadlines(text, expected):
    assert _match_deadline(normalise(text), TODAY) == expected


def test_a_past_date_means_next_year():
    """Typed in December, "14 February" is not seven weeks ago."""
    assert _match_deadline(normalise("14 февраля"), date(2026, 12, 1)) == date(
        2027, 2, 14
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("до 700", 700.0),
        ("бюджет 500 kč", 500.0),
        ("max 1200 czk", 1200.0),
        ("экзамен 14 февраля", None),
        ("физика 2", None),
        ("до 5", None),
    ],
)
def test_budget_only_when_marked_as_money(text, expected):
    assert _match_budget(normalise(text)) == expected


@pytest.mark.asyncio
async def test_full_parse_of_a_realistic_query(session):
    parsed = await parse(
        session,
        "нужен человек помочь с матаном на ČVUT, экзамен 14 февраля, до 700 kč",
        "ru",
        today=TODAY,
    )
    assert parsed.subject is not None
    assert parsed.subject.label == "Математический анализ"
    assert parsed.deadline == date(2026, 2, 14)
    assert parsed.budget_max == 700.0
    assert parsed.unmatched is False
    # Mentioning an exam does not say whether the help is wanted before it or
    # during it. Guessing here would be worse than asking, and asking is what
    # the clarify step is for.
    assert parsed.service_type is None


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_inflected_slang_still_resolves(session):
    """Russian inflects; students type "с матаном", not "матан"."""
    parsed = await parse(session, "помоги с матаном", "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.label == "Математический анализ"
    assert parsed.service_type == "tutoring"


@pytest.mark.asyncio
async def test_saying_when_removes_the_ambiguity(session):
    parsed = await parse(session, "нужна помощь на экзамене по матану", "ru", today=TODAY)
    assert parsed.service_type == "exam_live_help"


async def test_unmatched_is_reported_not_guessed(session):
    parsed = await parse(session, "asdfgh qwerty", "ru", today=TODAY)
    assert parsed.unmatched is True
    assert parsed.subject is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Help that is not about studying. Offerable since PR #29 and, until
        # these keywords existed, unfindable in words — a listing nobody could
        # reach. One phrasing per language per kind, because the catalog is read
        # in four languages and the parser is not told which one was typed.
        ("нужна страховка для визы", "insurance"),
        ("pojisteni na rok", "insurance"),
        ("insurance for a visa", "insurance"),
        ("страховка на рік", "insurance"),
        ("справка из банка", "bank_letter"),
        ("vypis z banky", "bank_letter"),
        ("bank statement", "bank_letter"),
        ("довідка з банку", "bank_letter"),
        ("перевод документов с печатью", "translation"),
        ("soudni preklad", "translation"),
        ("sworn translation", "translation"),
        ("переклад документів", "translation"),
        ("продлить ВНЖ", "residence"),
        ("prodlouzeni pobytu", "residence"),
        ("residence permit", "residence"),
        ("продовження ВНЖ", "residence"),
        ("жильё в Праге", "housing"),
        ("hledam bydleni", "housing"),
        ("looking for housing", "housing"),
        ("житло у Празі", "housing"),
    ],
)
def test_help_that_is_not_about_studying_is_recognised(text, expected):
    assert _match_service(normalise(text)) == expected


@pytest.mark.asyncio
async def test_a_short_faculty_name_is_not_found_inside_a_word(session):
    """`FI` is a faculty. It is also the first two letters of "физике".

    Trigram similarity scored that at 0.67 — above the threshold — so a query
    about physics came back naming a faculty nobody had mentioned.
    """
    parsed = await parse(session, "репетитор по физике", "ru", today=TODAY)
    assert parsed.institution is None


@pytest.mark.asyncio
async def test_a_named_faculty_is_still_found(session):
    """The rule above must not cost us the faculty when it really is named."""
    parsed = await parse(session, "матан на ČVUT FIT", "ru", today=TODAY)
    assert parsed.institution is not None


@pytest.mark.asyncio
async def test_the_subject_is_read_from_what_the_service_left(session):
    """The words naming the kind of help are not part of the subject.

    They also carry trigrams of their own: with them in the query, «Чешский язык
    B1» scored 0.59 against a question about physics while «Физика 1» sat at
    0.56, so the screen answered confidently about the wrong subject.
    """
    parsed = await parse(session, "помощь на экзамене по физике", "ru", today=TODAY)
    assert parsed.service_type == "exam_live_help"
    assert parsed.subject is not None
    assert parsed.subject.label.startswith("Физика")


@pytest.mark.asyncio
async def test_a_word_naming_both_the_service_and_the_subject_survives(session):
    """ "нострификация аттестата" names the kind of help in one word and the
    subject in the other, and the stem taken out is inside the first.

    Whole words, so what is left is "аттестата" rather than the fragment "ация".
    """
    parsed = await parse(session, "нострификация аттестата", "ru", today=TODAY)
    assert parsed.service_type == "nostrification"
    assert parsed.subject is not None
    assert parsed.subject.label == "Нострификационные экзамены"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["bank statement", "нострификация"])
async def test_no_subject_is_invented_when_the_service_was_the_whole_query(session, text):
    """Nothing is left to name a subject, so none is claimed.

    "bank statement" used to come back as Probability and Statistics at 0.61 —
    a filter narrower than the question, on a subject nobody had named.
    """
    parsed = await parse(session, text, "en", today=TODAY)
    assert parsed.service_type is not None
    assert parsed.subject is None
    assert parsed.unmatched is False
