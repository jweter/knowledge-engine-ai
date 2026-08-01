# Security Policy

## Supported Versions

Knowledge Engine AI is pre-release software. Security fixes will target the
latest version on `main` until the first stable release policy is defined.

## Reporting a Vulnerability

Please do not report security vulnerabilities in public issues.

Until a private security contact is published, prepare a concise report with:

- Affected version or commit.
- Steps to reproduce.
- Impact.
- Any known workaround.
- Whether the issue involves private data, unsafe file handling, or command
  execution.

Once the repository is published on GitHub, enable private vulnerability
reporting and update this file with the official reporting path.

## Scope

Security-sensitive areas include:

- Shelling out to `ke` (`knowledge-engine-core`'s CLI) -- arguments passed
  to `subprocess` must never interpolate untrusted input into a shell
  string; always pass argument lists, never `shell=True`.
- Any future LLM API integration -- API keys must come from environment
  variables only, never committed, never logged.
- Any future conversational interface accepting free-text user input.

## Current Limitations

This is a pre-alpha, offline-first CLI that shells out to `knowledge-engine-core`.
No network-facing service, no stored credentials, no user data persistence
exist yet.
