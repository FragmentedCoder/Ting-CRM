<p align="center">
  <img src="docs/brand/ting-mark.svg" width="96" height="96" alt="Þing">
</p>

<h1 align="center">Þing</h1>

<p align="center"><em>Gather. Agree. Remember.</em></p>

Þing is a self-hosted CRM for the technicians at a managed service provider. When a customer calls, a technician should be able to answer three questions in seconds: **what the customer pays for, whether this task is covered by their agreement or billable, and which systems we run for them.** Þing keeps the people, agreements, systems and history of every customer in one place. Sales and management views come later, on the same data.

The *þing* (thing) was the Norse assembly: free people met in a ring of standing stones to settle disputes, make agreements and hear the law spoken. Þing is where everything about a customer is gathered, agreed and remembered.

> [!NOTE]
> **Status: the platform is in place; the CRM comes next.** The first pre-release has what Þing stands on: the installer and setup wizard, sign-in with MFA, roles, customers with their sites and contacts, encryption keys, the audit log, backups and updates. Agreements, coverage, systems and the timeline come in Phases 2 and 3. Pre-releases are for trying out: don't trust them with real customer data before 1.0. Watch the repository to hear about new releases.

## What runs today

- **One-command install** on Ubuntu Server LTS with Docker Compose, from signed images, and a setup wizard for the company, the first Administrator with MFA, the recovery kit, backups, email and the certificate.
- **Sign-in with MFA for everyone**: passkeys and hardware keys, authenticator apps and recovery codes; Argon2id passwords checked against Have I Been Pwned; lockout, session limits, step-up confirmation for changes that lower security, and optional IP allowlists.
- **Roles and need-to-know access**: Administrators run everything; Managers run customers, the service catalog and agreements; technicians see and update only the customers they're assigned to; auditors read the audit log.
- **Customers** with sites and contacts, each customer encrypted with its own key, so deleting one leaves nothing readable behind.
- **A tamper-evident audit log**: hash-chained, timestamped daily by an outside authority, with a viewer and CSV export.
- **Encrypted backups** with restic to the server itself, SMB shares or S3 storage, a weekly restore test, and updates that back up first and roll back if the new version doesn't start.
- **Light and dark mode**, at desktop and phone width.

## What it will do

- **Gather** — customers, sites and contacts (with who may be contacted), and the systems we run for each customer, each with a link to its entry in Devolutions Remote Desktop Manager. Þing never stores passwords or other secrets.
- **Agree** — agreements, their lines and prices, and coverage rules, so a technician gets a clear answer: **Covered**, **Billable** or **Not covered**, with the rule text and the agreement line it comes from. A system that no agreement line pays for is flagged.
- **Remember** — a timeline of calls, meetings, visits and notes, with follow-up tasks; pinned warnings that must never be missed; and compliance records (NIS2 class, data processing agreement, reviews).
- **Overview first** — global search by name, CVR, contact, phone or email domain from every screen (`Ctrl+K`), a customer page that answers the three questions at a glance, and a home screen with tasks, notice deadlines and renewals.
- **Security first** — per-customer encryption keys, MFA for every account, need-to-know access by customer assignment, and a tamper-evident audit log.
- **Easy to run** — one command installs it on an Ubuntu VM with Docker Compose. Updates take a backup first and roll back on failure; backups are encrypted and restore-tested.

## Try it

On an Ubuntu Server LTS VM (4 vCPU, 8 GB RAM, 100 GB disk); until the first full release it installs the newest pre-release, which is for trying out, not for real data:

```sh
curl -fsSL https://raw.githubusercontent.com/FragmentedCoder/Ting-CRM/main/install.sh | sudo bash
```

The installer installs Docker Engine if needed, generates the master key, downloads the release and checks its files and every image against the release's signatures, starts Þing, and prints a one-time setup token. Open the address followed by `/setup` and the wizard takes it from there: the company, the first Administrator with MFA, the recovery kit, backups, email and the certificate. Until you choose another certificate, Þing's own authority signs it: install `https://<address>/ting-root.crt` as a trusted root on each computer that uses it. Each release's notes show how to check the installer with cosign before running it.

To try the newest code, install from a checkout instead: it builds the images there.

```sh
git clone https://github.com/FragmentedCoder/Ting-CRM.git
cd Ting-CRM
sudo ./install.sh --address https://ting.example.internal
```

On the server, `sudo ting help` lists what the web UI can't do: status, logs, backups and restores, updates, and replacing the master key; `sudo ting update` moves to the newest release.

## Roadmap

| Step | Scope |
| --- | --- |
| Phase 0 ✓ | Repository from Skjald's platform, renamed and rebranded; CI and signed builds; documentation and brand |
| Phase 1 ✓ | The platform made Þing's: Skjald's projects and report roles removed; Þing's roles (Administrator, Manager, Technician, Auditor) and plain assignments; the first pre-release |
| Phase 2 | Core CRM: customers, sites, contacts; service catalog; agreements, lines and coverage rules; systems with RDM references; timeline and tasks; global search; customer page; home |
| Phase 3 | Compliance, coverage check, CSV/Excel import, "systems no agreement pays for" and renewal warnings |
| 1.0 | Release gate: one-command install, ASVS Level 2 test plan passes, restore test green, the fictional demo company's data imports and works end to end |
| After 1.0 | Microsoft 365 mail on the timeline, CVR lookup, maintenance and update tracking per system, sales and management roles |

The design is described in [docs/architecture.md](docs/architecture.md).

## Tech stack

SvelteKit and TypeScript · Python and FastAPI · SQLite with SQLCipher · restic · Caddy · Docker Compose · Sigstore cosign

## Contributing and security

Ideas, questions and bug reports are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md), which also says how to run the tests, and the [code of conduct](CODE_OF_CONDUCT.md). Please report security problems privately as described in [SECURITY.md](SECURITY.md), never in a public issue.

## Licence

Þing is licensed under the [GNU Affero General Public License v3.0](LICENSE), like Skjald, whose code it started from. You may use, study, change and share it. If you share a modified version, or run one as a service for others, you must publish its source under the same licence.
