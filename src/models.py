from enum import Enum

from pydantic import BaseModel


class RoleType(str, Enum):
    SOFTWARE_ENGINEERING = "Software Engineering"
    DATA_ML_AI = "Data / ML / AI"
    HARDWARE_EMBEDDED = "Hardware / Embedded"
    CYBERSECURITY = "Cybersecurity"
    IT_INFRASTRUCTURE = "IT / Infrastructure"
    PRODUCT_MANAGEMENT = "Product Management"
    DESIGN_UX = "Design / UX"
    BUSINESS_FINANCE = "Business / Finance"
    RESEARCH = "Research"
    OTHER = "Other"


class OpportunityType(str, Enum):
    INTERNSHIP = "Internship"
    CO_OP = "Co-op"
    NEW_GRAD = "New Grad Role"
    EARLY_INSIGHT = "Early Insight Program"
    INTEREST_FORM = "Interest Form"
    FELLOWSHIP = "Fellowship"
    RESEARCH_PROGRAM = "Research Program"
    SCHOLARSHIP = "Scholarship"
    CONFERENCE = "Conference / Event"
    MENTORSHIP = "Mentorship"
    OTHER = "Other"


class Source(str, Enum):
    API = "api"
    PAGE = "page"
    EMBED = "embed"
    URL = "url"
    NONE = "none"


class Opportunity(BaseModel):
    # The schema forces every other field to be filled, so without an honest signal of
    # what the model actually had, it will invent a complete row for a dead link.
    source: Source
    name: str
    role_type: RoleType
    opportunity_type: OpportunityType
    summary: str
    open_date: str
    close_date: str


NEEDS_REVIEW = "Needs review"


def unreadable_page():
    """Row written when the link is good but the page could not be read."""
    return Opportunity(
        source=Source.NONE,
        name=NEEDS_REVIEW,
        role_type=RoleType.OTHER,
        opportunity_type=OpportunityType.OTHER,
        summary=(
            "This page could not be opened automatically, so the details below were "
            "never filled in. "
        ),
        open_date="N/A",
        close_date="N/A",
    )
