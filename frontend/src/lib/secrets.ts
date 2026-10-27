/** Text files for secrets shown once: what the Copy and Download buttons hand over. */

export function recoveryCodesText(username: string, codes: string[], reusable = false): string {
  if (reusable) {
    return [
      "Þing break-glass recovery code",
      `For ${username}, the break-glass Administrator. It lets you sign in if you lose your`,
      "phone or key, as often as you need. On the server, sudo ting admin recovery-code",
      "makes a new one, and this one stops working.",
      "",
      ...codes,
      "",
    ].join("\n");
  }
  return [
    "Þing recovery codes",
    `For ${username}. Each code lets you sign in once if you lose your phone or key.`,
    "",
    ...codes,
    "",
  ].join("\n");
}

/** How new recovery codes are introduced: ten one-time codes, or the break-glass
 * Administrator's one code that works every time. */
export function recoveryCodesWording(reusable: boolean) {
  return reusable
    ? {
        heading: "Save your recovery code",
        intro:
          "If you lose your phone or key, this code lets you sign in, as often as you need. " +
          "It's shown only now: keep it with the recovery kit.",
        confirmation: "I have saved this code somewhere safe",
      }
    : {
        heading: "Save your recovery codes",
        intro: "If you lose your phone or key, each code lets you sign in once. They are shown only now.",
        confirmation: "I have saved these codes somewhere safe",
      };
}

export interface RecoveryKit {
  master_key: string;
  backup_key: string;
  address: string;
  company_name: string | null;
  shown_at: string;
}

export function recoveryKitText(kit: RecoveryKit): string {
  return [
    "Þing recovery kit",
    `${kit.company_name ?? "Þing"} · ${kit.address} · created ${kit.shown_at.slice(0, 10)}`,
    "",
    "Keep this offline or in your password manager, never on the Þing server.",
    "Without both keys, no backup of this server can be restored.",
    "",
    `Master key: ${kit.master_key}`,
    `Backup key: ${kit.backup_key}`,
    "",
  ].join("\n");
}
