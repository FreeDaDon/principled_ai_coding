# Domain packs: MCP governance and GCP SRE

Two packs of deterministic analyzers. They turn untrusted artifacts (an MCP server manifest, a connector's
scripts, a Terraform export, a Kafka or Node.js log) into typed `Finding`s, then hand a file of findings to a
read-only agent for judgment. The analyzers never call an LLM, and the agent never changes anything.

**Ship policy: propose only.** A run writes a report under `.pac/runs/<id>/` and stops. Nothing is applied,
installed, registered, restarted or re-permissioned. A human reads the report and acts. (This repo has no
worktree or PR flow, so there is no `--propose` flag; the report is the proposal. See the sibling
[TAC toolkit](https://github.com/FreeDaDon/tac) for a PR flow.)

```
input ──▶ core.packs (no LLM) ──▶ findings.json + report.md ──▶ read-only agent ──▶ assessment.json ──▶ human
                                        ▲ path only, never inlined in a prompt
```

## Where things live

| Path | What it is |
|---|---|
| `core/types.py` | `Finding`, `AnalysisReport`, and the strict agent reply `AgentAssessment` (pydantic, `extra="forbid"`) |
| `core/security.py` | Report-text helpers: `redact_secrets`, `snippet`, `escape_markdown`, `markdown_code`, `find_suspicious_unicode` |
| `core/packs/mcp_gov/` | `manifest.py` (`mcp_manifest`), `rbac.py` (scope/audience validator), `injection.py` (`connector_scan`) |
| `core/packs/gcp_sre/` | `tfgcp.py` (`gcp_tf`), `logs.py` (`sre_logs`), `nodetrace.py` (`node_trace`), `events.py` (log loaders) |
| `core/packs/registry.py` | `PACK_TOOLS`, input auto-detection, `run_pack`, the CLI |
| `core/packs/export.py` | JSON and Markdown rendering |
| `adws/adw_domain_pack.py` | The workflow: analyze, interpret, report, gate |
| `.claude/commands/mcp_review.md`, `gcp_triage.md` | The agent's instructions per pack |
| `specs/templates/ai_connector_review.md`, `gcp_incident.md` | 5-layer spec templates for the decision record |
| `tests/fixtures/packs/` | Planted issues (fake credentials only) and one clean input per pack |

## Run it

```bash
# deterministic only (CI gate: exit 2 when a finding is at or above the level)
uv run python -m core.packs.registry mcp_gov vendor/connector/ --fail-on high
uv run python -m core.packs.registry gcp_sre state.json --format json --out findings.json
uv run python -m core.packs.registry mcp_gov server.json --opt allowed_scopes=docs.read,docs.list
uv run python -m core.packs.registry gcp_sre app.log --tool node_trace --opt repeat_threshold=3

# analyze + agent interpretation + report
uv run adws/adw_domain_pack.py --pack mcp_gov --input vendor/connector/ --fail-on high
uv run adws/adw_domain_pack.py --pack gcp_sre --input exports/ --no-agent       # skip the agent
PAC_RUNNER=mock uv run adws/adw_domain_pack.py --pack gcp_sre --input tests/fixtures/packs/gcp_sre   # offline, $0
```

Registry options (`--opt key=value`): mcp_gov `allowed_scopes` (comma list), `max_tools` (25), `require_audience`
(true); gcp_sre `lag_threshold` (10000), `burst_min` (10), `burst_factor` (3.0), `repeat_threshold` (5).
Directory input analyzes every recognizable file (`.env` files and symlinks are never read). A log that contains
stack traces is analyzed by `sre_logs` and by `node_trace`; pass `--tool` to run only one.

Exit codes. Registry: 0 ok, 1 bad input, 2 `--fail-on` tripped. Workflow: 0 done, 1 the workflow failed (bad
input, agent error, malformed assessment, input changed), 2 `--fail-on` tripped (the report is still written).

Fail closed. Inputs are untrusted, so an analyzer that crashes on a file never ends the run and never passes the file:
the file gets one `INPUT-ERROR` finding at **high** severity (it cannot be cleared until it can be analyzed), and the
other files are still analyzed. `--fail-on high` therefore blocks on it.

## Pack 1: `mcp_gov` (AI connector intake, risk assessment, release authorization)

`release_gate` in `metrics` is `blocked` (any critical or high), `needs_review`, or `eligible_for_human_review`.
It is advisory. A human authorizes release. Spec: `specs/templates/ai_connector_review.md`. Agent: `/mcp_review`.

**`mcp_manifest`** reads a server manifest or an `mcpServers` client config (JSON or YAML). It never connects.
Every string in it also goes through the injection scanner, so a poisoned tool description is reported at
`server:tools[N].description`. Metrics: `risk_score` (0-100), scopes, transports.

| Rule id | Severity | Fires when |
|---|---|---|
| `MCP-TRANSPORT-PLAINTEXT` | high | non-loopback endpoint over `http://` |
| `MCP-TLS-VERIFY-OFF` | high | `verify_tls: false`, `insecure: true` and variants |
| `MCP-AUTH-NONE` | high | remote server with no authentication |
| `MCP-AUTH-STATIC` | medium | api key / bearer / basic instead of IdP OAuth |
| `MCP-AUTH-FLOW` | high | implicit or password OAuth flow |
| `MCP-AUTH-PKCE` | medium | OAuth with `pkce: false` |
| `MCP-SCOPE-BROAD` | high | `*`, admin, owner, `cloud-platform`, `.all` scopes |
| `MCP-SCOPE-NOT-ALLOWED` | high | scope outside `--opt allowed_scopes` |
| `MCP-SCOPE-UNUSED` | medium | scope no tool declares a need for |
| `MCP-SCOPE-MISSING` | low | a tool requires a scope that is not requested |
| `MCP-SCOPE-WRITE-ON-READONLY` | medium | write scopes while every tool is read-only |
| `MCP-AUDIENCE-BROAD` | high | audience is "everyone", "all-users", "public"... |
| `MCP-AUDIENCE-MISSING` | medium | no approved IdP group declared |
| `MCP-CMD-INLINE` | high | launched through a shell or `-c`/`-e` inline code |
| `MCP-CMD-REMOTE-EXEC` | critical | launch command pipes a download into a shell |
| `MCP-PKG-UNPINNED` | medium | `npx`/`uvx`/... package not pinned to an exact version |
| `MCP-IMAGE-UNPINNED` | medium | container image without a digest |
| `MCP-CONTAINER-PRIV` | high | `--privileged`, host network/pid, docker socket, `/` mount |
| `MCP-RESOURCE-BROAD` | high | filesystem root, `$HOME`, or credential paths as a resource or argument |
| `MCP-SECRET-LITERAL` | high | literal credential in env, headers or argv (location and length only) |
| `MCP-TOOL-EXEC` | high | tool executes commands or code |
| `MCP-TOOL-DESTRUCTIVE` | medium | destructive-looking tool without `destructiveHint` |
| `MCP-TOOL-ANNOTATION-MISMATCH` | high | claims `readOnlyHint` but the name implies a write |
| `MCP-INPUT-UNCONSTRAINED` | high / medium | free string for `command`/`sql`/`code` (high) or `path`/`url`/`host` (medium) |
| `MCP-TOOL-DUP`, `MCP-TOOL-SHADOW` | medium | duplicate tool name, or a name that collides with a built-in tool |
| `MCP-TOOL-COUNT`, `MCP-TOOL-NO-ANNOTATIONS` | low | more tools than `max_tools`; no tool declares annotations |
| `MCP-EXFIL-TRIFECTA` | high | private-data read + untrusted content + external send in one server |
| `MCP-EXFIL-PATH` | medium | private-data read + external send |
| `MCP-PROVENANCE-VERSION`, `MCP-PROVENANCE-SOURCE` | low | floating or missing version; no repository/publisher |
| `MCP-DESCRIPTION-LONG` | low | description over 1500 characters (room to hide instructions) |

**`connector_scan`** scans every file of a connector (skills, scripts, docs, configs, minified bundles, files with
no extension). Only lockfiles, source maps, media, symlinks and `.env` files are ignored. A file it cannot read (binary,
over 1 MB, unreadable) is reported as `SCAN-SKIPPED`, never dropped. Past 200 findings per file it keeps the most
severe ones and counts the rest in `metrics.findings_truncated`.

| Rule id | Severity | Fires when |
|---|---|---|
| `INJ-OVERRIDE`, `INJ-ROLE-HIJACK` | high | "ignore previous instructions"; "you are now..." |
| `INJ-CONCEAL` | critical | instruction to hide actions from the user |
| `INJ-TOOL-COERCION` | high | `<IMPORTANT>` blocks, "before using this tool you must first read..." |
| `INJ-ROLE-MARKUP`, `INJ-HIDDEN-COMMENT` | medium | chat-template markup; instruction-like HTML comment |
| `INJ-ASCII-SMUGGLING` | critical | invisible Unicode tag characters (the hidden text is decoded into evidence) |
| `INJ-HIDDEN-UNICODE` | high | bidi or zero-width characters |
| `INJ-ENCODED` | medium / high | base64 text payload; high when it decodes to an instruction |
| `EXF-SENSITIVE-PATH`, `EXF-ENV-DUMP` | high | reads `~/.ssh`, `~/.aws`, `.env`...; serializes the whole environment |
| `EXF-NET-EGRESS` | medium | outbound network write |
| `EXF-SINK-DOMAIN` | high | webhook.site, ngrok, pastebin..., or a public raw-IP URL |
| `EXF-MD-IMAGE` | high | image URL that interpolates data (render-time exfiltration) |
| `EXF-CHAIN` | critical | sensitive read and an outbound path in the same file |
| `EXE-DYNAMIC` | high | `eval`, `exec`, `shell=True`, `pickle.loads`, unsafe YAML |
| `SUP-REMOTE-EXEC` | critical | `curl ... \| sh`, encoded PowerShell, base64 piped to a shell |
| `SUP-INSTALL` | medium | install hook, or install from a URL or custom index |
| `SCAN-SKIPPED` | high | a file could not be scanned (binary, over 1 MB, unreadable), so it cannot be cleared |

**The agent's role (`/mcp_review`).** Separates real risk from false positives (a security document that quotes an
attack, say), groups findings into actions ranked P1 to P4, and writes a release recommendation (reject, fix and
resubmit, approve for the named audience) into `summary`. A poisoned description is rejected, not fixed.

**Intake flow.** Copy the spec template, record source, exact version, audience and data classification. Run the
pack, then read the manifest and every tool description yourself: the scanner finds patterns, not intent. Fix the
manifest until only approved scopes and groups remain. Security, IAM and the platform owner sign; only then is
the connector registered.

## Pack 2: `gcp_sre` (GCP incident and Node.js triage)

Spec: `specs/templates/gcp_incident.md`. Agent: `/gcp_triage`.

**`gcp_tf`** reads `terraform show -json` (state or saved plan; child modules are walked; planned deletes are
skipped). It reports a service-account private key's presence, never its value. Metrics: `identity_matrix`
(member to roles), `service_accounts`, `resources_by_type`, `risk_score`.

| Rule id | Severity | Fires when |
|---|---|---|
| `GCP-IAM-PUBLIC` | critical / high | `allUsers` or `allAuthenticatedUsers` (critical on data services, at project/folder/org level, or with owner/editor) |
| `GCP-IAM-PRIMITIVE` | critical / high | owner or editor (critical for a service account or at org level) |
| `GCP-IAM-ESCALATION` | high | token creator, SA admin, IAM admin... at project, folder or org level |
| `GCP-IAM-ADMIN-ROLE` | medium | `*.admin` role at project, folder or org level |
| `GCP-IAM-USER-DIRECT` | medium | privileged role bound to an individual user, not a group |
| `GCP-IAM-AUTHORITATIVE` | high / medium / low | `_iam_policy` or `_iam_binding` replaces existing bindings |
| `GCP-SA-KEY`, `GCP-STATE-SECRET` | high | user-managed key; its private key stored in state |
| `GCP-SA-DEFAULT` | high / medium | default compute service account (high with `cloud-platform` scope) |
| `GCP-SA-SCOPE` | medium | `cloud-platform` scope on a dedicated service account |
| `GCP-SA-OVERPRIVILEGED` | high / medium | a service identity with several privileged roles, or 6+ roles |
| `GCP-NET-FW-OPEN` | critical / high | internet to all ports, databases, Kafka (critical) or SSH/RDP (high) |
| `GCP-NET-FW-PUBLIC` | low | internet to non-sensitive ports |
| `GCP-NET-PUBLIC-IP` | medium | VM with an external IP |
| `GCP-DATA-SQL-PUBLIC` | critical | Cloud SQL authorized network `0.0.0.0/0` |
| `GCP-DATA-SQL-PUBLIC-IP`, `GCP-DATA-SQL-BACKUP` | medium | public IPv4; backups disabled |
| `GCP-DATA-DELETION-PROTECTION` | low | Cloud SQL deletion protection off |
| `GCP-DATA-BUCKET-PAP`, `GCP-DATA-BUCKET-ACL` | medium | public access prevention not enforced; uniform access off |
| `GCP-GKE-ABAC`, `GCP-GKE-MASTER-OPEN` | high | legacy ABAC; control plane open to `0.0.0.0/0` |
| `GCP-GKE-PUBLIC-NODES` | medium | nodes are not private |
| `GCP-GKE-NO-WI` | low | Workload Identity off |

**`sre_logs`** reads a Splunk export (JSON, JSONL, CSV with `_raw`/`_time`), a Cloud Logging export, or plain
text. Each signature becomes one finding with `count`, `first_seen`, `last_seen`, `hosts` and up to three
redacted samples. A medium or low signature seen 20+ times is raised one level.

| Rule id | Severity | Fires when |
|---|---|---|
| `KAFKA-BROKER-UNAVAILABLE`, `KAFKA-ISR`, `KAFKA-AUTH` | high | brokers unreachable/leaderless; ISR shrink or below minimum; SASL/ACL/TLS failures |
| `KAFKA-REBALANCE` | high | 3 or more rebalance events |
| `KAFKA-CONSUMER-EVICTED` | high | session or `max.poll.interval.ms` timeouts, `CommitFailedException` |
| `KAFKA-CONSUMER-LAG` | high | lag at or above `lag_threshold`, with group and topic |
| `KAFKA-OFFSET-RESET`, `KAFKA-PRODUCE-FAIL` | medium | offset out of range; expired or oversized records |
| `KAFKA-DISK` | critical | broker log directory failed or disk full |
| `SPLUNK-PIPELINE-BLOCKED` | high | ingestion blocked or dropping (logs may be missing: "no errors" means unknown) |
| `SRE-OOM`, `SRE-CRASHLOOP`, `SRE-DB-POOL`, `SRE-CAPACITY` | high | OOM kills; crash loops or failed probes; pool exhaustion; no instance available |
| `SRE-QUOTA`, `SRE-PERMISSION`, `SRE-DEADLINE` | medium | quota exhausted; permission denied; deadline exceeded |
| `SRE-ERROR-BURST` | high / medium | busiest error minute vs the median |
| `SRE-ERROR-RATE` | medium | over 5% of 20+ events are errors |

**`node_trace`** extracts `Error: msg` plus `at fn (file:line:col)` frames, `Caused by:` chains, async frames and
`file://` paths from any of those inputs, classifies frames (`app`, `dependency`, `internal`), and groups by error
type, normalized message and top application frame. A signature seen `repeat_threshold` times is raised one level.

| Rule id | Severity | Fires when |
|---|---|---|
| `NODE-OOM` | critical | V8 heap exhausted |
| `NODE-UNCAUGHT`, `NODE-EMFILE` | high | uncaught exception or unhandled rejection; file descriptors exhausted |
| `NODE-EADDRINUSE`, `NODE-KAFKAJS`, `NODE-NET`, `NODE-CODE-DEFECT`, `NODE-LISTENER-LEAK` | medium | port in use; KafkaJS error; network failure (with `host:port`); TypeError/ReferenceError/RangeError/SyntaxError in application code; listener leak |
| `NODE-DEP-ERROR`, `NODE-ERROR` | low | error originating in a dependency (with the package); any other trace |

**The agent's role (`/gcp_triage`).** Orders findings by `first_seen` (earliest failing component is the probable
cause, later ones are symptoms), names the file and line from `top_app_frame` for a regression suspect, treats log
gaps as unknown, ranks exposure, and puts read-only diagnostics first. It never proposes a broader role to make a
permission error go away.

