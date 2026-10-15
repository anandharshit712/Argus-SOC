# Argus SOC — Ruleset

Numbered so we can point at them in reviews ("breaks A3"). These rules beat convenience. If one
blocks you, raise it with the team; don't quietly work around it.

## H — Hackathon rules (breaking these can disqualify us)

| ID | Rule |
|----|------|
| **H1** | FalkorDB is the primary database and does real work. If the product still works with FalkorDB removed, we have broken this rule. |
| **H2** | All coding happens between Oct 15, 12:01 AM IST and Oct 18, 11:59 PM IST. Submit by **8 PM IST on Oct 18** to leave a buffer. |
| **H3** | Talos is used as a dependency pinned to a commit of its public repo. It is not copied into this repo and not changed during the event. The README credits it (Apache licence) and lists what we built Oct 15–18. |
| **H4** | Only public, synthetic or our own data. No private, login-protected, paywalled or personal data. |
| **H5** | AI coding assistants are allowed and disclosed in the README. Every teammate can explain their own code, the graph model, the queries and the design choices. |
| **H6** | The submission has: public repo, README with setup steps and graph data model, the Cypher queries and algorithms, demo video, live URL (or full local setup), both tracks named. |

## A — Architecture

| ID | Rule |
|----|------|
| **A1** | Cypher is written only in `src/argus_soc/graph/`. Agents, ingestor and API call the graph tools library. |
| **A2** | Every graph function takes `tenant` as its first argument. One FalkorDB graph per tenant. No query ever touches two tenants. |
| **A3** | Every write uses `MERGE` and is one short query, so retries and parallel agents never duplicate or clash. |
| **A4** | FalkorDB is the only state store for Argus SOC. No Redis, no vector store, no framework checkpoints holding cases or memory. Talos's own PostgreSQL is internal to Talos. |
| **A5** | Agents keep no state in memory between steps. An agent that restarts reads the case from the graph and carries on. |
| **A6** | Every agent decision cites the query results it was based on, stored on the Decision node. No decision without graph evidence. |
| **A7** | Talos is reached only over its HTTP API. No imports from the `talos` package. |
| **A8** | The Responder's decision table is deterministic code in `decision_table.py`. The LLM explains and assists; it does not override the table. If no LLM is reachable, agents still decide and use a templated explanation. |
| **A9** | Log content, payloads and Talos evidence are attacker-controlled data, never instructions. Put them inside clearly delimited, length-limited blocks in prompts, and never execute or follow them. |
| **A10** | Response actions (isolate, disable, block) are simulated: recorded in the graph and shown in the UI only. Nothing calls real infrastructure. |
| **A11** | The three interface contracts (graph schema, graph tool signatures, UI API shapes) are frozen once agreed. Changing one needs a message to all three and a doc update in the same pull request. |

## C — Code

| ID | Rule |
|----|------|
| **C1** | Python 3.11+, type hints on every function, Pydantic v2 models for data crossing a module boundary. |
| **C2** | I/O is `async` (HTTP, graph calls, LLM calls). |
| **C3** | Lint and format with `ruff`; test with `pytest`. Both pass before a pull request. |
| **C4** | Thresholds, polling intervals, URLs and model names live in settings or `.env`, never as literals in logic. |
| **C5** | File names follow `FOLDER_STRUCTURE.md`: `<subject>_<role>.py`, no `utils`/`helpers`/`common`/`misc`/`_v2`. |
| **C6** | Files stay under 600 lines; 800 is the hard limit. |
| **C7** | No secrets in code or git. `.env` is ignored; `.env.example` lists every variable with no real values. |
| **C8** | Use the logger, not `print`. Log the tenant, case id and agent on every agent step. |
| **C9** | Fail loudly at startup on bad config. At runtime, the ingestor and agents log the error, retry with backoff and keep running. One bad report never stops the loop. |

## G — Git

| ID | Rule |
|----|------|
| **G1** | Work on your own branch (`a/...`, `b/...`, `c/...`) and merge to `main` through a pull request. |
| **G2** | `main` always starts with `docker compose up`. Don't merge anything that breaks it. |
| **G3** | Changes to contract files (`graph_schema.py`, `read_queries.py` / `write_queries.py` signatures, `api_models.py`) need a review from one other teammate. |
| **G4** | Commit messages: `type(area): what changed`, e.g. `feat(agents): triage recall step`, `fix(graph): merge on incident_id`. |
| **G5** | No force-push to `main`. No large binaries or generated files in git. |
| **G6** | No AI attribution in git: no `Co-Authored-By: Claude …` (or any AI) trailer, no "Generated with …" line in commits or pull requests, no AI account as author or contributor. Checked before every merge to `main`; offending commits are rewritten on the branch before merging. AI use is disclosed in the README only. |

## T — Testing

| ID | Rule |
|----|------|
| **T1** | Every graph function has a test against the seeded test graph. |
| **T2** | Agents are tested against `graph_stubs.py`, so their tests don't need FalkorDB running. |
| **T3** | Each demo scenario has an end-to-end test or scripted check in `tests/e2e/`. |
| **T4** | Run the checks before opening a pull request: `ruff check .`, `ruff format --check .`, `pytest`. |

## D — Demo

| ID | Rule |
|----|------|
| **D1** | Scenario logs and inventories are fixed files, so the demo plays the same way every time. |
| **D2** | `scripts/reset_demo.py` wipes and reseeds both tenants in one command. |
| **D3** | Record a backup demo video before the final submission, in case the live demo fails. |
