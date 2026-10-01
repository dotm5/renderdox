"""Evidence-based diagnostics. Absence of observation is never hook failure."""

from contracts import ToolError
import hashlib
import json
import re
from pathlib import Path


def order_matrix_evidence(path, expected_core_sha256):
    """Validate saved fixture evidence without executing its files or code."""
    def load(path):
        path = Path(path)
        if path.stat().st_size > 1024 * 1024:
            raise ToolError('invalid_order_matrix', 'Matrix/report exceeds 1 MiB')
        return path.read_text(encoding='utf-8-sig')
    def digest(path):
        h = hashlib.sha256()
        with Path(path).open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()
    def checked(path, expected):
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected) or digest(path) != expected.lower():
            raise ToolError('order_evidence_changed', 'Evidence SHA256 mismatch: ' + str(path))
    matrix = json.loads(load(path))
    if matrix.get('schemaVersion') != 2 or matrix.get('kind') != 'd3d12-order-matrix':
        raise ToolError('invalid_order_matrix', 'Run the schemaVersion 2 order matrix script')
    identity = matrix['identity']
    if identity['coreSHA256'].lower() != expected_core_sha256.lower():
        raise ToolError('order_core_mismatch', 'Fixture Core differs from this MCP package Core')
    checked(identity['corePath'], identity['coreSHA256'])
    checked(identity['fixturePath'], identity['fixtureSHA256'])
    phases = matrix['phases']
    if len(phases) != 4 or {p['phase'] for p in phases} != {'baseline', 'early', 'after-factory', 'after-swapchain'}:
        raise ToolError('invalid_order_matrix', 'Expected four unique creation-order phases')
    result = []
    for phase in phases:
        checked(phase['report']['path'], phase['report']['sha256'])
        records = [json.loads(line) for line in load(phase['report']['path']).splitlines() if line.strip()]
        if records != phase['events'] or not records or records[0].get('phase') != phase['phase'] or not records[0].get('pid'):
            raise ToolError('invalid_order_matrix', 'Embedded events differ from the hashed JSONL report')
        if records[-1].get('terminal') is not True or records[-1].get('exitCode') != phase['exitCode']:
            raise ToolError('invalid_order_matrix', 'Missing/mismatched terminal exit status')
        stages = {}
        for event in records:
            if 'stage' in event:
                hr = event.get('hresult', '')
                if not re.fullmatch(r'0x[0-9a-fA-F]{8}', hr) or event.get('succeeded') is not (int(hr, 16) < 0x80000000):
                    raise ToolError('invalid_order_matrix', 'HRESULT and success flag disagree')
                stages.setdefault(event['stage'], []).append(event)
        order = [e['stage'] for e in records if 'stage' in e]
        if phase['phase'] != 'baseline':
            if 'load_core' not in order:
                raise ToolError('invalid_order_matrix', 'No Core load attempt in nonbaseline phase')
            preceding = {'early': None, 'after-factory': 'create_factory', 'after-swapchain': 'create_swapchain'}[phase['phase']]
            if preceding and (preceding not in order or order.index(preceding) >= order.index('load_core')):
                raise ToolError('invalid_order_matrix', 'Core load order contradicts phase')
            if phase['phase'] == 'early' and 'create_factory' in order and order.index('load_core') >= order.index('create_factory'):
                raise ToolError('invalid_order_matrix', 'Early Core load occurred after factory')
        elif 'load_core' in order:
            raise ToolError('invalid_order_matrix', 'Baseline unexpectedly loaded Core')
        for capture in phase['captures']:
            checked(capture['path'], capture['sha256'])
            if Path(capture['path']).stat().st_size != capture['byteLength']:
                raise ToolError('order_evidence_changed', 'Capture byte length mismatch')
        saved = stages.get('capture_saved', [])
        count = next((e['captureCount'] for e in records if 'captureCount' in e), 0)
        if count != len(phase['captures']) or (saved and saved[-1]['succeeded'] and not count):
            raise ToolError('invalid_order_matrix', 'Capture count and verified RDC files disagree')
        observations = []
        for stage in ('load_core', 'core_handshake', 'create_factory', 'create_device', 'create_queue', 'create_swapchain', 'present', 'capture_started', 'capture_saved'):
            evidence = stages.get(stage, [])
            observations.append({'check': stage, 'state': 'observed' if evidence and all(e['succeeded'] for e in evidence) else 'failed' if evidence else 'unknown', 'evidence': evidence})
        result.append({'phase': phase['phase'], 'pid': records[0]['pid'], 'exitCode': phase['exitCode'], 'checks': observations, 'captures': phase['captures']})
    return {'kind': 'd3d12-order-evidence', 'identity': identity, 'phases': result,
        'source': {'path': str(path), 'sha256': digest(path)},
        'scope': 'Hashed reports from the owned fixture only. Object creation does not prove wrapping; no inference about the selected game.'}


def diagnose(connection=None, capture=None, replay=None, health=None, errors=None):
    checks = []
    def add(name, state, evidence):
        checks.append({"check": name, "state": state, "evidence": evidence})
    connection_errors = [e for e in errors or [] if e.get("scope") == "connection"]
    replay_errors = [e for e in errors or [] if e.get("scope") == "replay"]
    add("control_connection", "observed" if connection and connection.get("connected") else "failed" if connection or connection_errors else "unknown", connection or connection_errors)
    add("graphics_api", "observed" if connection and connection.get("api") else "unknown", connection.get("api") if connection else None)
    add("capture_collected", "observed" if capture and capture.get("state") == "ready" else "unknown", capture)
    add("replay_open", "observed" if replay else "failed" if replay_errors else "unknown", replay or replay_errors)
    for name in ("module_load", "factory_wrapping", "device_wrapping", "queue_wrapping", "swapchain_wrapping", "present_observed"):
        add(name, "unknown", "Public target control does not expose this observation")
    matched = None
    if health is not None:
        if health.get("kind") != "capture-health" or not isinstance(health.get("captures"), list):
            raise ToolError("invalid_health", "Expected a Capture Health Checker document")
        if not capture:
            raise ToolError("missing_capture", "Choose a capture to bind health evidence by SHA256")
        matched = next((x for x in health["captures"] if str(x.get("captureSHA256", "")).lower() == capture["sha256"].lower()), None)
        if matched is None:
            raise ToolError("health_capture_mismatch", "Health evidence does not contain the selected capture SHA256")
        add("capture_health", {"healthy": "observed", "degraded": "warning", "failed": "failed"}.get(matched.get("status"), "unknown"), matched)
    else:
        add("capture_health", "unknown", "No matching Capture Health Checker artifact supplied; replay-open alone is not full health validation")
    return {"schemaVersion": 1, "checks": checks, "health": matched, "errors": errors or [],
            "interpretation": "States are independent evidence, not a global injection-success score. Unknown means unobserved, not absent. No target mutation or automatic retry."}