## Safety model

- **No execution, no network.** The analyzers read files. They never run `terraform`, `gcloud`, `npx`, `docker`,
  or anything from the input, and never fetch a remote manifest. The tests fail if a process or socket is opened.
- **Untrusted text is scrubbed at two levels.** Analyzers build evidence with `snippet()`; `run_pack` then scrubs
  every string in every report, including metrics and summary. Scrubbing means: NFKC-normalize, drop control, bidi,
  zero-width and Unicode-tag characters, redact known secret formats (`[REDACTED:<rule>]`), collapse to one line,
  cap at 2000 characters. Findings carry a secret's location and length, never its value.
- **Markdown is escaped.** Prose goes through `escape_markdown`; evidence goes in code spans whose fence is
  longer than any backtick run inside. JSON output carries an `UNTRUSTED DATA` notice.
- **The agent gets a path.** `findings.json` is passed as a file path in a read-only `architect` role (Read, Glob,
  Grep; no Bash, Edit or Write) with the run directory as its working directory. The prompt never contains
  finding text.
- **Strict reply.** The agent's reply must parse into `AgentAssessment` (unknown keys, bad enums and oversized
  fields are errors). A malformed reply fails the step and keeps the deterministic report.
- **Fail closed on approval.** Any action with a `proposed_change` is forced to `requires_human_approval: true`
  in code, whatever the agent said. `proposed_change` is text for a human, never executed.
