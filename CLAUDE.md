# Working on Þing

Þing is a self-hosted CRM for MSP technicians that stores personal data about customer contacts. Read `docs/architecture.md` before changing the design, and keep it current when the design changes.

Þing started from the platform of its sister product Skjald (https://github.com/FragmentedCoder/Skjald-Reporting) and shares its history. The `skjald` remote points there, so platform fixes can be cherry-picked across. Never push to it.

## Workflow

- One branch per phase or larger milestone (for example `phase-1`), with many small, focused commits; never push to `main`.
- Open the pull request as a draft early so progress can be followed, and mark it ready only when everything in it is tested.
- Describe in the pull request what changed and how it was tested.
- Give the user a short status report whenever a task finishes or is interrupted.

## Rules that always apply

- Never commit secrets, real customer data, certificates or private keys. Demo data uses a fictional company (Nordlys), in fixtures, screenshots and examples alike.
- Þing never stores passwords, OTP secrets or keys for customer systems. A system holds a reference to its Devolutions RDM entry, never a credential.
- The security baseline is OWASP ASVS Level 2. New endpoints need authentication, authorisation by role and assignment, input validation and audit logging.
- UI and documents follow `docs/brand/` (tokens, fonts, logo rules). UI labels are plain English, in sentence case. Write **Þing** in product copy; `ting` only where ASCII is required (packages, images, commands, paths, HTTP headers).
