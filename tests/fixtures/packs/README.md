# Pack fixtures

Inputs for the `mcp_gov` and `gcp_sre` domain packs (`core/packs/`). Every credential in here is a **fake**
planted on purpose (`sk-ant-fixture...`, `ghp_FIXTURE...`, `supersecretvalue1234`, `REDACTED-BY-FIXTURE-NOT-A-REAL-KEY`)
so the tests can prove that secrets never reach a finding. The hostile text (prompt injection, `curl | sh`,
credential paths) is inert data: nothing in this tree is ever executed.

Invisible Unicode (zero-width, bidi, tag characters) is built inside the tests, not stored here, so it cannot be
stripped or hidden by an editor.

| Path | Purpose |
|---|---|
| `mcp_gov/servers/risky_server.json` | manifest with planted MCP-* and INJ-* issues |
| `mcp_gov/servers/client_config.json` | `mcpServers` client config with launch-command risks |
| `mcp_gov/servers/clean_server.json` | clean manifest (no findings) |
| `mcp_gov/connectors/` | `exfil_tool.py`, `poisoned_skill/`, and a clean `benign_tool.py` |
| `gcp_sre/state.tfstate.json` | `terraform show -json` state with planted GCP-* issues |
| `gcp_sre/clean.tfstate.json` | clean state (no findings) |
| `gcp_sre/kafka_broker.log`, `node_app.log`, `splunk_export.json` | Kafka/Node.js/Splunk failures |
| `gcp_sre/clean_app.log` | healthy log (no findings) |
