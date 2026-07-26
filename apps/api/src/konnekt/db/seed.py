"""Load reference data.

Idempotent by design: every row is matched on its stable key (`code` or
`slug`), so running this twice updates rather than duplicates. That matters
because the subject list will keep growing — new synonyms get added every time
a query in `search_queries` comes back empty — and reseeding must stay a safe,
boring operation.

    uv run python -m konnekt.db.seed
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from konnekt.db.models import (
    Institution,
    InstitutionI18n,
    Language,
    LanguageI18n,
    ServiceType,
    ServiceTypeI18n,
    Subject,
    SubjectI18n,
)
from konnekt.db.models.enums import InstitutionKind, NodeKind, UiLang
from konnekt.db.session import dispose_engine, get_sessionmaker


def _find_seeds_dir() -> Path:
    """Locate the seed files by searching upward, not by counting parents.

    Three levels up is right in the checkout and right in the image, but only
    by coincidence — the same fixed-depth assumption in the settings module
    raised on import inside Docker. Searching is cheap and cannot be wrong.
    """
    for directory in Path(__file__).resolve().parents:
        candidate = directory / "seeds"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parents[3] / "seeds"


SEEDS_DIR = _find_seeds_dir()

LANGS: tuple[UiLang, ...] = (UiLang.RU, UiLang.CS, UiLang.EN, UiLang.UK)


# Kinds of help, in the order they appear on the home screen. The requires_*
# flags drive what the offer form asks for: a written paper needs no subject,
# entrance preparation is meaningless without naming the school.
SERVICE_TYPES: list[dict[str, Any]] = [
    {
        "code": "tutoring",
        "requires_subject": True,
        "default_price_unit": "hour",
        "names": {
            "ru": (
                "Репетитор по предмету",
                "матан, физика, экономика, программирование",
            ),
            "cs": ("Doučování předmětu", "matematika, fyzika, ekonomie, programování"),
            "en": ("Subject tutoring", "calculus, physics, economics, programming"),
            "uk": ("Репетитор з предмета", "матан, фізика, економіка, програмування"),
        },
    },
    {
        "code": "entrance_prep",
        "requires_institution": True,
        "default_price_unit": "hour",
        "names": {
            "ru": ("Přijímačky", "ČVUT, VŠE, UK, VUT, MUNI"),
            "cs": ("Přijímačky", "ČVUT, VŠE, UK, VUT, MUNI"),
            "en": ("Entrance exams", "ČVUT, VŠE, UK, VUT, MUNI"),
            "uk": ("Přijímačky", "ČVUT, VŠE, UK, VUT, MUNI"),
        },
    },
    {
        "code": "language_tutoring",
        "requires_subject": True,
        "default_price_unit": "hour",
        "names": {
            "ru": ("Языки", "čeština B1/B2, английский, немецкий"),
            "cs": ("Jazyky", "čeština B1/B2, angličtina, němčina"),
            "en": ("Languages", "Czech B1/B2, English, German"),
            "uk": ("Мови", "čeština B1/B2, англійська, німецька"),
        },
    },
    {
        "code": "exam_live_help",
        "default_price_unit": "hour",
        "names": {
            "ru": ("Помощь на экзамене", "подстраховка онлайн в день сдачи"),
            "cs": ("Pomoc u zkoušky", "online podpora v den zkoušky"),
            "en": ("Help during the exam", "online backup on the day"),
            "uk": ("Допомога на іспиті", "підстраховка онлайн у день складання"),
        },
    },
    {
        "code": "exam_prep",
        "requires_subject": True,
        "default_price_unit": "hour",
        "names": {
            "ru": ("Подготовка к экзамену", "зачёт, пересдача, короткий срок"),
            "cs": ("Příprava na zkoušku", "zápočet, opravný termín, krátký čas"),
            "en": ("Exam preparation", "credits, retakes, short notice"),
            "uk": ("Підготовка до іспиту", "залік, перескладання, стислий термін"),
        },
    },
    {
        "code": "nostrification",
        "default_price_unit": "hour",
        "names": {
            "ru": ("Нострификация", "аттестат, диплом, досдача предметов"),
            "cs": ("Nostrifikace", "vysvědčení, diplom, doplňkové zkoušky"),
            "en": ("Nostrification", "school certificate, diploma, extra exams"),
            "uk": ("Нострифікація", "атестат, диплом, додаткові іспити"),
        },
    },
    {
        "code": "writing",
        "default_price_unit": "work",
        "names": {
            "ru": ("Написать работу", "семестровка, бакалаврская, реферат"),
            "cs": ("Napsat práci", "semestrální, bakalářská, referát"),
            "en": ("Written work", "term paper, bachelor thesis, essay"),
            "uk": ("Написати роботу", "семестрова, бакалаврська, реферат"),
        },
    },
]

# Languages people work in — the same four the interface speaks.
#
# It was wider, and that was a mistake: a question with nine answers is a
# question people skip, and the tail of it (Kazakh, Uzbek, Vietnamese, Slovak,
# German) never matched a single pair. Codes are deactivated rather than
# deleted, because `users.spoken_langs` and `offers.langs` already hold them
# and a code that vanishes would silently stop matching.
WORKING_LANGUAGES: list[tuple[str, dict[str, str]]] = [
    ("ru", {"ru": "Русский", "cs": "Ruština", "en": "Russian", "uk": "Російська"}),
    (
        "uk",
        {
            "ru": "Украинский",
            "cs": "Ukrajinština",
            "en": "Ukrainian",
            "uk": "Українська",
        },
    ),
    ("cs", {"ru": "Чешский", "cs": "Čeština", "en": "Czech", "uk": "Чеська"}),
    (
        "en",
        {"ru": "Английский", "cs": "Angličtina", "en": "English", "uk": "Англійська"},
    ),
]


async def seed_service_types(session: AsyncSession) -> int:
    for sort, spec in enumerate(SERVICE_TYPES, start=1):
        row = await session.scalar(
            select(ServiceType).where(ServiceType.code == spec["code"])
        )
        if row is None:
            row = ServiceType(code=spec["code"])
            session.add(row)
        row.requires_subject = spec.get("requires_subject", False)
        row.requires_institution = spec.get("requires_institution", False)
        row.default_price_unit = spec.get("default_price_unit")
        row.sort = sort
        row.is_active = True
        await session.flush()
        for lang, (name, hint) in spec["names"].items():
            await _upsert_i18n(
                session,
                ServiceTypeI18n,
                {"service_type_id": row.id, "lang": UiLang(lang)},
                {"name": name, "hint": hint},
            )
    await session.commit()
    return len(SERVICE_TYPES)


async def seed_languages(session: AsyncSession) -> int:
    for sort, (code, names) in enumerate(WORKING_LANGUAGES, start=1):
        row = await session.get(Language, code)
        if row is None:
            row = Language(code=code)
            session.add(row)
        row.sort = sort
        row.is_active = True
        await session.flush()
        for lang, name in names.items():
            await _upsert_i18n(
                session,
                LanguageI18n,
                {"language_code": code, "lang": UiLang(lang)},
                {"name": name},
            )

    # Retire anything the list no longer holds. The row stays, so a profile
    # that already claims Slovak keeps its data and can be read back; it simply
    # stops being offered as a choice.
    kept = [code for code, _ in WORKING_LANGUAGES]
    await session.execute(
        update(Language).where(Language.code.notin_(kept)).values(is_active=False)
    )
    await session.commit()
    return len(WORKING_LANGUAGES)


async def seed_subjects(session: AsyncSession, path: Path) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    groups = data["groups"]
    group_count = leaf_count = 0

    for group_sort, group in enumerate(groups, start=1):
        parent = await _upsert_subject(
            session,
            slug=group["slug"],
            names=group["names"],
            kind=NodeKind.GROUP,
            sort=group_sort,
            parent=None,
        )
        group_count += 1
        for leaf_sort, leaf in enumerate(group.get("children", []), start=1):
            await _upsert_subject(
                session,
                slug=leaf["slug"],
                names=leaf["names"],
                kind=NodeKind.LEAF,
                sort=leaf_sort,
                parent=parent,
                synonyms=leaf.get("synonyms", []),
            )
            leaf_count += 1

    await session.commit()
    return group_count, leaf_count


async def _upsert_subject(
    session: AsyncSession,
    *,
    slug: str,
    names: dict[str, str],
    kind: NodeKind,
    sort: int,
    parent: Subject | None,
    synonyms: list[str] | None = None,
) -> Subject:
    row = await session.scalar(select(Subject).where(Subject.slug == slug))
    if row is None:
        row = Subject(slug=slug, path="")
        session.add(row)
    row.kind = kind
    row.sort = sort
    row.is_active = True
    row.parent_id = parent.id if parent else None
    row.depth = (parent.depth + 1) if parent else 0
    # Synonyms are normalised at match time, so store them as written — that
    # keeps the seed file readable and lets a human spot duplicates.
    row.synonyms = sorted({s.strip() for s in (synonyms or []) if s.strip()})
    await session.flush()
    # The materialised path needs the row's own id, so it can only be built
    # after the flush that assigns one.
    row.path = f"{parent.path}{row.id}." if parent else f"{row.id}."
    await session.flush()

    for lang, name in names.items():
        if lang not in {code.value for code in LANGS}:
            continue
        await _upsert_i18n(
            session,
            SubjectI18n,
            {"subject_id": row.id, "lang": UiLang(lang)},
            {"name": name},
        )
    return row


async def seed_institutions(session: AsyncSession, path: Path) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    uni_count = fac_count = 0

    for sort, uni in enumerate(data["institutions"], start=1):
        parent = await _upsert_institution(
            session,
            code=uni["code"],
            kind=InstitutionKind(uni.get("kind", "university")),
            city=uni.get("city"),
            site_url=uni.get("site_url"),
            names=uni.get("names", {}),
            short_names=uni.get("short_names", {}),
            sort=sort,
            parent=None,
        )
        uni_count += 1
        for fac_sort, fac in enumerate(uni.get("faculties", []), start=1):
            await _upsert_institution(
                session,
                code=fac["code"],
                kind=InstitutionKind.FACULTY,
                city=fac.get("city") or uni.get("city"),
                site_url=fac.get("site_url"),
                names=fac.get("names", {}),
                short_names=fac.get("short_names", {}),
                sort=fac_sort,
                parent=parent,
            )
            fac_count += 1

    await session.commit()
    return uni_count, fac_count


async def _upsert_institution(
    session: AsyncSession,
    *,
    code: str,
    kind: InstitutionKind,
    city: str | None,
    site_url: str | None,
    names: dict[str, str],
    short_names: dict[str, str],
    sort: int,
    parent: Institution | None,
) -> Institution:
    row = await session.scalar(select(Institution).where(Institution.code == code))
    if row is None:
        row = Institution(code=code, path="", kind=kind)
        session.add(row)
    row.kind = kind
    row.city = city
    row.site_url = site_url
    row.sort = sort
    row.is_active = True
    row.parent_id = parent.id if parent else None
    row.depth = (parent.depth + 1) if parent else 0
    await session.flush()
    row.path = f"{parent.path}{row.id}." if parent else f"{row.id}."
    await session.flush()

    for lang in LANGS:
        name = names.get(lang.value)
        short = short_names.get(lang.value)
        if not name and not short:
            continue
        await _upsert_i18n(
            session,
            InstitutionI18n,
            {"institution_id": row.id, "lang": lang},
            {"name": name or short or code, "short_name": short},
        )
    return row


async def _upsert_i18n(
    session: AsyncSession, model, keys: dict[str, Any], values: dict[str, Any]
) -> None:
    stmt = select(model)
    for key, value in keys.items():
        stmt = stmt.where(getattr(model, key) == value)
    row = await session.scalar(stmt)
    if row is None:
        row = model(**keys)
        session.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    await session.flush()


async def run() -> None:
    async with get_sessionmaker()() as session:
        services = await seed_service_types(session)
        languages = await seed_languages(session)
        print(f"service types : {services}")
        print(f"languages     : {languages}")

        subjects_file = SEEDS_DIR / "subjects.json"
        if subjects_file.exists():
            groups, leaves = await seed_subjects(session, subjects_file)
            print(f"subjects      : {groups} groups, {leaves} leaves")
        else:
            print(f"subjects      : skipped, no {subjects_file}")

        institutions_file = SEEDS_DIR / "institutions.json"
        if institutions_file.exists():
            unis, faculties = await seed_institutions(session, institutions_file)
            print(f"institutions  : {unis} universities, {faculties} faculties")
        else:
            print(f"institutions  : skipped, no {institutions_file}")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(run())
