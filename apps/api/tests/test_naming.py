"""The rule that turns a reference row into a name.

Four modules read names off the taxonomy and every one of them used to reach
into `catalog` for a private helper to do it. Now that the rule has a home it
gets a test of its own — the fallbacks in it are the difference between a
Ukrainian speaker seeing the Czech name of their faculty and seeing a blank
row, and nothing above this level would notice which.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.db.models import Institution, InstitutionI18n, Subject, SubjectI18n
from konnekt.db.models.enums import UiLang
from konnekt.services.naming import names_by_id, rows_by_id, short_form, translated

pytestmark = pytest.mark.asyncio


def subject_named(**by_lang: str) -> Subject:
    # `path` is the materialised tree path and is not nullable; the seeder
    # fills it after the flush that assigns an id. Nothing here reads it.
    row = Subject(slug="x", kind="leaf", path="")
    row.names = [
        SubjectI18n(lang=UiLang(lang), name=name) for lang, name in by_lang.items()
    ]
    return row


def institution_named(name: str, short: str | None) -> Institution:
    row = Institution(code="x")
    row.names = [InstitutionI18n(lang=UiLang.CS, name=name, short_name=short)]
    return row


async def test_the_asked_language_wins() -> None:
    row = subject_named(cs="Matematická analýza", ru="Матанализ")

    assert translated(row, UiLang.RU) == "Матанализ"


async def test_a_missing_translation_falls_back_to_any_other() -> None:
    """Not to nothing. A Czech name is a worse answer than a Ukrainian one and
    a far better answer than an empty row."""
    row = subject_named(cs="Matematická analýza")

    assert translated(row, UiLang.UK) == "Matematická analýza"


async def test_a_row_with_no_names_at_all_says_so() -> None:
    assert translated(subject_named(), UiLang.CS) is None


async def test_an_empty_string_is_not_a_translation() -> None:
    """The fallback has to keep looking past it, or a blank row in the asked
    language hides a real name in another one."""
    row = subject_named(uk="", cs="Matematická analýza")

    assert translated(row, UiLang.UK) == "Matematická analýza"


async def test_another_attribute_follows_the_same_rule() -> None:
    row = institution_named("České vysoké učení technické", "ČVUT")

    assert translated(row, UiLang.RU, "short_name") == "ČVUT"


async def test_the_short_form_is_the_short_name_when_there_is_one() -> None:
    row = institution_named("České vysoké učení technické", "ČVUT")

    assert short_form(row, UiLang.CS) == "ČVUT"


async def test_the_short_form_falls_back_to_the_full_name() -> None:
    """A chip with nothing in it is worse than a chip that is too long."""
    row = institution_named("Slezská univerzita v Opavě", None)

    assert short_form(row, UiLang.CS) == "Slezská univerzita v Opavě"


async def test_rows_by_id_ignores_the_ids_that_are_none(session: AsyncSession) -> None:
    """An offer without a subject is ordinary, not an error, and asking the
    database about `None` is a query nobody meant to write."""
    subject = subject_named(cs="Fyzika")
    session.add(subject)
    await session.flush()

    found = await rows_by_id(session, Subject, [subject.id, None, None])

    assert list(found) == [subject.id]


async def test_rows_by_id_asks_nothing_when_there_is_nothing_to_ask(
    session: AsyncSession,
) -> None:
    assert await rows_by_id(session, Subject, [None]) == {}


async def test_names_by_id_renders_what_rows_by_id_finds(
    session: AsyncSession,
) -> None:
    subject = subject_named(cs="Fyzika", ru="Физика")
    session.add(subject)
    await session.flush()

    assert await names_by_id(session, Subject, [subject.id], UiLang.RU) == {
        subject.id: "Физика"
    }


async def test_names_by_id_answers_with_a_string_for_an_untranslated_row(
    session: AsyncSession,
) -> None:
    """Its callers put the value straight into a field that cannot be null."""
    subject = subject_named()
    session.add(subject)
    await session.flush()

    assert await names_by_id(session, Subject, [subject.id], UiLang.CS) == {
        subject.id: ""
    }
