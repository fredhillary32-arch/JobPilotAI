from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.services.countries import COUNTRIES, is_country_code

WorkArrangement = Literal["remote", "hybrid", "onsite"]
RelocationWillingness = Literal["willing", "not_willing"]
WorkAuthorizationStatus = Literal["authorized", "not_authorized"]


def _country_code(value: str) -> str:
    code = value.strip().upper()
    if not is_country_code(code):
        raise ValueError(f"{value!r} is not an ISO 3166-1 country code.")
    return code


CountryCode = Annotated[str, AfterValidator(_country_code)]


class WorkAuthorizationInput(BaseModel):
    country_code: CountryCode
    status: WorkAuthorizationStatus


class CandidateEligibilityDetailsInput(BaseModel):
    """Saving replaces all details and records them as candidate-confirmed.

    Leave a value null, or a list empty, when it is unknown; nothing is inferred.
    """

    confirmed: Literal[True]
    country_of_residence: CountryCode | None = None
    relocation_willingness: RelocationWillingness | None = None
    relocation_countries: list[CountryCode] = Field(default_factory=list, max_length=50)
    accepted_work_arrangements: list[WorkArrangement] = Field(default_factory=list, max_length=3)
    work_authorizations: list[WorkAuthorizationInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def reject_duplicates_and_contradictions(self) -> "CandidateEligibilityDetailsInput":
        authorized_countries = [item.country_code for item in self.work_authorizations]
        if len(set(authorized_countries)) != len(authorized_countries):
            raise ValueError("Each country can have only one work authorization status.")
        if len(set(self.relocation_countries)) != len(self.relocation_countries):
            raise ValueError("Relocation countries must not repeat.")
        if len(set(self.accepted_work_arrangements)) != len(self.accepted_work_arrangements):
            raise ValueError("Work arrangements must not repeat.")
        if self.relocation_countries and self.relocation_willingness != "willing":
            raise ValueError("Relocation countries can only be listed when you are willing to relocate.")
        return self


class WorkAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country_code: str
    country_name: str
    status: WorkAuthorizationStatus
    confirmed_at: datetime


class CandidateEligibilityDetailsRead(BaseModel):
    confirmation_status: Literal["not_confirmed", "confirmed"]
    confirmed_at: datetime | None = None
    country_of_residence: str | None = None
    country_of_residence_name: str | None = None
    relocation_willingness: RelocationWillingness | None = None
    relocation_countries: list[str] = []
    accepted_work_arrangements: list[WorkArrangement] = []
    work_authorizations: list[WorkAuthorizationRead] = []


class CountryRead(BaseModel):
    code: str
    name: str


def country_name(code: str | None) -> str | None:
    return COUNTRIES.get(code) if code else None
