import type { FullAutoFill } from "svelte/elements";
import type { Role } from "./roles";

/** Work details colleagues see beside someone's name (the same for Your account). */
export interface Profile {
  display_name: string;
  first_name: string | null;
  middle_name: string | null;
  last_name: string | null;
  job_title: string | null;
  department: string | null;
  email: string | null;
  phone: string | null;
}

export const PROFILE_FIELDS: {
  key: Exclude<keyof Profile, "display_name">;
  label: string;
  type?: "email" | "tel";
  autocomplete: FullAutoFill;
}[] = [
  { key: "first_name", label: "First name", autocomplete: "given-name" },
  { key: "middle_name", label: "Middle name", autocomplete: "additional-name" },
  { key: "last_name", label: "Last name", autocomplete: "family-name" },
  { key: "job_title", label: "Job title", autocomplete: "organization-title" },
  { key: "department", label: "Department", autocomplete: "off" },
  { key: "email", label: "Work email", type: "email", autocomplete: "email" },
  { key: "phone", label: "Work phone", type: "tel", autocomplete: "tel" },
];

export type ProfileForm = Record<keyof Profile, string>;

export function profileForm(profile: Profile): ProfileForm {
  return {
    display_name: profile.display_name,
    first_name: profile.first_name ?? "",
    middle_name: profile.middle_name ?? "",
    last_name: profile.last_name ?? "",
    job_title: profile.job_title ?? "",
    department: profile.department ?? "",
    email: profile.email ?? "",
    phone: profile.phone ?? "",
  };
}

export interface UserSummary extends Profile {
  id: number;
  username: string;
  avatar_url: string | null;
  roles: Role[];
  is_active: boolean;
  is_break_glass: boolean;
  locked: boolean;
  second_factors: number;
  mfa_required: boolean;
  password_change_required: boolean;
  last_sign_in_at: string | null;
  created_at: string;
}

export interface SessionRow {
  id: number;
  created_at: string;
  last_seen_at: string;
  ip: string | null;
  user_agent: string | null;
  second_factor_done: boolean;
  current: boolean;
}

export interface UserDetail extends UserSummary {
  password_expires_at: string | null;
  factors: {
    id: number;
    kind: "totp" | "webauthn";
    label: string;
    created_at: string;
    last_used_at: string | null;
  }[];
  recovery_codes_left: number;
  recovery_code_reusable: boolean;
  sessions: SessionRow[];
}

/** A new or reset password: Þing's random one is shown once; a chosen one never is. */
export interface PasswordResult {
  user: UserDetail;
  temporary_password: string | null;
  expires_at: string | null;
}

type Tone = "ok" | "warning" | "critical" | "info" | "neutral";

/** The one status that matters most, as a word and a tone. */
export function userStatus(user: UserSummary): { tone: Tone; text: string } {
  if (!user.is_active) return { tone: "critical", text: "Disabled" };
  if (user.locked) return { tone: "critical", text: "Locked" };
  if (user.password_change_required) return { tone: "warning", text: "Awaiting first sign-in" };
  if (user.mfa_required && user.second_factors === 0) {
    return { tone: "warning", text: "Multifactor not set up" };
  }
  return { tone: "ok", text: "Active" };
}

/** How an administrator sets someone's password: Þing's random one, or one they type. */
export interface PasswordChoice {
  mode: "random" | "chosen";
  password: string;
  repeat: string;
  mustChange: boolean;
}

export function newPasswordChoice(): PasswordChoice {
  return { mode: "random", password: "", repeat: "", mustChange: true };
}

/** The request fields for a choice, or a reason it can't be sent yet. */
export function passwordFields(
  choice: PasswordChoice,
): { password?: string; must_change_password?: boolean } | string {
  if (choice.mode === "random") return {};
  if (choice.password !== choice.repeat) return "The two passwords don't match.";
  return { password: choice.password, must_change_password: choice.mustChange };
}
