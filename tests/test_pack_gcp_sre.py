"""gcp_sre pack: every rule id has a positive and a negative case, plus the fixture flow."""

import json

import pytest

from core.packs.gcp_sre import events as ev
from core.packs.gcp_sre import logs, nodetrace, tfgcp
from core.types import SEVERITY_ORDER


def res(rtype, **values):
    return {"address": f"{rtype}.x", "type": rtype, "values": values}


def check_all(resource):
    return [f for check in tfgcp.CHECKS for f in check(resource)]


def fw(*ports, source="0.0.0.0/0", proto="tcp"):
    return res("google_compute_firewall", source_ranges=[source], allow=[{"protocol": proto, "ports": list(ports)}])


def vm(email="", scopes=(), public_ip=False):
    nic = [{"access_config": [{"nat_ip": "203.0.113.1"}]}] if public_ip else [{}]
    return res("google_compute_instance", service_account=[{"email": email, "scopes": list(scopes)}], network_interface=nic)


def sql(net=None, ipv4=False, backup=True, protect=True):
    ipc = {"ipv4_enabled": ipv4, "authorized_networks": [{"value": net}] if net else []}
    return res("google_sql_database_instance", deletion_protection=protect,
               settings=[{"ip_configuration": [ipc], "backup_configuration": [{"enabled": backup}]}])


def gke(**overrides):
    values = {"enable_legacy_abac": False, "private_cluster_config": [{"enable_private_nodes": True}],
              "master_authorized_networks_config": [{"cidr_blocks": [{"cidr_block": "10.0.0.0/8"}]}],
              "workload_identity_config": [{"workload_pool": "p.svc.id.goog"}]}
    return res("google_container_cluster", **{**values, **overrides})


def bucket(**values):
    return res("google_storage_bucket", **{"public_access_prevention": "enforced", "uniform_bucket_level_access": True, **values})


DEDICATED = "api@p.iam.gserviceaccount.com"
DEFAULT_SA = "123-compute@developer.gserviceaccount.com"
CLOUD = "https://www.googleapis.com/auth/cloud-platform"

# (rule id, expected severity, positive resource, negative resource)
TF_CASES = [
    ("GCP-IAM-PUBLIC", "critical", res("google_storage_bucket_iam_member", role="roles/storage.objectViewer", member="allUsers"),
     res("google_storage_bucket_iam_member", role="roles/storage.objectViewer", member="group:a@x.example")),
    ("GCP-IAM-PRIMITIVE", "high", res("google_project_iam_member", role="roles/editor", member="group:a@x.example"),
     res("google_project_iam_member", role="roles/viewer", member="group:a@x.example")),
    ("GCP-IAM-ESCALATION", "high",
     res("google_project_iam_member", role="roles/iam.serviceAccountTokenCreator", member="group:a@x.example"),
     res("google_service_account_iam_member", role="roles/iam.serviceAccountTokenCreator", member="group:a@x.example")),
    ("GCP-IAM-ADMIN-ROLE", "medium", res("google_project_iam_member", role="roles/storage.admin", member="group:a@x.example"),
     res("google_project_iam_member", role="roles/storage.objectViewer", member="group:a@x.example")),
    ("GCP-IAM-USER-DIRECT", "medium", res("google_project_iam_member", role="roles/owner", member="user:a@x.example"),
     res("google_project_iam_member", role="roles/owner", member="group:a@x.example")),
    ("GCP-IAM-AUTHORITATIVE", "high", res("google_project_iam_policy", policy_data="{}"),
     res("google_project_iam_member", role="roles/viewer", member="group:a@x.example")),
    ("GCP-SA-KEY", "high", res("google_service_account_key", service_account_id="a"), res("google_service_account", email="a")),
    ("GCP-STATE-SECRET", "high", res("google_service_account_key", service_account_id="a", private_key="x"),
     res("google_service_account_key", service_account_id="a")),
    ("GCP-SA-DEFAULT", "high", vm(DEFAULT_SA, [CLOUD]), vm(DEDICATED)),
    ("GCP-SA-SCOPE", "medium", vm(DEDICATED, [CLOUD]), vm(DEDICATED)),
    ("GCP-NET-PUBLIC-IP", "medium", vm(DEDICATED, public_ip=True), vm(DEDICATED)),
    ("GCP-NET-FW-OPEN", "critical", fw(), fw(source="10.0.0.0/8")),
    ("GCP-NET-FW-PUBLIC", "low", fw("443"), fw("443", source="10.0.0.0/8")),
    ("GCP-DATA-BUCKET-PAP", "medium", bucket(public_access_prevention="inherited"), bucket()),
    ("GCP-DATA-BUCKET-ACL", "medium", bucket(uniform_bucket_level_access=False), bucket()),
    ("GCP-DATA-SQL-PUBLIC", "critical", sql(net="0.0.0.0/0"), sql()),
    ("GCP-DATA-SQL-PUBLIC-IP", "medium", sql(ipv4=True), sql()),
    ("GCP-DATA-SQL-BACKUP", "medium", sql(backup=False), sql()),
    ("GCP-DATA-DELETION-PROTECTION", "low", sql(protect=False), sql()),
    ("GCP-GKE-ABAC", "high", gke(enable_legacy_abac=True), gke()),
    ("GCP-GKE-PUBLIC-NODES", "medium", gke(private_cluster_config=[]), gke()),
    ("GCP-GKE-MASTER-OPEN", "high", gke(master_authorized_networks_config=[{"cidr_blocks": [{"cidr_block": "0.0.0.0/0"}]}]), gke()),
    ("GCP-GKE-NO-WI", "low", gke(workload_identity_config=[]), gke()),
]


