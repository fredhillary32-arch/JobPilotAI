import { useState, type FormEvent } from "react";

import { api } from "./api/client";
import type { AtsRequirement, SkillCategory, SkillConfirmationInput, SkillResponse, WorkExperience } from "./api/types";

type RunAction = (action: () => Promise<unknown>, success?: string, pending?: string) => Promise<boolean>;

export const RESPONSE_LABELS: Record<SkillResponse, string> = {
  has_skill: "I have this skill. Add it to my profile.",
  used_in_role: "I have used this skill in a role or project.",
  needs_details: "I have this skill but need to add details later.",
  not_possessed: "I do not have this skill.",
  unsure: "Not sure. Leave it unverified.",
};
const SHORT_LABELS: Record<SkillResponse, string> = {
  has_skill: "You have this skill",
  used_in_role: "You used it in a role or project",
  needs_details: "You have it; details to follow",
  not_possessed: "You do not have this",
  unsure: "Left unverified",
};
const CATEGORY_LABELS: Record<SkillCategory, string> = {
  technical: "Technical skill",
  tool: "Tool or platform",
  communication: "Communication",
  customer_service: "Customer service",
  work_style: "Work style or personal quality",
  language: "Language",
  other: "Other",
};

function defaultCategory(requirement: AtsRequirement): SkillCategory {
  if (requirement.category === "communication") return "communication";
  if (requirement.category === "work_style") return "work_style";
  if (requirement.category === "tool") return "tool";
  return "technical";
}

function defaultName(requirement: AtsRequirement): string {
  if (requirement.terms.length) return requirement.terms.slice(0, 3).join(", ");
  const first = requirement.text.split(/(?<=[.!?])\s/)[0].replace(/[.!?]$/, "");
  return first.length <= 80 ? first : `${first.slice(0, 77)}…`;
}

