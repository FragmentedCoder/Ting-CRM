// Mirrors backend/app/backup_routes.py.
import { bytes } from "./format.js";

export type TargetKind = "local" | "smb" | "s3";

export interface BackupTarget {
  // null for one not saved yet: the server gives it one.
  id: string | null;
  kind: TargetKind;
  smb_host: string;
  smb_share: string;
  smb_path: string;
  smb_username: string;
  smb_domain: string;
  s3_endpoint: string;
  s3_bucket: string;
  s3_path: string;
  s3_region: string;
  s3_access_key_id: string;
}

export type RunKind = "backup" | "restore_test" | "backup_check";

export interface BackupRun {
  id: number;
  kind: RunKind;
  target: string | null;
  state: "queued" | "running" | "done" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  requested_by: string | null;
}

export interface TargetStatus {
  target: BackupTarget;
  words: string;
  secret_set: boolean;
  repository: string;
  last_backup: BackupRun | null;
  last_restore_test: BackupRun | null;
}

export interface BackupStatus {
  hour: number;
  keep_days: number;
  targets: TargetStatus[];
  next_backup_at: string | null;
  runs: BackupRun[];
}

/** A target as the form edits it, with its secret as typed (empty keeps the saved one). */
export interface TargetForm extends BackupTarget {
  secret: string;
  secretSet: boolean;
}

export interface PlanForm {
  hour: number;
  keep_days: number;
  targets: TargetForm[];
}

export const KINDS: { kind: TargetKind; name: string; about: string }[] = [
  { kind: "smb", name: "SMB share",
    about: "A folder on a file server or NAS on your network, such as a Windows share." },
  { kind: "s3", name: "S3-compatible storage",
    about: "A bucket at Amazon S3, Backblaze B2, MinIO, Wasabi or similar." },
  { kind: "local", name: "This server",
    about: "The backup folder on this server. It doesn't survive losing the server's disk." },
];

export function newTarget(kind: TargetKind): TargetForm {
  return {
    id: null, kind, secret: "", secretSet: false,
    smb_host: "", smb_share: "", smb_path: "ting", smb_username: "", smb_domain: "",
    s3_endpoint: "", s3_bucket: "", s3_path: "ting", s3_region: "", s3_access_key_id: "",
  };
}

export function planForm(status: BackupStatus): PlanForm {
  return {
    hour: status.hour,
    keep_days: status.keep_days,
    targets: status.targets.map((t) => ({ ...t.target, secret: "", secretSet: t.secret_set })),
  };
}

/** The plan as the API takes it: each target's secret only when one was typed. */
export function planBody(form: PlanForm) {
  return {
    hour: form.hour,
    keep_days: form.keep_days,
    targets: form.targets.map(({ secret, secretSet: _saved, ...target }) => ({
      ...target,
      smb_password: target.kind === "smb" && secret ? secret : null,
      s3_secret_access_key: target.kind === "s3" && secret ? secret : null,
    })),
  };
}

export const RUN_NAMES: Record<RunKind, string> = {
  backup: "Backup",
  restore_test: "Restore test",
  backup_check: "Connection check",
};

/** What a run did, in a line. */
export function runSummary(run: BackupRun): string {
  if (run.state === "queued") return run.error ? `Will try again: ${run.error}` : "Waiting for the worker";
  if (run.state === "running") return "Running";
  if (run.state === "failed") return run.error ?? "Failed";
  const result = run.result ?? {};
  if (run.kind === "backup") {
    return `${bytes(Number(result.bytes ?? 0))} backed up (${bytes(Number(result.added ?? 0))} new), ` +
      `snapshot ${String(result.snapshot ?? "")}`;
  }
  if (run.kind === "restore_test") {
    return `Restored snapshot ${String(result.snapshot ?? "")}: the database and ` +
      `${Number(result.audit_entries ?? 0).toLocaleString("en-GB")} audit log entries check out`;
  }
  const made = result.repository_made ? "Made a new repository. " : "";
  return `${made}Reached it: ${Number(result.snapshots ?? 0)} snapshots there`;
}

/** An hour in UTC, with what it is here today. */
export function hourLabel(hour: number): string {
  const at = new Date();
  at.setUTCHours(hour, 0, 0, 0);
  const here = at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${String(hour).padStart(2, "0")}:00 UTC (${here} here)`;
}
