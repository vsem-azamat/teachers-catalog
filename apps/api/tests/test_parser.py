from datetime import date

import pytest

from students_cz.services.lookup import normalise
from students_cz.services.parser import (
    SUBJECTLESS,
    _match_budget,
    _match_deadline,
    _match_service,
    _without,
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
    assert _match_service(normalise(text))[0] == expected


def test_keyword_must_start_a_word():
    """ "osp" is a Scio test; it is also inside "gospodarka"."""
    assert _match_service(normalise("gospodarka a osnovy"))[0] is None
    assert _match_service(normalise("готовлюсь к osp"))[0] == "entrance_prep"


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
    assert _match_service(normalise(text))[0] == expected


@pytest.mark.asyncio
async def test_a_short_faculty_name_is_not_found_inside_a_word(session):
    """`FI` is a faculty. It is also the first two letters of "физике".

    Trigram similarity scored that at 0.67 — above the threshold — so a query
    about physics came back naming a faculty nobody had mentioned.
    """
    parsed = await parse(session, "репетитор по физике", "ru", today=TODAY)
    assert parsed.institution is None


@pytest.mark.asyncio
async def test_a_named_two_letter_faculty_is_still_found(session):
    """The rule above must not cost us the faculty when it really is named.

    Two letters, and no university beside it: "ČVUT FI" would pass through the
    institution-code branch whatever the short-name rule does, and a three-letter
    name goes back to trigram matching, so neither would test the rule.
    """
    parsed = await parse(session, "матан на FI", "ru", today=TODAY)
    assert parsed.institution is not None
    assert parsed.institution.label == "FI"


@pytest.mark.asyncio
async def test_an_inflected_three_letter_faculty_still_matches(session):
    """Czech declines the abbreviation itself: nobody writes "na FEL".

    The whole-word rule is deliberately two letters wide and not three. At three
    it took every inflected form off the 69 institutions whose short name is
    three characters, 60 of them faculties.
    """
    parsed = await parse(session, "doucovani matematiky na FELu", "cs", today=TODAY)
    assert parsed.institution is not None
    assert parsed.institution.label == "FEL"


def test_a_keyword_takes_whole_words_with_it():
    """What is left has to be words, or the caller cannot ask if anything is.

    The keywords are stems: taking the characters of "нострифик" out of
    "нострификация" leaves "ация", which is not nothing and is not a word either.
    """
    assert _without(normalise("нострификация"), "нострифик") == ""
    assert _without(normalise("нострификация аттестата"), "нострифик") == "аттестата"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "нужен матан, живу в общежитии",
        "матан, снимаю квартиру на Виноградах",
    ],
)
async def test_an_aside_about_life_does_not_replace_the_subject(session, text):
    """Both filters are applied together, and no such offer has a subject.

    Reading these as housing produced subject + housing, which `catalog.search`
    ANDs into a pair matching nobody — a list of calculus tutors became an empty
    screen.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.label == "Математический анализ"
    assert parsed.service_type not in SUBJECTLESS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Single-word study stems used to win these on dictionary order alone:
        # "диплом" made the first thesis writing, "аттестат" made the second
        # nostrification.
        ("присяжный перевод диплома", "translation"),
        ("нужен перевод аттестата", "translation"),
        ("нотариальный перевод диплома", "translation"),
        ("i need a bank statement", "bank_letter"),
        ("bank statement for the visa", "bank_letter"),
    ],
)
async def test_document_work_survives_the_whole_parse(session, text, expected):
    """Through `parse`, not through the matcher.

    The matcher had this right while `parse` did not: a 0.55 trigram guess at a
    subject sent the kind of help back to being thesis writing, and a test on
    the private function could not see it.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "нотариальный перевод диплома",
        "bank statement for the visa",
        "нужна страховка, учусь на физике",
    ],
)
async def test_a_guessed_subject_is_dropped_not_the_kind_of_help(session, text):
    """Both filters are applied together, and these offers have no subject.

    Keeping a 0.55 trigram guess beside the kind of help is a pair that matches
    nobody, so the count and the preview on the search screen are zero for
    exactly the queries this change exists to make findable. The guess goes; a
    named subject is the other rule, two tests up.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type in SUBJECTLESS
    assert parsed.subject is None


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
async def test_no_subject_is_guessed_when_the_service_was_the_whole_query(session):
    """Nothing is left to name a subject, so none is guessed at.

    "bank statement" came back as Probability and Statistics at 0.61 — a filter
    narrower than the question, on a subject nobody had named.
    """
    parsed = await parse(session, "bank statement", "en", today=TODAY)
    assert parsed.service_type == "bank_letter"
    assert parsed.subject is None
    assert parsed.unmatched is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("курсовая", "Академическое письмо и дипломная работа"),
        ("нострификация", "Нострификационные экзамены"),
    ],
)
async def test_a_certain_subject_survives_being_the_whole_query(session, text, expected):
    """The rule above drops guesses, not curated names.

    These words are synonyms somebody wrote down for exactly this subject, which
    is not the scorer finding something in noise. Dropping them too would lose a
    certainty in order to avoid a maybe.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.matched_on == "synonym"
    assert parsed.subject.label == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A word, not a stem: "визу" is the accusative of "виза" and the first
        # four letters of "визуализация". Read as a stem it turned a question
        # about data visualisation into a residence-permit one, and since the
        # search applies both filters together the screen went empty.
        ("нужна виза в Чехию", "residence"),
        ("визуализация данных", None),
        ("визуальное программирование", None),
    ],
)
async def test_a_visa_is_a_word_and_not_a_beginning(session, text, expected):
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == expected