- **Propose only.** After the agent step, the workflow checks that the input tree did not change.
- **Limits.** A clean result is not a safe connector or a healthy system. The rules are heuristics (a document
  about prompt injection can trip `INJ-*`), the scanner cannot see runtime behavior, the GCP audit sees only what
  the export contains (not org policy or IAM granted outside Terraform), and log order across hosts depends on
  clock skew. Exports can hold secrets: treat them as confidential and delete them after the review.

## Extending

1. Injection or exfiltration rule: add `_rule(...)` to `INJECTION_RULES` or `EXFIL_RULES` in `core/packs/mcp_gov/injection.py`.
2. Manifest or scope rule: add a check to `manifest.py` (transport, launch, tools) or `rbac.py` (scopes, audience). Use the next free `MCP-*` id.
3. GCP rule: add to a `check_*` function in `tfgcp.py` (or a new function in `CHECKS`) with the next free `GCP-*` id.
4. Log signature: add `_sig(...)` to `SIGNATURES` in `logs.py`. Set `min_count` for symptoms that matter only in bulk.
5. Node.js class: add a branch in `_classify` in `nodetrace.py`, or a `_MARKERS` entry for process-level messages.
6. New log format: add a loader path in `events.py` that yields `Event`s; every analyzer then works on it.
7. New tool: write `analyze_file(path, **opts) -> AnalysisReport`, register it in `PACK_TOOLS` and the pack's detector in `registry.py` (and in `COMPANIONS` if it should also run on another tool's input).
8. New pack: add its name to `PackName` in `core/types.py`, its tools to `PACK_TOOLS`, a command in `.claude/commands/`, and an entry in `PACK_COMMANDS` in `adws/adw_domain_pack.py`.

Every rule needs a stable id, a severity, a recommendation, and a positive and a negative case in
`tests/test_pack_mcp_gov.py` or `tests/test_pack_gcp_sre.py`. Add planted issues to `tests/fixtures/packs/` with
fake credentials only.
