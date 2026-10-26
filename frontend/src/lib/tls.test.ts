import { describe, expect, it } from "vitest";
import { mailBody, type MailServer } from "./mail.js";
import { expiry, tlsBody, type Certificate, type TlsChoice } from "./tls.js";

const NOW = Date.parse("2026-10-25T12:00:00Z");

function certificate(notAfter: string): Certificate {
  return { subject: "ting.example.com", names: [], issuer: "Test CA", not_after: notAfter };
}

describe("expiry", () => {
  it("says how long a certificate has left", () => {
    expect(expiry(certificate("2027-01-23T12:00:00Z"), NOW)).toBe("expires in 90 days");
    expect(expiry(certificate("2026-10-26T13:00:00Z"), NOW)).toBe("expires in 1 day");
    expect(expiry(certificate("2026-10-25T23:59:00Z"), NOW)).toBe("expires in 11 hours");
    expect(expiry(certificate("2026-10-25T13:30:00Z"), NOW)).toBe("expires in 1 hour");
    expect(expiry(certificate("2026-10-25T12:20:00Z"), NOW)).toBe("expires within the hour");
    expect(expiry(certificate("2026-10-24T12:00:00Z"), NOW)).toBe("expired");
  });
});

describe("tlsBody", () => {
  const files: TlsChoice = {
    mode: "own", certificate_pem: "CERT", key_pem: "KEY", acme_email: "",
    challenge: "dns", dns_provider: "cloudflare", rfc2136_server: "", rfc2136_key_name: "",
    rfc2136_key_alg: "hmac-sha256", cloudflare_token: "TOKEN", rfc2136_key: "",
  };

  it("sends files only for an own certificate, and only new ones", () => {
    expect(tlsBody(files)).toMatchObject({ certificate_pem: "CERT", key_pem: "KEY" });
    expect(tlsBody({ ...files, mode: "internal" })).toMatchObject({ certificate_pem: null, key_pem: null });
    expect(tlsBody({ ...files, certificate_pem: "", key_pem: "" }))
      .toMatchObject({ certificate_pem: null, key_pem: null });
  });

  it("sends DNS secrets only for the DNS challenge, and only new ones", () => {
    expect(tlsBody({ ...files, mode: "acme" })).toMatchObject({ cloudflare_token: "TOKEN", rfc2136_key: null });
    expect(tlsBody({ ...files, mode: "acme", challenge: "tls-alpn" })).toMatchObject({ cloudflare_token: null });
    expect(tlsBody({ ...files, mode: "internal" })).toMatchObject({ cloudflare_token: null });
    expect(tlsBody({ ...files, mode: "acme", cloudflare_token: "" })).toMatchObject({ cloudflare_token: null });
  });
});

describe("mailBody", () => {
  const server: MailServer = { host: "smtp.example.com", port: 587, security: "starttls",
    username: "ting", from_address: "ting@example.com", from_name: "" };

  it("keeps the saved password unless a new one is typed", () => {
    expect(mailBody(server, "").password).toBeNull();
    expect(mailBody(server, "new").password).toBe("new");
  });
});