// Records what the candidate says is true about one requirement. JobPilot never
// treats the answer as independent proof, and never adds a "no" or "not sure" to a CV.
export function RequirementAnswer({ profileId, jobId, requirement, experiences, busy, runAction }: {
  profileId: string;
  jobId: string;
  requirement: AtsRequirement;
  experiences: WorkExperience[];
  busy: boolean;
  runAction: RunAction;
}) {
  const existing = requirement.confirmation ?? null;
  const [open, setOpen] = useState(false);
  const [response, setResponse] = useState<SkillResponse>(existing?.response ?? "has_skill");
  const [skillName, setSkillName] = useState(existing?.skill_name ?? defaultName(requirement));
  const [category, setCategory] = useState<SkillCategory>(existing?.category ?? defaultCategory(requirement));
  const [proficiency, setProficiency] = useState(existing?.proficiency_level ?? "");
  const [roleId, setRoleId] = useState(existing?.work_experience_id ?? "");
  const [projectName, setProjectName] = useState(existing?.project_name ?? "");
  const [example, setExample] = useState(existing?.example ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const claims = response === "has_skill" || response === "used_in_role" || response === "needs_details";

  function validate(): Record<string, string> {
    const found: Record<string, string> = {};
    if (!skillName.trim()) found.skillName = "Name the skill in a few words.";
    if (response === "used_in_role") {
      if (!roleId && !projectName.trim()) found.where = "Choose the role, or name the project, where you used it.";
      if (example.trim().split(/\s+/).filter(Boolean).length < 6) found.example = "Describe what you did in your own words (at least six words). Only true statements: this may appear on your CV.";
    }
    return found;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length) return;
    const payload: SkillConfirmationInput = {
      skill_name: skillName.trim(), category, response,
      proficiency_level: claims && proficiency ? proficiency as SkillConfirmationInput["proficiency_level"] : null,
      work_experience_id: response === "used_in_role" && roleId ? roleId : null,
      project_name: response === "used_in_role" && !roleId && projectName.trim() ? projectName.trim() : null,
      example: response === "used_in_role" || (response !== "not_possessed" && response !== "unsure" && example.trim()) ? example.trim() || null : null,
    };
    const saved = await runAction(
      () => existing
        ? api.updateConfirmation(profileId, existing.id, payload)
        : api.createConfirmation(profileId, { ...payload, job_description_id: jobId, requirement_key: requirement.key }),
      claims ? "Saved as your own statement. The match report has been updated; generate a new draft to use it." : "Your answer was saved. This requirement stays off your CV.",
      "Saving your answer…",
    );
    if (saved) setOpen(false);
  }

  function withdraw() {
    if (!existing) return;
    void runAction(() => api.withdrawConfirmation(profileId, existing.id), "Answer withdrawn. It is kept in your history but no longer used.", "Withdrawing your answer…");
  }

  const role = existing?.work_experience_id ? experiences.find((item) => item.id === existing.work_experience_id) : undefined;
  return <div className="requirement-answer">
    {existing && !open && <p className="answer-summary">
      <span className="ats-basis">Your answer</span> {SHORT_LABELS[existing.response]}{existing.skill_name ? `: ${existing.skill_name}` : ""}
      {role ? ` (at ${role.employer})` : existing.project_name ? ` (project: ${existing.project_name})` : ""}.
      <span className="muted"> Your own statement, not independently verified.</span>
      {existing.example && <q className="answer-example">{existing.example}</q>}
    </p>}
    {!open ? <div className="row-actions">
      <button className="text-button" disabled={busy} onClick={() => setOpen(true)} type="button">{existing ? "Edit answer" : "Answer this requirement"}</button>
      {existing && <button className="text-button danger-text-button" disabled={busy} onClick={withdraw} type="button">Withdraw answer</button>}
    </div> : <form aria-label={`Your answer: ${requirement.text.slice(0, 60)}`} className="answer-form" noValidate onSubmit={submit}>
      <fieldset>
        <legend>What is true for you?</legend>
        {(Object.keys(RESPONSE_LABELS) as SkillResponse[]).map((value) => <label className="radio-field" key={value}>
          <input checked={response === value} name={`response-${requirement.key}`} onChange={() => setResponse(value)} type="radio" value={value} /> {RESPONSE_LABELS[value]}
        </label>)}
      </fieldset>
      <div className="form-grid">
        <label className="field"><span>Skill or competency</span><input aria-invalid={Boolean(errors.skillName)} maxLength={200} value={skillName} onChange={(event) => setSkillName(event.target.value)} />{errors.skillName && <small className="field-error">{errors.skillName}</small>}</label>
        <label className="field"><span>Category</span><select value={category} onChange={(event) => setCategory(event.target.value as SkillCategory)}>{(Object.keys(CATEGORY_LABELS) as SkillCategory[]).map((value) => <option key={value} value={value}>{CATEGORY_LABELS[value]}</option>)}</select></label>
        {claims && <label className="field"><span>Your level (optional)</span><select value={proficiency} onChange={(event) => setProficiency(event.target.value)}><option value="">Not stated</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option><option value="expert">Expert</option></select></label>}
        {response === "used_in_role" && <>
          <label className="field"><span>Role where you used it</span><select aria-invalid={Boolean(errors.where)} value={roleId} onChange={(event) => setRoleId(event.target.value)}><option value="">A project, not a recorded role</option>{experiences.map((item) => <option key={item.id} value={item.id}>{item.job_title} at {item.employer}</option>)}</select></label>
          {!roleId && <label className="field"><span>Project name</span><input aria-invalid={Boolean(errors.where)} maxLength={200} value={projectName} onChange={(event) => setProjectName(event.target.value)} /></label>}
          {errors.where && <small className="field-error full-span">{errors.where}</small>}
        </>}
        {claims && <label className="field full-span"><span>{response === "used_in_role" ? "What you did (your own words)" : "Supporting details (optional)"}</span>
          <textarea aria-invalid={Boolean(errors.example)} maxLength={2000} rows={3} value={example} onChange={(event) => setExample(event.target.value)} />
          <small>{response === "used_in_role" && roleId ? "Written as a CV statement, for example: \"Built rapport with members on support calls.\" It can become a bullet for that role; nothing is added to it." : "Kept with your answer. It is never presented as an achievement or a number of years unless you recorded those."}</small>
          {errors.example && <small className="field-error">{errors.example}</small>}
        </label>}
      </div>
      <div className="row-actions">
        <button className="button button-primary" disabled={busy} type="submit">Save answer</button>
        <button className="button button-secondary" disabled={busy} onClick={() => { setOpen(false); setErrors({}); }} type="button">Cancel</button>
      </div>
    </form>}
  </div>;
}