@pytest.mark.parametrize("rule,severity,positive,negative", TF_CASES, ids=[c[0] for c in TF_CASES])
def test_terraform_rule_positive_and_negative(rule, severity, positive, negative):
    hit = [f for f in check_all(positive) if f.rule_id == rule]
    assert hit and {f.severity for f in hit} == {severity} and all(f.recommendation for f in hit)
    assert rule not in {f.rule_id for f in check_all(negative)}


def test_overprivileged_service_identity_positive_and_negative():
    sa = "serviceAccount:a@p.iam.gserviceaccount.com"
    [hit] = tfgcp.check_identities({sa: ["roles/owner", "roles/iam.serviceAccountAdmin"]})
    assert (hit.rule_id, hit.severity) == ("GCP-SA-OVERPRIVILEGED", "high") and hit.recommendation
    assert tfgcp.check_identities({sa: ["roles/owner"]}) == []
    assert tfgcp.check_identities({"user:a@x.example": ["roles/owner", "roles/editor"]}) == []


def test_firewall_variants():
    assert check_all(fw("22", source="35.235.240.0/20")) == []
    [db] = check_all(fw("5432"))
    assert db.severity == "critical" and db.evidence["ports"] == {"5432": "postgres"}
    [rng] = check_all(fw("3000-3400"))
    assert "mysql" in rng.title
    disabled = fw("22")
    disabled["values"]["disabled"] = True
    assert check_all(disabled) == []
    egress = fw("22")
    egress["values"]["direction"] = "EGRESS"
    assert check_all(egress) == []


def test_iam_policy_and_binding_forms():
    policy = res("google_project_iam_policy",
                 policy_data=json.dumps({"bindings": [{"role": "roles/owner", "members": ["allUsers"]}]}))
    assert {"GCP-IAM-PUBLIC", "GCP-IAM-AUTHORITATIVE"} <= {f.rule_id for f in check_all(policy)}
    binding = res("google_folder_iam_binding", role="roles/iam.serviceAccountTokenCreator", members=["group:g@x.example"])
    assert [f.rule_id for f in check_all(binding)] == ["GCP-IAM-ESCALATION", "GCP-IAM-AUTHORITATIVE"]
    assert check_all(res("google_project_iam_custom_role")) == []


