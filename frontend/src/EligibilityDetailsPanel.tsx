import { type FormEvent, useEffect, useState } from "react";

import { api } from "./api/client";
import type {
  CandidateEligibilityDetails,
  CandidateEligibilityInput,
  Country,
  WorkArrangement,
  WorkAuthorizationStatus,
} from "./api/types";
import { Field } from "./Views";

export type ConfirmEligibility = (payload: CandidateEligibilityInput) => Promise<boolean>;

const ARRANGEMENT_LABELS: Record<WorkArrangement, string> = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" };

function formatDay(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

export function EligibilityDetailsPanel({
  details,
  profileLocation,
  busy,
  onConfirm,
}: {
  details: CandidateEligibilityDetails;
  profileLocation: string | null;
  busy: boolean;
  onConfirm: ConfirmEligibility;
}) {
  const [countries, setCountries] = useState<Country[]>([]);
  const [editing, setEditing] = useState(false);
  const [residence, setResidence] = useState(details.country_of_residence || "");
  const [relocation, setRelocation] = useState<"" | "willing" | "not_willing">(details.relocation_willingness || "");
  const [relocationCountries, setRelocationCountries] = useState<string[]>(details.relocation_countries);
  const [arrangements, setArrangements] = useState<WorkArrangement[]>(details.accepted_work_arrangements);
  const [authorizations, setAuthorizations] = useState(details.work_authorizations.map(({ country_code, status }) => ({ country_code, status })));
  const [confirmed, setConfirmed] = useState(false);
  const names = new Map(countries.map((country) => [country.code, country.name]));
  const confirmedNow = details.confirmation_status === "confirmed";

  useEffect(() => {
    if (!editing || countries.length) return;
    let current = true;
    api.listCountries().then((list) => { if (current) setCountries(list); }).catch(() => undefined);
    return () => { current = false; };
  }, [editing, countries.length]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saved = await onConfirm({
      confirmed: true,
      country_of_residence: residence || null,
      relocation_willingness: relocation || null,
      relocation_countries: relocation === "willing" ? relocationCountries : [],
      accepted_work_arrangements: arrangements,
      work_authorizations: authorizations.filter((item) => item.country_code),
    });
    if (saved) {
      setEditing(false);
      setConfirmed(false);
    }
  }

  const countryOptions = <>{countries.map((country) => <option key={country.code} value={country.code}>{country.name}</option>)}</>;

  return <section aria-label="Work eligibility details" className="panel">
    <div className="section-title">
      <div><p className="eyebrow">Used to check job eligibility and fit</p><h2>Work eligibility</h2></div>
      <span className={`status-pill ${confirmedNow ? "eligibility-confirmed" : "eligibility-unknown"}`}>{confirmedNow && details.confirmed_at ? `Confirmed by you ${formatDay(details.confirmed_at)}` : "Not confirmed"}</span>
    </div>
    <p className="inline-note">Only details you confirm here are used. Your profile location{profileLocation ? ` ("${profileLocation}")` : ""} is free text and is not treated as confirmed. Work authorization is never assumed from where you live or your nationality; anything you leave blank stays unknown.</p>
    <dl className="listing-facts">
      <div><dt>Country of residence</dt><dd>{details.country_of_residence_name || "Unknown"}</dd></div>
      <div><dt>Authorized to work in</dt><dd>{details.work_authorizations.filter((a) => a.status === "authorized").map((a) => a.country_name).join(", ") || "None confirmed"}</dd></div>
      <div><dt>Not authorized to work in</dt><dd>{details.work_authorizations.filter((a) => a.status === "not_authorized").map((a) => a.country_name).join(", ") || "None recorded"}</dd></div>
      <div><dt>Relocation</dt><dd>{details.relocation_willingness === "willing" ? `Willing${details.relocation_countries.length ? ` (${details.relocation_countries.join(", ")})` : ""}` : details.relocation_willingness === "not_willing" ? "Not willing" : "Unknown"}</dd></div>
      <div><dt>Work arrangements you accept</dt><dd>{details.accepted_work_arrangements.map((value) => ARRANGEMENT_LABELS[value]).join(", ") || "Unknown"}</dd></div>
    </dl>
    {!editing ? <button className="button button-secondary" onClick={() => setEditing(true)} type="button">{confirmedNow ? "Review and update" : "Confirm your details"}</button>
      : <form aria-label="Confirm work eligibility details" className="eligibility-review" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Country of residence"><select value={residence} onChange={(event) => setResidence(event.target.value)}><option value="">Unknown or prefer not to say</option>{countryOptions}</select></Field>
          <Field label="Willing to relocate?"><select value={relocation} onChange={(event) => setRelocation(event.target.value as "" | "willing" | "not_willing")}><option value="">Unknown</option><option value="willing">Willing</option><option value="not_willing">Not willing</option></select></Field>
          {relocation === "willing" && <Field className="full-span" label="Countries you would relocate to" hint="Leave empty if you would consider any country."><select multiple size={5} value={relocationCountries} onChange={(event) => setRelocationCountries(Array.from(event.target.selectedOptions, (option) => option.value))}>{countryOptions}</select></Field>}
          <fieldset className="full-span arrangement-choices"><legend>Work arrangements you accept</legend>{(Object.keys(ARRANGEMENT_LABELS) as WorkArrangement[]).map((value) => <label key={value}><input checked={arrangements.includes(value)} onChange={(event) => setArrangements(event.target.checked ? [...arrangements, value] : arrangements.filter((item) => item !== value))} type="checkbox" /> {ARRANGEMENT_LABELS[value]}</label>)}</fieldset>
          <fieldset className="full-span authorization-rows"><legend>Work authorization by country</legend>
            {authorizations.length === 0 && <p className="muted">No countries recorded. Add only countries where you know your status.</p>}
            {authorizations.map((item, index) => <div className="authorization-row" key={index}>
              <label><span className="sr-only">Country {index + 1}</span><select aria-label={`Authorization country ${index + 1}`} value={item.country_code} onChange={(event) => setAuthorizations(authorizations.map((row, i) => (i === index ? { ...row, country_code: event.target.value } : row)))}><option value="">Choose a country</option>{countryOptions}</select></label>
              <label><span className="sr-only">Status {index + 1}</span><select aria-label={`Authorization status ${index + 1}`} value={item.status} onChange={(event) => setAuthorizations(authorizations.map((row, i) => (i === index ? { ...row, status: event.target.value as WorkAuthorizationStatus } : row)))}><option value="authorized">I am authorized to work there</option><option value="not_authorized">I am not authorized to work there</option></select></label>
              <button className="text-button" onClick={() => setAuthorizations(authorizations.filter((_, i) => i !== index))} type="button">Remove</button>
            </div>)}
            <button className="text-button" onClick={() => setAuthorizations([...authorizations, { country_code: "", status: "authorized" }])} type="button">Add a country</button>
          </fieldset>
          <label className="full-span confirm-check"><input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required type="checkbox" /> I confirm these details are accurate. Blank answers will be treated as unknown.</label>
        </div>
        <div className="form-footer"><button className="text-button" onClick={() => setEditing(false)} type="button">Cancel</button><button className="button button-primary" disabled={!confirmed || busy} type="submit">Confirm details</button></div>
        {names.size === 0 && <p className="muted" role="status">Loading countries…</p>}
      </form>}
  </section>;
}