@pytest.mark.asyncio
async def test_a_stamped_bank_paper_is_not_a_translation(session):
    """The stamp is a modifier, not the kind of document.

    Translation is checked before the study kinds, and "s razitkem" sitting in
    it shadowed bank_letter's own phrases — so the standard stamped bank
    statement for a Czech visa came back as a document translation.
    """
    parsed = await parse(session, "vypis z banky s razitkem", "cs", today=TODAY)
    assert parsed.service_type == "bank_letter"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "Чешский язык B1, нужна виза",
        "Математический анализ, живу в общежитии",
    ],
)
async def test_a_subject_typed_out_in_full_is_named(session, text):
    """A name the query reproduces exactly scores 1.0 and reports "name".

    The first spelling of "was the subject named" asked for a *synonym*, so a
    subject somebody had typed out in full was thrown away as a guess and the
    search filtered by insurance or housing instead.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.subject is not None
    assert parsed.subject.score == 1.0
    assert parsed.service_type not in SUBJECTLESS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Words rather than stems, because the stems reached into subjects:
        # "pojist" prefixes "pojistna matematika" (actuarial mathematics) and
        # "страхован" prefixes the genitive in "экономика страхования".
        ("нужно страхование", "insurance"),
        ("pojistna matematika", None),
        ("экономика страхования", None),
        # And "zustat" is "to stay", so the bank balance is spelled out.
        ("zustatek na ucte", "bank_letter"),
        ("chci zustat v Praze", None),
        # English could not say two of these five in the plainest way.
        ("i need a visa", "residence"),
        ("student visa", "residence"),
        ("visualisation of data", None),
        ("document translation", "translation"),
        ("translate my diploma", "translation"),
    ],
)
def test_the_plainest_phrasing_reaches_the_right_kind(text, expected):
    assert _match_service(normalise(text))[0] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "перевод диплома, матан",
        "присяжный перевод диплома по матану",
        "перевод аттестата, линал",
        "document translations",
    ],
)
async def test_a_document_phrase_is_the_request_even_beside_a_named_subject(
    session, text
):
    """Translation is not an aside, so a named subject does not displace it.

    The rule that lets a named subject win re-reads the text with the non-study
    kinds removed — and with translation among them the study stem it was
    ordered above won again, so "перевод диплома, матан" came back as thesis
    writing. Nobody writes "присяжный перевод диплома" in passing.
    """
    parsed = await parse(session, text, "ru", today=TODAY)
    assert parsed.service_type == "translation"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The genitive is how these are actually asked, and a multi-word keyword
        # tolerates inflection only on its last word — so the phrases that used
        # to be here reached none of them, and the first fell through to thesis
        # writing on "диплом".
        ("присяжного перевода диплома", "translation"),
        ("нотариального перевода документов", "translation"),
        ("soudniho prekladu", "translation"),
        ("продление вида на жительство", "residence"),
        ("продовження посвідки на проживання", "residence"),
    ],
)
def test_the_genitive_reaches_the_same_kind_as_the_nominative(text, expected):
    assert _match_service(normalise(text))[0] == expected
