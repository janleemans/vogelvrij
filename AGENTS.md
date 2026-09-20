# Vogelvrij project instructions

Before planning or modifying this repository, read `HANDOVER.md` in full. Verify relevant statements against the current code, tests, and Git history; source code is authoritative when documentation disagrees.

Keep `HANDOVER.md` current whenever work materially changes architecture, data model, collection/filtering semantics, map behavior, local setup, security, deployment, or operational procedures. Clearly separate implemented behavior from plans and known gaps. Update other affected documentation as well.

Preserve existing observations and the PostgreSQL volume unless deletion is explicitly requested. Do not commit API keys, credentials, `.env`, or generated map pages. Treat Google Maps browser keys as exposed to viewers and require appropriate API/referrer restrictions. Respect source-data licensing and attribution when building public output.

After code changes, run the relevant tests and `ruff check .`; report pre-existing or newly discovered failures rather than silently ignoring them.
