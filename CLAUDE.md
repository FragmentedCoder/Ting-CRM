# Working on Þing

Þing is a self-hosted report builder that stores sensitive customer data. Read `docs/architecture.md` before changing the design, and keep it current when the design changes.

## Workflow

- One branch per phase or larger milestone (for example `phase-0`), with many small, focused commits; never push to `main`.
- Open the pull request as a draft early so progress can be followed, and mark it ready only when everything in it is tested.
- Describe in the pull request what changed and how it was tested.

## Rules that always apply

- Never commit secrets, real customer data, certificates or private keys. Demo data and templates use a fictional company.
- The security baseline is OWASP ASVS Level 2. New endpoints need authentication, authorisation by role and assignment, input validation and audit logging.
- The PDF renderer must never get network access, and template expressions must never execute code.
- UI and reports follow `docs/brand/` (tokens, fonts, logo rules). UI labels are plain English, in sentence case.
