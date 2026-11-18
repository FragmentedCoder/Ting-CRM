import type { CaseKind } from "./customers.js";

/** A detail worth recording for a service: its kind decides how it's filled in. */
export type DetailKind = "text" | "number" | "date" | "yes_no" | "choice";

export interface DetailField {
  key: string;
  label: string;
  kind: DetailKind;
  choices: string[];
  help: string;
}

/** A service in the catalog (backend/app/services.py). */
export interface StandardService {
  id: number;
  /** What Þing looks for, such as "support"; null for one a Manager added. */
  key: string | null;
  name: string;
  description: string;
  details: DetailField[];
  /** How many customers have a copy. */
  used_by: number;
}

export const DETAIL_KINDS: Record<DetailKind, string> = {
  text: "Text",
  number: "Number",
  date: "Date",
  yes_no: "Yes or no",
  choice: "A choice",
};

export const CASE_KINDS: Record<Exclude<CaseKind, "">, string> = {
  monthly: "Monthly",
  standing: "Standing",
  project: "Project",
};

/** A detail's value as words. */
export function showValue(field: Pick<DetailField, "kind">, value: string | number | boolean | null): string {
  if (value === null || value === "") return "—";
  if (field.kind === "yes_no") return value ? "Yes" : "No";
  return String(value);
}
