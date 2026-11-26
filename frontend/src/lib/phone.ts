// Phone numbers: a country code and the number after it, kept as one line of text
// ("+45 12 34 56 78") as the contact's card shows it.

/** The country codes offered, the Nordic ones first; the team's own goes on top. */
export const COUNTRY_CODES: { code: string; name: string }[] = [
  { code: "+45", name: "Denmark" },
  { code: "+46", name: "Sweden" },
  { code: "+47", name: "Norway" },
  { code: "+358", name: "Finland" },
  { code: "+354", name: "Iceland" },
  { code: "+298", name: "Faroe Islands" },
  { code: "+299", name: "Greenland" },
  { code: "+49", name: "Germany" },
  { code: "+31", name: "Netherlands" },
  { code: "+32", name: "Belgium" },
  { code: "+352", name: "Luxembourg" },
  { code: "+33", name: "France" },
  { code: "+44", name: "United Kingdom" },
  { code: "+353", name: "Ireland" },
  { code: "+34", name: "Spain" },
  { code: "+351", name: "Portugal" },
  { code: "+39", name: "Italy" },
  { code: "+41", name: "Switzerland" },
  { code: "+43", name: "Austria" },
  { code: "+48", name: "Poland" },
  { code: "+420", name: "Czechia" },
  { code: "+421", name: "Slovakia" },
  { code: "+36", name: "Hungary" },
  { code: "+372", name: "Estonia" },
  { code: "+371", name: "Latvia" },
  { code: "+370", name: "Lithuania" },
  { code: "+380", name: "Ukraine" },
  { code: "+40", name: "Romania" },
  { code: "+359", name: "Bulgaria" },
  { code: "+30", name: "Greece" },
  { code: "+90", name: "Türkiye" },
  { code: "+1", name: "United States and Canada" },
  { code: "+91", name: "India" },
  { code: "+86", name: "China" },
  { code: "+81", name: "Japan" },
  { code: "+61", name: "Australia" },
];

/** The codes to choose from, the team's default first. One that isn't on the list
 *  (the team's own, or a number's) is offered by its digits alone. */
export function codeChoices(first: string, also = ""): { code: string; name: string }[] {
  const listed = (code: string) => COUNTRY_CODES.find((c) => c.code === code) ?? { code, name: "" };
  const top = [first, also].filter((code, n, all) => code && all.indexOf(code) === n).map(listed);
  return [...top, ...COUNTRY_CODES.filter((c) => !top.some((t) => t.code === c.code))];
}

/** A number as text, taken apart: its country code and the rest. A number written
 *  with "00" for "+" is read the same. One with no country code keeps none (it isn't
 *  given the team's: that would change what was written); an empty one starts on the
 *  team's own. */
export function splitPhone(value: string, first: string): { code: string; number: string } {
  const text = value.trim();
  if (!text) return { code: first, number: "" };
  const plus = text.startsWith("00") ? `+${text.slice(2)}` : text;
  if (!plus.startsWith("+")) return { code: "", number: text };
  const digits = plus.slice(1).replace(/[^0-9]/g, "");
  // The longest code the number starts with: "+358" before "+35".
  const known = [first, ...COUNTRY_CODES.map((c) => c.code)]
    .filter((code) => code && digits.startsWith(code.slice(1)))
    .sort((a, b) => b.length - a.length)[0];
  if (!known) return { code: "", number: text };
  // What follows the code's digits, as it was written.
  let seen = 0;
  let at = 1;
  while (at < plus.length && seen < known.length - 1) {
    if (/[0-9]/.test(plus[at])) seen += 1;
    at += 1;
  }
  return { code: known, number: plus.slice(at).replace(/^[\s\-.]+/, "") };
}

/** A country code and a number as one line: "+45 12 34 56 78". A number typed with
 *  its own code keeps it. */
export function joinPhone(code: string, number: string): string {
  const text = number.trim();
  if (!text || !code || text.startsWith("+") || text.startsWith("00")) return text;
  return `${code} ${text}`;
}
