// Mirrors backend/app/tls.py and backend/app/server_routes.py.

export type TlsMode = "internal" | "own" | "acme";
export type TlsChallenge = "tls-alpn" | "dns";
export type DnsProvider = "cloudflare" | "rfc2136";
export type KeyAlgorithm = "hmac-sha256" | "hmac-sha384" | "hmac-sha512" | "hmac-sha224" | "hmac-sha1";

export interface Certificate {
  subject: string;
  names: string[];
  issuer: string;
  not_after: string;
}

export interface DnsSettings {
  challenge: TlsChallenge;
  dns_provider: DnsProvider;
  rfc2136_server: string;
  rfc2136_key_name: string;
  rfc2136_key_alg: KeyAlgorithm;
}

export interface TlsSettings extends DnsSettings {
  mode: TlsMode;
  acme_email: string;
  certificate: Certificate | null;
}

export interface TlsStatus {
  settings: TlsSettings;
  host: string;
  served: Certificate | null;
  root_url: string | null;
  cloudflare_token_set: boolean;
  rfc2136_key_set: boolean;
}

export interface TlsChoice extends DnsSettings {
  mode: TlsMode;
  acme_email: string;
  certificate_pem: string;
  key_pem: string;
  // Typed here and sent once; empty keeps the saved one.
  cloudflare_token: string;
  rfc2136_key: string;
}

export const MODES: { mode: TlsMode; name: string; about: string }[] = [
  { mode: "internal", name: "Þing's own certificate authority",
    about: "Works at once, offline too. Each computer that uses Þing installs its root certificate once." },
  { mode: "own", name: "Your organisation's certificate",
    about: "A certificate for this address from your own or a public authority, with its key, as PEM files." },
  { mode: "acme", name: "Let's Encrypt",
    about: "Free and automatic, for an address in public DNS: checked over the internet, or through your DNS." },
];

export const KEY_ALGORITHMS: KeyAlgorithm[] = ["hmac-sha256", "hmac-sha384", "hmac-sha512", "hmac-sha224", "hmac-sha1"];

export function choiceFrom(status: TlsStatus): TlsChoice {
  const { certificate: _uploaded, ...settings } = status.settings;
  return { ...settings, certificate_pem: "", key_pem: "", cloudflare_token: "", rfc2136_key: "" };
}

/** The choice as the API takes it: files and secrets only when new ones were given. */
export function tlsBody(choice: TlsChoice) {
  const dns = choice.mode === "acme" && choice.challenge === "dns";
  return {
    mode: choice.mode,
    acme_email: choice.acme_email,
    challenge: choice.challenge,
    dns_provider: choice.dns_provider,
    rfc2136_server: choice.rfc2136_server,
    rfc2136_key_name: choice.rfc2136_key_name,
    rfc2136_key_alg: choice.rfc2136_key_alg,
    certificate_pem: choice.mode === "own" && choice.certificate_pem ? choice.certificate_pem : null,
    key_pem: choice.mode === "own" && choice.key_pem ? choice.key_pem : null,
    cloudflare_token: dns && choice.cloudflare_token ? choice.cloudflare_token : null,
    rfc2136_key: dns && choice.rfc2136_key ? choice.rfc2136_key : null,
  };
}

/** When a certificate runs out, in words (Caddy's own last hours, not days). */
export function expiry(certificate: Certificate, now = Date.now()): string {
  const left = new Date(certificate.not_after).getTime() - now;
  const days = Math.floor(left / 86_400_000);
  const hours = Math.floor(left / 3_600_000);
  if (left <= 0) return "expired";
  if (days >= 1) return `expires in ${days} day${days === 1 ? "" : "s"}`;
  if (hours >= 1) return `expires in ${hours} hour${hours === 1 ? "" : "s"}`;
  return "expires within the hour";
}

export const RESET_COMMAND = "sudo ting admin reset-certificate";
