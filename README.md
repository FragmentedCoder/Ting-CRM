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

- **Gather** — customers (and the companies in a group, filled in from the CVR registry), sites and contacts with their roles (who decides, who may be contacted), and each customer's systems: what runs on what, and where. Þing never stores passwords, licence keys or other secrets.
- **Agree** — standard services (Support, Backup, Microsoft 365, Updates and more) that each customer gets a copy of with its own details, because no two customers' backup looks alike; the case number the work goes on; agreements and SLA; and renewals of licences, feature keys and certificates, with a decision on each.
- **Remember** — a work log in plain text, tasks and recurring work (updates, restore tests, NIS2 documentation) that schedule themselves, documents and uploaded emails on a timeline, and compliance checklists (NIS2, GDPR, TISAX) that say where to find what an auditor asks for.
- **Overview first** — global search by name, CVR, contact, phone, email domain or case number from every screen (`Ctrl+K`); a customer page that shows in five seconds the support they have, our services, the case number, pinned warnings and the decision-maker; My work for each technician; and a wall display of what's most pressing for the department's TV.
- **Security first** — per-customer encryption keys, MFA for every account, need-to-know access, and a tamper-evident audit log.
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
| Phase 2 | Core CRM: customers and their companies, CVR lookup, sites, contacts, pinned warnings; systems; standard services and each customer's own; support and case numbers; agreements and SLA; the work log; the customer page and its timeline; global search |
| Phase 3 | Tasks, recurring tasks and renewals; warnings in Þing and by email; My work; the wall display |
| Phase 4 | Documents and uploaded emails; compliance frameworks and checklists; CSV/Excel import |
| 1.0 | Release gate: one-command install, ASVS Level 2 test plan passes, restore test green, the fictional demo company's data imports and works end to end |
| After 1.0 | Danish, more warning channels (such as NTFY), prices once decided, sales and management roles |

The design is described in [docs/architecture.md](docs/architecture.md).

## Tech stack

SvelteKit and TypeScript · Python and FastAPI · SQLite with SQLCipher · restic · Caddy · Docker Compose · Sigstore cosign

## Contributing and security

Ideas, questions and bug reports are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md), which also says how to run the tests, and the [code of conduct](CODE_OF_CONDUCT.md). Please report security problems privately as described in [SECURITY.md](SECURITY.md), never in a public issue.

## Licence

Þing is licensed under the [GNU Affero General Public License v3.0](LICENSE), like Skjald, whose code it started from. You may use, study, change and share it. If you share a modified version, or run one as a service for others, you must publish its source under the same licence.
