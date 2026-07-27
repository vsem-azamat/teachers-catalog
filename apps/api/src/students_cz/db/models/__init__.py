"""All ORM models.

Importing this package registers every mapper, which is what Alembic's
autogenerate needs to see the full schema. Import it, do not cherry-pick
modules, or migrations will silently miss tables.
"""

from konnekt.db.base import Base
from konnekt.db.models.catalog import Offer
from konnekt.db.models.goods import Item, Material
from konnekt.db.models.ops import ModerationReview, SearchQuery, UserEvent
from konnekt.db.models.partners import (
    Partner,
    PartnerOffer,
    PartnerOfferI18n,
    Placement,
    PlacementEvent,
)
from konnekt.db.models.people import (
    AvailabilitySlot,
    HelperProfile,
    User,
    UserEducation,
    WeeklyAvailability,
)
from konnekt.db.models.requests import Contact, HelpRequest, RequestResponse
from konnekt.db.models.taxonomy import (
    Institution,
    InstitutionI18n,
    ItemCategory,
    ItemCategoryI18n,
    Language,
    LanguageI18n,
    ServiceType,
    ServiceTypeI18n,
    StudentChat,
    Subject,
    SubjectI18n,
)

__all__ = [
    "AvailabilitySlot",
    "Base",
    "Contact",
    "HelpRequest",
    "HelperProfile",
    "Institution",
    "InstitutionI18n",
    "Item",
    "ItemCategory",
    "ItemCategoryI18n",
    "Language",
    "LanguageI18n",
    "Material",
    "ModerationReview",
    "Offer",
    "Partner",
    "PartnerOffer",
    "PartnerOfferI18n",
    "Placement",
    "PlacementEvent",
    "RequestResponse",
    "SearchQuery",
    "ServiceType",
    "ServiceTypeI18n",
    "StudentChat",
    "Subject",
    "SubjectI18n",
    "User",
    "UserEducation",
    "UserEvent",
    "WeeklyAvailability",
]
