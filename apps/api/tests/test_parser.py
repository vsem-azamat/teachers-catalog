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
