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


def _migrated_groups() -> dict[str, str]:
    """What the migrations, taken together, leave a deployed database holding.

    Every migration, not one named file. A migration describes the database at
    a moment in time and must never be edited afterwards, so pinning this to a
    single revision would mean the thirteenth service type could only be added
    by rewriting history. Later revisions win, by filename — they are date
    prefixed, and alembic's `versions` directory is not a package, so each is
    loaded by path rather than imported.
    """
    groups: dict[str, str] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
        assert spec is not None and spec.loader is not None, f"cannot load {path}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for row in getattr(module, "SERVICE_TYPES", []):
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


def test_seed_and_migrations_agree() -> None:
    """The one that stops production drifting from the seed.

    `seed.py` builds a fresh database; the migrations are the only thing that
    runs on the deployed one. A type added to one and not the other is a
    category that exists locally and nowhere else — or, the other way round, a
    category live in production that no fresh checkout has.
    """
    assert _migrated_groups() == _seeded_groups()
