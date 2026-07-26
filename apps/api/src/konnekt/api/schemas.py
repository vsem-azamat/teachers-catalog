"""Response and request shapes for the mini app.

Two conventions worth stating once:

* **Data** is localised here; **chrome** is not. Names of subjects, faculties
  and service types arrive already in the caller's language, because those
  translations live in the database. Sentences the interface composes do not:
  they arrive as a `Phrase` — a code plus parameters — and the client renders
  them. Czech has four plural forms and Russian's are differently shaped; that
  belongs in the presentation layer, which has the rules, not in an API that
  would have to reimplement them.
* Screens are assembled server-side. `/home` returns the whole home screen in
  one response rather than making a phone on mobile data issue six requests.
"""

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from konnekt.db.models.enums import PriceUnit, UiLang, WorkFormat

# Matches ARRAY(String(8)) in the schema; a longer code cannot be stored, and a
# request carrying one should be told so rather than fail at the database.
LangCode = Annotated[str, StringConstraints(min_length=2, max_length=8)]


class Phrase(BaseModel):
    """A sentence for the client to render, not a sentence.

    `{"code": "reason.same_exam", "params": {"taught": 40, "passed": 38}}`
    becomes "Готовил к этому же экзамену 40 человек, сдали 38" — with correct
    plural agreement, which only the client can produce.
    """

    code: str
    params: dict[str, str | int] = Field(default_factory=dict)


class Price(BaseModel):
    amount: float | None = None
    currency: str = "CZK"
    unit: PriceUnit = PriceUnit.HOUR


class Avatar(BaseModel):
    """Enough to draw the little circle without fetching anything.

    Telegram avatar URLs expire, so a monogram is the fallback rather than a
    broken image. The colour is derived from the user id, which keeps the same
    person the same colour across screens.
    """

    initials: str
    tone: int = Field(ge=0, le=5)
    photo_url: str | None = None


# ── taxonomy ────────────────────────────────────────────────────────────


class ServiceTypeOut(BaseModel):
    id: int
    code: str
    name: str
    hint: str | None = None
    requires_subject: bool
    requires_institution: bool


class SubjectOut(BaseModel):
    id: int
    slug: str
    name: str
    parent_id: int | None = None
    has_children: bool = False
    external_code: str | None = None
    offers_count: int = 0


class InstitutionOut(BaseModel):
    id: int
    code: str
    name: str
    short_name: str | None = None
    city: str | None = None
    parent_id: int | None = None
    faculties: list["InstitutionOut"] = Field(default_factory=list)


class LanguageOut(BaseModel):
    code: str
    name: str


# ── catalog ─────────────────────────────────────────────────────────────


class OfferOut(BaseModel):
    id: int
    service_type: str
    service_type_name: str
    subject: str | None = None
    institution: str | None = None
    price: Price
    langs: list[str]
    work_format: WorkFormat


class HelperCardOut(BaseModel):
    """One row in the results list."""

    user_id: int
    name: str
    avatar: Avatar
    affiliation: str | None = None
    price: Price | None = None
    # The line under the name explaining why this person is in the list at all.
    # Sometimes it says the match is weak; that is the point.
    reason: Phrase | None = None
    availability: Phrase | None = None
    rating: float | None = None
    deals_count: int = 0
    langs: list[str] = Field(default_factory=list)


class Stat(BaseModel):
    code: str
    value: str


class ReviewOut(BaseModel):
    author: str
    created_on: date
    text: str


class HelperDetailOut(BaseModel):
    user_id: int
    name: str
    avatar: Avatar
    affiliation: str | None = None
    about: str | None = None
    headline: str | None = None
    stats: list[Stat]
    offers: list[OfferOut]
    langs: list[str]
    work_format: WorkFormat
    place_note: str | None = None
    free_slots: list[datetime] = Field(default_factory=list)
    reviews: list[ReviewOut] = Field(default_factory=list)
    # Everything the client needs to compose the prefilled first message. The
    # wording is the client's; the facts are ours.
    intro_context: dict[str, str | int] = Field(default_factory=dict)
    telegram_url: str | None = None


# ── search ──────────────────────────────────────────────────────────────


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class Chip(BaseModel):
    """One piece of what we understood, shown back for correction."""

    kind: str  # subject | institution | service_type | deadline | budget | lang
    label: str
    value: str | int | None = None
    confidence: float = 1.0


