<p align="center">
  <img src="docs/brand/ting-mark.svg" width="96" height="96" alt="Þing">
</p>

<h1 align="center">Þing</h1>

<p align="center"><em>Reports worth keeping.</em></p>

Þing is a self-hosted, template-driven report builder for IT, MSP and security work: security incident reports, storage device destruction certificates, vulnerability assessments and similar. A technician picks a customer project and a template, answers the template's questions, reviews the generated PDF, signs it and delivers it to the customer.

A *skald* (Danish *ting*) was the Norse poet who turned events into a lasting record. Þing does the same for technical work.

> [!NOTE]
> **Status: Phase 1 of the road to 1.0.** The platform runs: install, setup wizard, sign-in with MFA, roles, customers and projects, encryption keys, the audit log and backups. Templates and reports come in Phases 2 and 3, so Þing can't make a report yet. Don't trust it with real customer data before 1.0. Watch the repository to hear about the first release.

## What it will do

- **Template builder** — a question form, a drag-and-drop document layout, and visual logic (IF / ELSE IF / ELSE, SWITCH, AND / OR / XOR, regular expressions, text replacement) on top of a sandboxed expression language that never runs code.
- **Auto-fill** — customer and project details are typed once and filled into every report. Lookup tables cover things like CVSS severity and end-of-life dates.
- **Signed reports** — PDF/A output with PAdES signatures, trusted timestamps and long-term validation. Technician, reviewer and company signatures, set per template.
- **Delivery** — download, email, password-protected PDF, or an expiring secure link with an access code.
- **Security first** — per-customer encryption keys, MFA for every account, need-to-know access and a tamper-evident audit log.
- **Templates as files** — export, import and share templates as single `.ting` files.
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

On the server, `sudo ting help` lists what the web UI can't do: status, logs, backups and restores, updates, and replacing the master key.

## Roadmap

| Release | Scope |
| --- | --- |
| 1.0 | Platform (installer, sign-in, MFA, roles, admin), template builder, reports end to end with signing and delivery, three built-in templates |
| 1.1 | Secure links through the Bifrost delivery gateway |
| 1.2 | Active Directory (LDAPS) and Microsoft Entra ID sign-in; API |
| 1.3 | Importers (Nmap, OpenVAS / Greenbone, Nessus), vulnerability data feeds, more built-in templates |
| 1.4 | HSM support, syslog / SIEM forwarding, custom fonts |

The design is described in [docs/architecture.md](docs/architecture.md).

## Tech stack

SvelteKit and TypeScript · Python and FastAPI · SQLite with SQLCipher · WeasyPrint · pyHanko · restic · Caddy · Docker Compose

## Contributing and security

Ideas, questions and bug reports are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md), which also says how to run the tests, and the [code of conduct](CODE_OF_CONDUCT.md). Please report security problems privately as described in [SECURITY.md](SECURITY.md), never in a public issue.

## Licence

Þing is licensed under the [GNU Affero General Public License v3.0](LICENSE). You may use, study, change and share it. If you share a modified version, or run one as a service for others, you must publish its source under the same licence.
