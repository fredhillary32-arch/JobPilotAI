from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import CandidateProfile, CandidateWorkAuthorization
from app.services.countries import COUNTRIES, countries_named_in

API = "/api/v1/candidate-profiles"


def _profile(client: TestClient, **fields) -> str:
    response = client.post(API, json={"name": "Eligibility Owner", **fields})
    assert response.status_code == 201
    return response.json()["id"]


def _confirm(client: TestClient, profile_id: str, **details):
    return client.put(f"{API}/{profile_id}/eligibility-details", json={"confirmed": True, **details})


def test_country_reference_is_iso_and_names_are_matched_case_sensitively() -> None:
    assert len(COUNTRIES) == 249 and COUNTRIES["KE"] == "Kenya"
    assert countries_named_in("Must be authorized to work in the U.S. or the UK. Based in Kenya.") == ["US", "GB", "KE"]
    assert countries_named_in("Tell us about the united states of affairs; reach us.") == []


def test_unconfirmed_profile_reports_nothing_as_known(api_client: TestClient) -> None:
    profile_id = _profile(api_client, location="Nairobi, Kenya")

    details = api_client.get(f"{API}/{profile_id}/eligibility-details").json()

    # The free-text profile location is never turned into a confirmed residence.
    assert details["confirmation_status"] == "not_confirmed"
    assert details["country_of_residence"] is None
    assert details["work_authorizations"] == []


def test_confirming_details_records_them_without_inferring_authorization(api_client: TestClient) -> None:
    profile_id = _profile(api_client)

    response = _confirm(
        api_client,
        profile_id,
        country_of_residence="ke",
        relocation_willingness="willing",
        relocation_countries=["DE"],
        accepted_work_arrangements=["remote", "hybrid"],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmation_status"] == "confirmed" and body["confirmed_at"]
    assert (body["country_of_residence"], body["country_of_residence_name"]) == ("KE", "Kenya")
    # Residence in Kenya does not create a Kenyan work authorization.
    assert body["work_authorizations"] == []


def test_work_authorizations_are_stored_per_country_and_replaced_on_reconfirmation(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    first = _confirm(api_client, profile_id, work_authorizations=[
        {"country_code": "KE", "status": "authorized"},
        {"country_code": "US", "status": "not_authorized"},
    ])
    assert [(a["country_code"], a["status"]) for a in first.json()["work_authorizations"]] == [("KE", "authorized"), ("US", "not_authorized")]

    second = _confirm(api_client, profile_id, work_authorizations=[{"country_code": "KE", "status": "authorized"}])

    assert [a["country_code"] for a in second.json()["work_authorizations"]] == ["KE"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CandidateWorkAuthorization)) == 1


def test_invalid_or_contradictory_details_are_rejected(api_client: TestClient) -> None:
    profile_id = _profile(api_client)

    responses = [
        _confirm(api_client, profile_id, country_of_residence="XX"),
        _confirm(api_client, profile_id, work_authorizations=[{"country_code": "KE", "status": "authorized"}, {"country_code": "ke", "status": "not_authorized"}]),
        _confirm(api_client, profile_id, relocation_willingness="not_willing", relocation_countries=["DE"]),
        _confirm(api_client, profile_id, accepted_work_arrangements=["remote", "remote"]),
        _confirm(api_client, profile_id, work_authorizations=[{"country_code": "KE", "status": "probably"}]),
        api_client.put(f"{API}/{profile_id}/eligibility-details", json={"country_of_residence": "KE"}),
        api_client.put(f"{API}/{profile_id}/eligibility-details", json={"confirmed": False, "country_of_residence": "KE"}),
    ]

    assert [r.status_code for r in responses] == [422] * 7
    assert api_client.get(f"{API}/{profile_id}/eligibility-details").json()["confirmation_status"] == "not_confirmed"


def test_unknown_values_stay_unknown_after_confirmation(api_client: TestClient) -> None:
    profile_id = _profile(api_client)

    body = _confirm(api_client, profile_id).json()

    assert body["confirmation_status"] == "confirmed"
    assert (body["country_of_residence"], body["relocation_willingness"]) == (None, None)
    assert body["accepted_work_arrangements"] == [] and body["work_authorizations"] == []


def test_details_are_owner_scoped(api_client: TestClient, database) -> None:
    _, factory = database
    with factory.begin() as session:
        legacy = CandidateProfile(name="Unowned legacy profile")
        session.add(legacy)
        session.flush()
        legacy_id = legacy.id

    assert api_client.get(f"{API}/{legacy_id}/eligibility-details").status_code == 404
    assert _confirm(api_client, str(legacy_id), country_of_residence="KE").status_code == 404
    assert api_client.get(f"{API}/{uuid4()}/eligibility-details").status_code == 404


def test_confirmation_requires_csrf(api_client: TestClient) -> None:
    profile_id = _profile(api_client)

    response = api_client.put(
        f"{API}/{profile_id}/eligibility-details",
        json={"confirmed": True, "country_of_residence": "KE"},
        headers={"X-CSRF-Token": "not-the-session-token"},
    )

    assert response.status_code == 403
    assert api_client.get(f"{API}/{profile_id}/eligibility-details").json()["confirmation_status"] == "not_confirmed"


def test_country_list_is_available_to_signed_in_users(api_client: TestClient, unauthenticated_client: TestClient) -> None:
    countries = api_client.get("/api/v1/countries").json()
    assert {"code": "KE", "name": "Kenya"} in countries and len(countries) == 249
