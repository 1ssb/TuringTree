# Security Policy

Turing Tree (RagIndex) is a research / hackathon project provided under the MIT
License **"as is", without warranty of any kind** (see [LICENSE](LICENSE)). It is
designed to run **entirely on your own machine** — no cloud services, no
telemetry, and no API keys — so the network attack surface is intentionally
small.

## Supported versions

This is a community project maintained on a best-effort basis. Only the latest
state of the `main` branch (and the newest `v1.x` tag) receives fixes.

| Version | Supported |
| ------- | --------- |
| latest `main` / newest `v1.x` | ✅ |
| older tags | ❌ |

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** — do **not** open a public
issue, discussion, or pull request for security problems.

- Use GitHub's private reporting: **Security → “Report a vulnerability”** on this
  repository
  ([open a report](https://github.com/1ssb/TuringTree/security/advisories/new)).

Include, if you can: affected files or endpoints, a minimal reproduction, and the
potential impact.

We triage reports on a **best-effort** basis. Because this is a volunteer,
community-maintained project, we **cannot commit to a fixed response or
remediation timeline**. Valid reports will be addressed as time allows, and we're
happy to credit you in the release notes unless you'd prefer to stay anonymous.

## Scope

- **In scope:** source code in this repository.
- **Out of scope:** third-party dependencies — report those to their own
  maintainers (e.g. [PageIndex](https://github.com/VectifyAI/PageIndex),
  [Ollama](https://ollama.com), and packages in `requirements*.txt` /
  `frontend/package.json`); issues that require an already-compromised host; and
  findings that depend on non-default, user-modified configuration.

## Good-faith research

We support good-faith security research. If you make a good-faith effort to avoid
privacy violations, data loss, and service disruption while investigating, we
will not pursue or support action against you.

## Maintainers

Turing Tree was built by the following team, developed as part of the Microsoft
Global Intern Hackathon 2026. Security reports are handled by:

- [Subhransu S. (Rudra) Bhattacharjee](https://github.com/1ssb)
- [Himanshu Singh](https://github.com/himanshuIndia)
- [Yeredla Koushik Reddy](https://github.com/ykr080805)
- [Jayesh RL](https://github.com/Aspect022)
