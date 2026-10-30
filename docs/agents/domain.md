# Domain docs

This repository uses a single context: a root `GLOSSARY.md` and decisions under `docs/adr/`.

Before exploring, read `GLOSSARY.md` when present and the ADRs relevant to the area being
changed. If a `GLOSSARY-MAP.md` exists later, follow it to the relevant context glossaries.
If these documents do not exist, proceed silently. Create terms and decisions lazily when
they are resolved through domain modeling; do not create placeholder glossaries or ADRs.

Use the project's defined terms consistently. When a proposed change contradicts an ADR,
identify that decision and explain the conflict instead of silently overriding it.

The current implementation map lives in `docs/architecture.md`; it describes observed
behavior and does not replace recorded decisions.
