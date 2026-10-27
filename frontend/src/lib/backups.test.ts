import { describe, expect, it } from "vitest";
import { newTarget, planBody, planForm, type BackupStatus } from "./backups";

const status: BackupStatus = {
  hour: 3,
  keep_days: 30,
  next_backup_at: null,
  runs: [],
  targets: [
    { target: { ...newTarget("local"), id: "local" }, words: "this server", secret_set: false,
      repository: "/backups/restic", last_backup: null, last_restore_test: null },
    { target: { ...newTarget("smb"), id: "smb", smb_host: "nas", smb_share: "b", smb_username: "u" },
      words: "the SMB share \\\\nas\\b", secret_set: true, repository: "rclone:tingsmb:b/ting",
      last_backup: null, last_restore_test: null },
  ],
};

describe("the backup plan form", () => {
  it("starts from what's saved, with no secrets typed", () => {
    const form = planForm(status);
    expect(form.hour).toBe(3);
    expect(form.targets.map((t) => [t.id, t.secret, t.secretSet])).toEqual([
      ["local", "", false], ["smb", "", true]]);
  });

  it("sends a secret only when one was typed, under the right name", () => {
    const form = planForm(status);
    let body = planBody(form);
    expect(body.targets[1]).toMatchObject({ id: "smb", smb_password: null, s3_secret_access_key: null });
    expect(body.targets[1]).not.toHaveProperty("secret");
    form.targets[1].secret = "nas password";
    form.targets.push({ ...newTarget("s3"), secret: "s3cret" });
    body = planBody(form);
    expect(body.targets[1]).toMatchObject({ smb_password: "nas password", s3_secret_access_key: null });
    expect(body.targets[2]).toMatchObject({ id: null, kind: "s3", smb_password: null, s3_secret_access_key: "s3cret" });
  });
});
