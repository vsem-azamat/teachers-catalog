"""Fuzzy lookup against the seeded reference data."""

import pytest

from students_cz.services.lookup import find_subjects, mixes_scripts, normalise

pytestmark = pytest.mark.asyncio  # every async test here; the one sync test opts out


@pytest.mark.parametrize(
    ("query", "expect_slug"),
    [
        ("матан", "matematicka-analyza"),
        ("matan", "matematicka-analyza"),
        ("mat analiza", "matematicka-analyza"),
        ("линал", "linearni-algebra"),
        ("терех", "termomechanika"),
        ("сопромат", "pruznost-a-pevnost"),
        ("нужен репетитор по тфкп", "komplexni-analyza"),
        ("микра вше", "mikroekonomie"),
        ("prijimacky cvut", "prijimacky-technicke-vs"),
        ("чешский для поступления", "cestina-b2"),
    ],
)
async def test_finds_the_right_subject(session, query, expect_slug):
    from sqlalchemy import select

    from students_cz.db.models import Subject

    matches = await find_subjects(session, query, "ru", limit=3)
    assert matches, f"{query!r} matched nothing"

    subject = await session.scalar(select(Subject).where(Subject.id == matches[0].id))
    assert subject is not None
    assert subject.slug == expect_slug, (
        f"{query!r} -> {subject.slug} (score {matches[0].score:.2f}), "
        f"expected {expect_slug}"
    )


async def test_synonyms_respect_word_boundaries(session):
    """Regression: "TIN" is a substring of "čeština".

    Before synonyms were matched on word boundaries, "cestina b2 pro
    nostrifikaci" resolved to theoretical computer science with a confidence
    of 1.00, because the synonym "TIN" sits inside the word "cestina".
    """
    from sqlalchemy import select

    from students_cz.db.models import Subject

    matches = await find_subjects(session, "cestina b2 pro nostrifikaci", "cs", limit=3)
    assert matches

    slugs = []
    for match in matches:
        subject = await session.scalar(select(Subject).where(Subject.id == match.id))
        slugs.append(subject.slug)

    assert "teoreticka-informatika" not in slugs
    assert slugs[0].startswith("cestina")


async def test_gibberish_matches_nothing(session):
    assert await find_subjects(session, "qwertyuiop zxcvbnm", "ru") == []


async def test_score_is_certain_for_synonyms(session):
    [match] = await find_subjects(session, "матан", "ru", limit=1)
    assert match.score == pytest.approx(1.0)
    assert match.matched_on == "synonym"


async def test_label_follows_the_requested_language(session):
    [ru] = await find_subjects(session, "матан", "ru", limit=1)
    [cs] = await find_subjects(session, "матан", "cs", limit=1)
    assert ru.id == cs.id
    assert ru.label == "Математический анализ"
    assert cs.label == "Matematická analýza"


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_normalise_matches_what_postgres_does():
    assert normalise("Přijímačky") == "prijimacky"
    assert normalise("ČVUT") == "cvut"
    assert normalise("  Matematická Analýza ") == "matematicka analyza"
    # Cyrillic keeps its marks — unaccent does not decompose й into и, and
    # doing so in Python turned "чешский" into "чешскии" and matched nothing.
    assert normalise("Чешский") == "чешский"
    assert normalise("їжак") == "їжак"
    # ...except ё, which Postgres does fold.
    assert normalise("ёлка") == "елка"


@pytest.mark.parametrize(
    ("query", "expect_code"),
    [
        ("prijimacky cvut", "cvut"),
        ("нужен матан на ЧВУТ", "cvut"),
        ("микра на вше", "vse"),
        ("сдаю на цвут", "cvut"),
        ("муни tsp", "muni"),
        ("matematika na MFF", "uk_mff"),
    ],
)
async def test_finds_institutions_in_either_script(session, query, expect_code):
    """Russian speakers write Czech acronyms in Cyrillic: "чвут", "вше"."""
    from sqlalchemy import select

    from students_cz.db.models import Institution
    from students_cz.services.lookup import find_institutions

    matches = await find_institutions(session, query, "ru", limit=3)
    assert matches, f"{query!r} matched no institution"

    codes = []
    for match in matches:
        row = await session.scalar(select(Institution).where(Institution.id == match.id))
        codes.append(row.code)
    assert expect_code in codes, f"{query!r} -> {codes}, expected {expect_code}"


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_transliteration_is_czech_flavoured():
    """ч becomes "c" as in Č, not "ch" as in an English transcription."""
    from students_cz.services.lookup import transliterate

    assert transliterate("ЧВУТ") == "cvut"
    assert transliterate("вше") == "vse"
    assert transliterate("мфф ук") == "mff uk"


# ── alphabets ───────────────────────────────────────────────────────────
#
# The sweep that produced the cases below is not here: it walks every name and
# every synonym in the catalog, and seventy-four of them already reach a
# different subject than their own — «javascript» reaches «Программирование на
# Java», «статистика» reaches «Теория вероятностей и статистика». Those are the
# catalog's own ambiguities and a test failing on them would fail on main too.
# What is pinned here is the rule this file's change added, and the regression
# it nearly shipped.


@pytest.mark.parametrize(
    ("text", "mixed"),
    [
        ("přijímačky на медицину", True),
        ("матан ČVUT", True),
        ("квантовая механика", False),
        ("kvantova mechanika", False),
        ("čeština B2", False),
        ("", False),
    ],
)
async def test_only_a_query_using_both_alphabets_is_transliterated(text, mixed) -> None:
    """A single-alphabet query already reaches the names written in it.

    Transliterating it anyway is a guess, and a guess that costs: it moved
    nineteen catalog names onto the wrong subject, because generic words collide
    once latinised.
    """
    assert mixes_scripts(text) is mixed


@pytest.mark.parametrize(
    "text",
    [
        # Every one of these reached the right subject before the change and was
        # stolen by an unconditional transliteration — measured, not imagined.
        "Статистика для экономистов",
        "Электроника и схемотехника",
        "Гидромеханика и механика жидкостей",
        "Статика и строительная механика",
        "квантовая механика",
    ],
)
async def test_a_name_a_transliteration_would_have_stolen(session, text) -> None:
    from sqlalchemy import select

    from students_cz.db.models import Subject, SubjectI18n

    rows = await find_subjects(session, text, "ru", limit=1)
    assert rows, f"{text!r} reaches nothing"

    owner = await session.scalar(
        select(SubjectI18n.subject_id).where(SubjectI18n.name == text).limit(1)
    )
    if owner is None:
        # A synonym rather than a name: it belongs to whichever subject lists it.
        owner = await session.scalar(
            select(Subject.id).where(Subject.synonyms.any(text)).limit(1)
        )
    assert owner is not None, f"{text!r} is not in the catalog any more"
    assert rows[0].id == owner, f"{text!r} answered {rows[0].label}"
