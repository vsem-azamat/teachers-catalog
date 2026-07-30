"""Every kind of help belongs to a group, and production hears about it.

Two different silent failures live here.

The first is a service type with no group. Both screens that show these tiles —
the catalog's front door and the screen where someone offers a service — render
by group, so an ungrouped type appears on neither. Nothing errors; the type is
simply invisible.

The second is the seed and the migration drifting apart. The deployment runs
`alembic upgrade head` and never runs `seed.py`, so a row that exists only in
the seed reaches every developer's database and no production one. The two
therefore hold the same reference data on purpose, and the last test here is
what keeps them saying the same thing.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from students_cz.db.models import ServiceType
from students_cz.db.models.enums import ServiceGroup
from students_cz.db.seed import SERVICE_TYPES

VERSIONS = Path(__file__).resolve().parents[1] / "src/students_cz/db/migrations/versions"


def _seeded_groups() -> dict[str, str]:
    return {spec["code"]: spec["group"] for spec in SERVICE_TYPES}


def _seeded_rows() -> dict[str, dict[str, Any]]:
    """Everything about a service type that a deployed database has to match."""
    return {
        spec["code"]: {
            "group": spec["group"],
            "unit": spec.get("default_price_unit"),
            "names": {lang: tuple(value) for lang, value in spec["names"].items()},
        }
        for spec in SERVICE_TYPES
    }


def _migrated_rows() -> dict[str, dict[str, Any]]:
    """The same, for the rows the migrations actually create."""
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        for row in _load(path):
            if "names" not in row:
                continue
            rows[row["code"]] = {
                "group": row["group"],
                "unit": row["default_price_unit"],
                "names": {lang: tuple(value) for lang, value in row["names"].items()},
            }
    return rows


def _load(path: Path) -> list[dict[str, Any]]:
    """The service types one migration writes, or nothing if it writes none.

    Every row is checked for the two keys these comparisons index, and named if
    it lacks them: a future migration that spells its table differently should
    say so here rather than fail with a bare `KeyError` in a helper.
    """
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rows = list(getattr(module, "SERVICE_TYPES", []))
    for row in rows:
        missing = sorted({"code", "group"} - set(row))
        assert not missing, f"{path.name}: a SERVICE_TYPES row is missing {missing}"
    return rows


def _migrated_groups() -> dict[str, str]:
    """What the migrations, taken together, leave a deployed database holding.

    Every migration, not one named file. A migration describes the database at
    a moment in time and must never be edited afterwards, so pinning this to a
    single revision would mean the thirteenth service type could only be added
    by rewriting history.

    Later revisions win, ordered by filename rather than by walking the revision
    chain. That is only correct because every file here is date prefixed, which
    is this repository's convention and not alembic's rule — two revisions
    landing on the same day and disagreeing about the same code would be
    resolved arbitrarily. They would also be a mistake worth catching by hand.

    Loaded by path rather than imported: `versions` is not a package.
    """
    groups: dict[str, str] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        for row in _load(path):
            groups[row["code"]] = row["group"]
    return groups


def test_every_seeded_service_type_declares_a_group() -> None:
    """A twelfth type appended without a group would default to `study`.

    Checking the column against `ServiceGroup` instead would prove nothing:
    the column is typed, so a member test can never fail. The mistake worth
    catching happens in the seed, in Python, before any of that.
    """
    missing = [spec["code"] for spec in SERVICE_TYPES if not spec.get("group")]
    assert missing == [], f"service types with no group: {missing}"

    unknown = sorted(
        {spec["group"] for spec in SERVICE_TYPES}
        - {member.value for member in ServiceGroup}
    )
    assert unknown == [], f"groups that are not in ServiceGroup: {unknown}"


def test_the_three_groups_are_all_used() -> None:
    """A group nobody is in renders an empty heading on both screens."""
    used = {spec["group"] for spec in SERVICE_TYPES}
    assert used == {member.value for member in ServiceGroup}


@pytest.mark.asyncio
async def test_seeded_groups_reach_the_database(session: Any) -> None:
    rows = (await session.scalars(select(ServiceType))).all()
    assert rows, "reference data is not loaded — run `make seed`"

    stored = {row.code: row.group_code.value for row in rows}
    expected = _seeded_groups()
    assert {code: stored.get(code) for code in expected} == expected


def test_seed_and_migrations_agree_on_which_types_exist() -> None:
    """The one that stops production drifting from the seed.

    `seed.py` builds a fresh database; the migrations are the only thing that
    runs on the deployed one. A type added to one and not the other is a
    category that exists locally and nowhere else — or, the other way round, a
    category live in production that no fresh checkout has.
    """
    assert _migrated_groups() == _seeded_groups()


def test_seed_and_migrations_agree_on_what_those_types_say() -> None:
    """Names too, not only codes — that is where most of the data is.

    Forty translated strings and a price unit are written out twice, and only
    the seed's copy is ever re-read. Renaming a service type there and stopping
    would leave production showing the old name for ever, because the seed does
    not run on the deployed database: a rename needs a migration, and this is
    what says so.

    Only the rows a migration creates are compared, which is five of the twelve.
    No migration creates the other seven — the initial schema builds the table
    and inserts nothing, and they reached production because somebody ran the
    seed against it by hand. Renaming one of those still needs a migration, and
    nothing here will tell you so; docs/data-model.md is where that is written
    down.
    """
    migrated = _migrated_rows()
    seeded = _seeded_rows()
    assert migrated == {code: seeded[code] for code in migrated}


def test_subjectless_is_exactly_the_life_group():
    """The parser's own list of subjectless kinds, against the seed.

    `SUBJECTLESS` is written out in the parser because it reads no tables, and a
    sixth kind of help in the `life` group would otherwise be added without the
    rule that protects it — a query naming a subject would come back with that
    kind beside it, and the two filters together match nobody.

    Not `requires_subject`: exam help and nostrification have that false too and
    must stay out of this set.
    """
    from students_cz.db.seed import SERVICE_TYPES
    from students_cz.services.parser import SUBJECTLESS

    life = {spec["code"] for spec in SERVICE_TYPES if spec["group"] == "life"}
    assert life == SUBJECTLESS
