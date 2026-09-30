"""What the operator reads in the console. See services/admin.py."""

from fastapi import APIRouter

from students_cz.api.deps import AdminDep, LangDep, SessionDep
from students_cz.schemas import AdminCatalog, AdminPlacement
from students_cz.services import admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/catalog", response_model=AdminCatalog)
async def read_catalog(_: AdminDep, session: SessionDep, lang: LangDep) -> AdminCatalog:
    return await admin.catalog(session, lang)


@router.get("/partners", response_model=list[AdminPlacement])
async def read_partners(
    _: AdminDep, session: SessionDep, lang: LangDep
) -> list[AdminPlacement]:
    return await admin.partners(session, lang)