def test_state_fixture_findings_and_secret_hygiene(packs):
    report = tfgcp.analyze_file(packs / "gcp_sre" / "state.tfstate.json")
    got = {(f.rule_id, f.resource) for f in report.findings}
    assert {
        ("GCP-IAM-PRIMITIVE", "google_project_iam_member.app_owner"),
        ("GCP-IAM-PRIMITIVE", "google_project_iam_member.dev_editor"),
        ("GCP-IAM-USER-DIRECT", "google_project_iam_member.dev_editor"),
        ("GCP-IAM-ESCALATION", "google_project_iam_member.app_sa_admin"),
        ("GCP-IAM-PUBLIC", "google_storage_bucket_iam_member.public"),
        ("GCP-SA-KEY", "google_service_account_key.app"),
        ("GCP-STATE-SECRET", "google_service_account_key.app"),
        ("GCP-SA-DEFAULT", "google_compute_instance.web"),
        ("GCP-NET-FW-OPEN", "google_compute_firewall.ssh_any"),
        ("GCP-DATA-SQL-PUBLIC", "google_sql_database_instance.db"),
        ("GCP-DATA-BUCKET-PAP", "google_storage_bucket.exports"),
        ("GCP-GKE-ABAC", "google_container_cluster.main"),
        ("GCP-GKE-MASTER-OPEN", "google_container_cluster.main"),
        ("GCP-SA-OVERPRIVILEGED", "serviceAccount:app@acme-prod.iam.gserviceaccount.com"),
    } <= got
    assert not any(r in ("google_project_iam_member.viewer", "google_compute_firewall.internal",
                         "module.data.google_storage_bucket.ok") for _, r in got)
    sev = {(f.rule_id, f.resource): f.severity for f in report.findings}
    assert sev[("GCP-IAM-PRIMITIVE", "google_project_iam_member.app_owner")] == "critical"
    assert "REDACTED-BY-FIXTURE" not in json.dumps([f.model_dump() for f in report.findings])
    assert report.metrics["source"] == "state" and report.metrics["google_resources"] == 14
    assert report.metrics["identity_matrix"]["serviceAccount:app@acme-prod.iam.gserviceaccount.com"] == [
        "roles/iam.serviceAccountAdmin", "roles/owner"]


def test_plan_input_uses_resource_changes_and_skips_deletes(tmp_path):
    plan = {"resource_changes": [
        {"address": "google_project_iam_member.a", "type": "google_project_iam_member", "name": "a",
         "change": {"actions": ["create"], "after": {"role": "roles/owner", "member": "user:x@y.example"}}},
        {"address": "google_project_iam_member.gone", "type": "google_project_iam_member", "name": "gone",
         "change": {"actions": ["delete"], "before": {"role": "roles/owner", "member": "allUsers"}, "after": None}}]}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    report = tfgcp.analyze_file(path)
    assert {f.resource for f in report.findings} == {"google_project_iam_member.a"}
    assert report.metrics["source"] == "plan"


def test_rejects_non_terraform_json(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"hello": 1}')
    with pytest.raises(ValueError):
        tfgcp.analyze_file(path)


# ----------------------------------------------------------------------------- sre_logs
def log_report(tmp_path, lines, **opts):
    path = tmp_path / "app.log"
    path.write_text("\n".join(f"2025-06-30T10:00:{i:02d}Z {line}" for i, line in enumerate(lines)) + "\n")
    return logs.analyze_file(path, **opts)


def hits(report, rule):
    return [f for f in report.findings if f.rule_id == rule]


