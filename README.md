<p align="center">
  <img src="docs/brand/ting-mark.svg" width="96" height="96" alt="Þing">
</p>

<h1 align="center">Þing</h1>

<p align="center"><em>Gather. Agree. Remember.</em></p>

Þing is a self-hosted CRM for the technicians at a managed service provider. When a customer calls, a technician should be able to answer three questions in seconds: **what the customer pays for, whether this task is covered by their agreement or billable, and which systems we run for them.** Þing keeps the people, agreements, systems and history of every customer in one place. Sales and management views come later, on the same data.

The *þing* (thing) was the Norse assembly: free people met in a ring of standing stones to settle disputes, make agreements and hear the law spoken. Þing is where everything about a customer is gathered, agreed and remembered.

> [!NOTE]
> **Status: Phase 1 of the road to 1.0.** Þing starts from the platform of its sister product [Skjald](https://github.com/FragmentedCoder/Skjald-Reporting): install, setup wizard, sign-in with MFA, Þing's roles (Administrator, Technician, Auditor), customers with their sites and contacts, encryption keys, the audit log and backups already run. The CRM itself (agreements, coverage, systems, timeline) comes in Phases 2 and 3. Don't trust it with real customer data before 1.0.

## What it will do

- **Gather** — customers, sites and contacts (with who may be contacted), and the systems we run for each customer, each with a link to its entry in Devolutions Remote Desktop Manager. Þing never stores passwords or other secrets.
- **Agree** — agreements, their lines and prices, and coverage rules, so a technician gets a clear answer: **Covered**, **Billable** or **Not covered**, with the rule text and the agreement line it comes from. A system that no agreement line pays for is flagged.
- **Remember** — a timeline of calls, meetings, visits and notes, with follow-up tasks; pinned warnings that must never be missed; and compliance records (NIS2 class, data processing agreement, reviews).
- **Overview first** — global search by name, CVR, contact, phone or email domain from every screen (`Ctrl+K`), a customer page that answers the three questions at a glance, and a home screen with tasks, notice deadlines and renewals.
- **Security first** — per-customer encryption keys, MFA for every account, need-to-know access by customer assignment, and a tamper-evident audit log.
- **Easy to run** — one command installs it on an Ubuntu VM with Docker Compose. Updates take a backup first and roll back on failure; backups are encrypted and restore-tested.

## Try it

There is no release yet. To try the newest code on an Ubuntu Server LTS VM (4 vCPU, 8 GB RAM, 100 GB disk), install from a checkout: it builds the images there.

```sh
git clone https://github.com/FragmentedCoder/Ting-CRM.git
cd Ting-CRM
sudo ./install.sh --address https://ting.example.internal
```

The installer installs Docker Engine if needed, generates the master key, starts Þing and prints a one-time setup token. Open the address followed by `/setup` and the wizard takes it from there: the company, the first Administrator with MFA, the recovery kit, backups, email and the certificate. Until you choose another certificate, Þing's own authority signs it: install `https://<address>/ting-root.crt` as a trusted root on each computer that uses it.

On the server, `sudo ting help` lists what the web UI can't do: status, logs, backups and restores, updates, and replacing the master key.

## Roadmap

| Step | Scope |
| --- | --- |
| Phase 0 | Repository from Skjald's platform, renamed and rebranded; CI and signed builds; documentation and brand |
| Phase 1 | The platform made Þing's: Skjald's projects and report roles removed, Þing's roles (Administrator, Technician, Auditor) and plain assignments |
| Phase 2 | Core CRM: customers, sites, contacts; service catalog; agreements, lines and coverage rules; systems with RDM references; timeline and tasks; global search; customer page; home |
| Phase 3 | Compliance, coverage check, CSV/Excel import, "systems no agreement pays for" and renewal warnings |
| 1.0 | Release gate: one-command install, ASVS Level 2 test plan passes, restore test green, the fictional demo company's data imports and works end to end |
| After 1.0 | Microsoft 365 mail on the timeline, CVR lookup, maintenance and update tracking per system, sales and management roles |

The design is described in [docs/architecture.md](docs/architecture.md).

## Tech stack

SvelteKit and TypeScript · Python and FastAPI · SQLite with SQLCipher · restic · ClamAV · Caddy · Docker Compose

## Contributing and security

Ideas, questions and bug reports are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md), which also says how to run the tests, and the [code of conduct](CODE_OF_CONDUCT.md). Please report security problems privately as described in [SECURITY.md](SECURITY.md), never in a public issue.

## Licence

Þing is licensed under the [GNU Affero General Public License v3.0](LICENSE), like Skjald, whose code it started from. You may use, study, change and share it. If you share a modified version, or run one as a service for others, you must publish its source under the same licence.