class ClarifyOption(BaseModel):
    code: str
    tone: int = 0


class Clarify(BaseModel):
    """One question, asked only when the answer changes the result set.

    Never a wall of filters — if we cannot justify asking, we do not ask.
    """

    code: str
    options: list[ClarifyOption]


class ParseOut(BaseModel):
    chips: list[Chip]
    clarify: Clarify | None = None
    matches: int
    # Set when nothing was recognised, so the screen can say so plainly
    # instead of showing an empty list and looking broken.
    note: Phrase | None = None


class SearchFilters(BaseModel):
    subject_id: int | None = None
    institution_id: int | None = None
    service_type_id: int | None = None
    max_price: float | None = None
    langs: list[str] = Field(default_factory=list)
    work_format: WorkFormat | None = None


class SearchOut(BaseModel):
    total: int
    filters: SearchFilters
    chips: list[Chip]
    results: list[HelperCardOut]


# ── home ────────────────────────────────────────────────────────────────


class HomeSection(BaseModel):
    kind: str  # service_type | item_category
    code: str
    name: str
    hint: str | None = None
    tone: int
    count: int
    live_count: int | None = None
    avatars: list[Avatar] = Field(default_factory=list)


class HomeOut(BaseModel):
    people: list[HomeSection]
    things: list[HomeSection]


# ── partners ────────────────────────────────────────────────────────────


class PlacementOut(BaseModel):
    id: int
    title: str
    subtitle: str | None = None
    price_text: str | None = None
    context_note: str | None = None
    logo_text: str | None = None
    logo_bg: str | None = None
    url: str


# ── user ────────────────────────────────────────────────────────────────


class MeOut(BaseModel):
    id: int
    tg_id: int
    name: str
    username: str | None = None
    avatar: Avatar
    ui_lang: UiLang
    spoken_langs: list[str]
    city: str | None = None
    institution: InstitutionOut | None = None
    is_helper: bool
    helper_status: str | None = None


class MeUpdate(BaseModel):
    ui_lang: UiLang | None = None
    # Bounds mirror the columns: an over-long value would otherwise reach
    # Postgres and come back as a 500 rather than a validation error.
    spoken_langs: list[LangCode] | None = Field(default=None, max_length=12)
    city: str | None = Field(default=None, max_length=96)
    institution_id: int | None = None


# ── becoming a helper ───────────────────────────────────────────────────


class IntroRequest(BaseModel):
    text: str = Field(min_length=10, max_length=4000)


class IntroOut(BaseModel):
    """What we made of "расскажи своими словами".

    Everything is a chip the person can remove, and `missing` names what the
    text did not say — so the screen asks for exactly that instead of showing
    a four-step wizard.
    """

    chips: list[Chip]
    price: Price | None = None
    work_format: WorkFormat | None = None
    institution_id: int | None = None
    subject_ids: list[int] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class OfferIn(BaseModel):
    service_type_id: int
    subject_id: int | None = None
    institution_id: int | None = None
    price_amount: float | None = Field(default=None, ge=0, le=1_000_000)
    price_unit: PriceUnit = PriceUnit.HOUR
    langs: list[LangCode] = Field(default_factory=list, max_length=12)


class HelperUpsert(BaseModel):
    headline: str | None = Field(default=None, max_length=160)
    about: str | None = Field(default=None, max_length=4000)
    raw_intro: str | None = Field(default=None, max_length=4000)
    work_format: WorkFormat = WorkFormat.BOTH
    city: str | None = Field(default=None, max_length=96)
    place_note: str | None = Field(default=None, max_length=240)
    # A person offers a handful of things, not a catalogue. The cap keeps one
    # request from writing tens of thousands of rows in a single transaction.
    offers: list[OfferIn] = Field(default_factory=list, max_length=60)
    publish: bool = False


# ── requests ────────────────────────────────────────────────────────────


class RequestCreate(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    subject_id: int | None = None
    institution_id: int | None = None
    service_type_id: int | None = None
    deadline_on: date | None = None
    budget_max: float | None = Field(default=None, ge=0, le=1_000_000)
    langs: list[LangCode] = Field(default_factory=list, max_length=12)


class RequestOut(BaseModel):
    id: int
    text: str
    subject: str | None = None
    institution: str | None = None
    service_type: str | None = None
    deadline_on: date | None = None
    status: str
    responses_count: int = 0
    responders: list[Avatar] = Field(default_factory=list)
    created_at: datetime