# (rule id, expected severity, positive lines, negative lines)
SIGNATURE_CASES = [
    ("KAFKA-BROKER-UNAVAILABLE", "high", ["ERROR Connection to node 2 (kafka-2/10.0.4.12:9092) could not be established. Broker may not be available."],
     ["INFO Connection to node 2 established"]),
    ("KAFKA-REBALANCE", "high", ["WARN group is rebalancing"] * 3, ["WARN group is rebalancing"] * 2),
    ("KAFKA-CONSUMER-EVICTED", "high", ["ERROR CommitFailedException: group already rebalanced"], ["INFO offset commit ok"]),
    ("KAFKA-OFFSET-RESET", "medium", ["WARN OffsetOutOfRange for partition orders-0"], ["INFO offset committed"]),
    ("KAFKA-ISR", "high", ["WARN Shrinking ISR from 1,2,3 to 1"], ["INFO ISR is complete"]),
    ("KAFKA-AUTH", "high", ["ERROR TopicAuthorizationException: Not authorized to access topics"], ["INFO topic created"]),
    ("KAFKA-PRODUCE-FAIL", "medium", ["ERROR Expiring 12 record(s) for billing-0"], ["INFO produced 12 records"]),
    ("KAFKA-DISK", "critical", ["ERROR KafkaStorageException: log dir failed"], ["INFO log segment rolled"]),
    ("SPLUNK-PIPELINE-BLOCKED", "high", ["WARN TcpOutputProc blocked=true queue is full"], ["INFO TcpOutputProc connected"]),
    ("SRE-OOM", "high", ["ERROR Container terminated on signal 9 (OOMKilled)"], ["INFO Container started"]),
    ("SRE-CRASHLOOP", "high", ["WARN Back-off restarting failed container"], ["INFO Liveness probe succeeded"]),
    ("SRE-DB-POOL", "high", ["ERROR too many connections for role app"], ["INFO connections healthy"]),
    ("SRE-CAPACITY", "high", ["ERROR no available instance to serve the request"], ["INFO instances ready"]),
    ("SRE-QUOTA", "medium", ["ERROR RESOURCE_EXHAUSTED: quota exceeded"], ["INFO quota within limits"]),
    ("SRE-PERMISSION", "medium", ["ERROR PERMISSION_DENIED: Caller does not have permission"], ["INFO permission check passed"]),
    ("SRE-DEADLINE", "medium", ["ERROR DEADLINE_EXCEEDED calling payments"], ["INFO call finished within deadline"]),
    ("KAFKA-CONSUMER-LAG", "high", ["WARN consumer lag=50000 group=g topic=t partition=0"],
     ["WARN consumer lag=50 group=g topic=t partition=0"]),
]


@pytest.mark.parametrize("rule,severity,positive,negative", SIGNATURE_CASES, ids=[c[0] for c in SIGNATURE_CASES])
def test_signature_positive_and_negative(tmp_path, rule, severity, positive, negative):
    found = hits(log_report(tmp_path, positive), rule)
    assert found and {f.severity for f in found} == {severity} and all(f.recommendation for f in found)
    assert not hits(log_report(tmp_path, negative), rule)


def test_error_burst_positive_and_negative(tmp_path):
    def at_minutes(counts):
        rows = [f"2025-06-30T10:{m:02d}:{s:02d}Z ERROR boom" for m, n in enumerate(counts) for s in range(n)]
        path = tmp_path / "burst.log"
        path.write_text("\n".join(rows) + "\n")
        return logs.analyze_file(path)

    [burst] = hits(at_minutes([1, 15, 1]), "SRE-ERROR-BURST")
    assert burst.severity == "high" and burst.evidence["minute"] == "2025-06-30T10:01Z" and burst.recommendation
    assert not hits(at_minutes([4, 4, 4]), "SRE-ERROR-BURST")


def test_error_rate_positive_and_negative(tmp_path):
    [rate] = hits(log_report(tmp_path, ["ERROR boom"] * 3 + ["INFO ok"] * 27), "SRE-ERROR-RATE")
    assert rate.severity == "medium" and rate.recommendation
    assert not hits(log_report(tmp_path, ["INFO ok"] * 30), "SRE-ERROR-RATE")


def test_lag_threshold_option(tmp_path):
    line = ["WARN consumer lag=50000 group=g topic=t"]
    assert hits(log_report(tmp_path, line, lag_threshold=1000), "KAFKA-CONSUMER-LAG")
    assert not hits(log_report(tmp_path, line, lag_threshold=100_000), "KAFKA-CONSUMER-LAG")


def test_kafka_broker_log_fixture(packs):
    report = logs.analyze_file(packs / "gcp_sre" / "kafka_broker.log")
    by = {f.rule_id: f for f in report.findings}
    assert {"KAFKA-BROKER-UNAVAILABLE", "KAFKA-REBALANCE", "KAFKA-CONSUMER-EVICTED", "KAFKA-ISR", "KAFKA-AUTH",
            "KAFKA-PRODUCE-FAIL", "KAFKA-CONSUMER-LAG"} <= set(by)
    lag = by["KAFKA-CONSUMER-LAG"].evidence
    assert (lag["max_lag"], lag["group"], lag["topic"]) == (48211, "orders-consumer", "orders")
    assert by["KAFKA-BROKER-UNAVAILABLE"].evidence["first_seen"] == "2025-06-30T12:03:00+00:00"
    assert "sk-ant-fixture" not in str(report.model_dump())


def test_splunk_export_fixture(packs):
    report = logs.analyze_file(packs / "gcp_sre" / "splunk_export.json")
    by = {f.rule_id: f for f in report.findings}
    assert {"SPLUNK-PIPELINE-BLOCKED", "SRE-OOM", "SRE-PERMISSION", "SRE-ERROR-BURST", "SRE-ERROR-RATE"} <= set(by)
    assert by["SRE-ERROR-BURST"].evidence["minute"] == "2025-06-30T12:08Z" and by["SRE-OOM"].evidence["hosts"] == ["web-2"]
    assert report.metrics["events"] == 73
    assert "ghp_FIXTURE" not in str(report.model_dump())
    assert "<n>" in report.metrics["top_error_signatures"][0]["signature"]


def test_cloud_logging_and_csv_shapes(tmp_path):
    entry = {"timestamp": "2025-06-30T10:00:00Z", "severity": "ERROR", "resource": {"labels": {"service_name": "api"}},
             "textPayload": "Container terminated on signal 9 (OOMKilled)"}
    p = tmp_path / "gcl.jsonl"
    p.write_text(json.dumps(entry) + "\n")
    [e] = ev.load_events(p)
    assert (e.level, e.host, e.ts and e.ts.isoformat()) == ("ERROR", "api", "2025-06-30T10:00:00+00:00")
    csv_path = tmp_path / "s.csv"
    csv_path.write_text("_time,host,_raw\n1751277600,h1,ERROR CrashLoopBackOff pod x\n")
    report = logs.analyze_file(csv_path)
    assert [f.rule_id for f in report.findings] == ["SRE-CRASHLOOP"]


# ----------------------------------------------------------------------------- node_trace
def trace_report(tmp_path, text, **opts):
    path = tmp_path / "node.log"
    path.write_text(text if text.endswith("\n") else text + "\n")
    return nodetrace.analyze_file(path, **opts)


def traced(header, frame="/srv/app/src/a.js:1:1"):
    return f"2025-06-30T10:00:00Z ERROR {header}\n    at fn ({frame})\n"


# (rule id, expected severity, positive log text, negative log text)
NODE_CASES = [
    ("NODE-OOM", "critical", "FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory", "INFO heap ok"),
    ("NODE-UNCAUGHT", "high", "ERROR uncaughtException: boom", "ERROR handled exception in worker"),
    ("NODE-LISTENER-LEAK", "medium", "WARN MaxListenersExceededWarning: Possible EventEmitter memory leak", "WARN listeners fine"),
    ("NODE-EMFILE", "high", traced("Error: EMFILE: too many open files"), traced("Error: ENOENT: no such file")),
    ("NODE-EADDRINUSE", "medium", traced("Error: listen EADDRINUSE: address already in use :::3000"), traced("Error: listen EACCES")),
    ("NODE-KAFKAJS", "medium", traced("KafkaJSConnectionError: bad broker"), traced("Error: bad broker")),
    ("NODE-NET", "medium", traced("Error: connect ECONNREFUSED 10.0.0.1:6379"), traced("Error: bad input")),
    ("NODE-CODE-DEFECT", "medium", traced("TypeError: x is undefined"),
     traced("TypeError: x is undefined", "/srv/app/node_modules/pkg/index.js:1:1")),
    ("NODE-DEP-ERROR", "low", traced("Error: oops", "/srv/app/node_modules/pkg/index.js:1:1"), traced("Error: oops")),
    ("NODE-ERROR", "low", traced("Error: oops"), traced("Error: oops", "/srv/app/node_modules/pkg/index.js:1:1")),
]


@pytest.mark.parametrize("rule,severity,positive,negative", NODE_CASES, ids=[c[0] for c in NODE_CASES])
def test_node_rule_positive_and_negative(tmp_path, rule, severity, positive, negative):
    found = hits(trace_report(tmp_path, positive), rule)
    assert found and {f.severity for f in found} == {severity} and all(f.recommendation for f in found)
    assert not hits(trace_report(tmp_path, negative), rule)


def test_frames_kinds_causes_and_grouping():
    text = ("TypeError: Cannot read properties of undefined (reading 'id')\n"
            "    at buildOrder (/srv/app/src/orders/build.js:88:31)\n"
            "    at Layer.handle [as handle_request] (/srv/app/node_modules/express/lib/router/layer.js:95:5)\n"
            "    at next (node:internal/process/task_queues:95:5)\n    at file:///srv/app/src/x.mjs:3:1\n"
            "Caused by: Error: inner\n")
    [t] = nodetrace.extract_traces(text)
    assert [f.kind for f in t.frames] == ["app", "dependency", "internal", "app"]
    assert t.causes == ["Error: inner"] and t.frames[-1].file == "/srv/app/src/x.mjs"
    assert nodetrace.extract_traces("just a log line\nError: no frames here\n") == []


def test_repeat_threshold_escalates_one_level(tmp_path):
    text = "".join(traced("TypeError: x is undefined") for _ in range(6))
    [defect] = hits(trace_report(tmp_path, text), "NODE-CODE-DEFECT")
    assert defect.severity == "high" and defect.evidence["count"] == 6
    [calm] = hits(trace_report(tmp_path, text, repeat_threshold=10), "NODE-CODE-DEFECT")
    assert calm.severity == "medium"


def test_node_fixtures(packs):
    report = nodetrace.analyze_file(packs / "gcp_sre" / "node_app.log")
    by = {f.rule_id: f for f in report.findings}
    assert {"NODE-NET", "NODE-KAFKAJS", "NODE-EMFILE", "NODE-UNCAUGHT"} <= set(by)
    assert by["NODE-NET"].evidence["target"] == "10.20.30.40:6379" and by["NODE-NET"].location == "/srv/app/src/cache.js:12"
    assert report.metrics["traces"] == 3
    splunk = nodetrace.analyze_file(packs / "gcp_sre" / "splunk_export.json")
    defect = next(f for f in splunk.findings if f.rule_id == "NODE-CODE-DEFECT")
    assert defect.evidence["count"] == 6 and defect.severity == "high"
    assert defect.evidence["top_app_frame"].startswith("buildOrder (/srv/app/src/orders/build.js:88")


# ----------------------------------------------------------------------------- clean inputs and invariants
def test_clean_fixtures_have_no_findings(packs):
    assert tfgcp.analyze_file(packs / "gcp_sre" / "clean.tfstate.json").findings == []
    assert logs.analyze_file(packs / "gcp_sre" / "clean_app.log").findings == []
    assert nodetrace.analyze_file(packs / "gcp_sre" / "clean_app.log").findings == []


def test_every_fixture_finding_is_well_formed(packs):
    reports = [tfgcp.analyze_file(packs / "gcp_sre" / "state.tfstate.json")]
    for name in ("kafka_broker.log", "node_app.log", "splunk_export.json"):
        reports += [logs.analyze_file(packs / "gcp_sre" / name), nodetrace.analyze_file(packs / "gcp_sre" / name)]
    findings = [f for r in reports for f in r.findings]
    assert len(findings) > 30
    for f in findings:
        assert f.severity in SEVERITY_ORDER and f.recommendation and f.title and f.category and f.location
        assert f.rule_id.split("-")[0] in {"GCP", "KAFKA", "SPLUNK", "SRE", "NODE"}


def test_same_input_same_output(packs):
    path = packs / "gcp_sre" / "splunk_export.json"
    assert logs.analyze_file(path).model_dump_json() == logs.analyze_file(path).model_dump_json()
    assert nodetrace.analyze_file(path).model_dump_json() == nodetrace.analyze_file(path).model_dump_json()
