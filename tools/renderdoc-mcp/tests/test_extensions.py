import asyncio
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import ToolError
from contracts.catalog import TOOLS, validate
from adapters.renderdoc.debug_trace import record_trace
from adapters.renderdoc.replay import Replay
from workflows.shader_diff import compare_traces
from workflows.reports import profile_report, evidence_report
from workflows.doctor import diagnose, order_matrix_evidence
import hashlib
from workflows.analysis import export_bundle
from supervisor.service import Service


def var(name, value, kind="Float"):
    return {"name": name, "type": kind, "rows": 1, "columns": 1, "values": [value]}


def trace(values=(1, 2), instructions=(1, 2), kind="Float"):
    return {"schemaVersion": 2, "metadata": {"stage": "Pixel", "shaderSHA256": "abc", "replacementState": {}},
            "initial": {"inputs": [var("input", 0)]}, "completion": {"status": "complete"},
            "steps": [{"stepIndex": i, "nextInstruction": pc, "callstack": [],
                       "changes": [{"before": var("r0", 0, kind), "after": var("r0", value, kind)}]}
                      for i, (value, pc) in enumerate(zip(values, instructions))]}


class TraceTests(unittest.TestCase):
    def test_identity_and_first_write(self):
        a = trace()
        self.assertEqual(compare_traces(a, a, {})["status"], "equal_in_recorded_scope")
        result = compare_traces(a, trace((1, 3)), {})
        self.assertEqual(result["firstValueDivergence"]["stateIndex"], 1)

    def test_integer_tolerance_is_not_applied(self):
        result = compare_traces(trace((2**63, 2**63), kind="ULong"), trace((2**63+1, 2**63), kind="ULong"), {"absoluteThreshold": 100})
        self.assertEqual(result["firstValueDivergence"]["stateIndex"], 0)

    def test_float_and_nonfinite_policy(self):
        self.assertEqual(compare_traces(trace((1, 2)), trace((1.00001, 2)), {"absoluteThreshold": .0001})["status"], "equal_in_recorded_scope")
        self.assertEqual(compare_traces(trace(("nan", "inf")), trace(("nan", "inf")), {})["status"], "equal_in_recorded_scope")
        self.assertEqual(compare_traces(trace(("inf", 0)), trace(("-inf", 0)), {})["status"], "different")

    def test_branch_stops_value_alignment(self):
        result = compare_traces(trace((1, 2), (1, 2)), trace((1, 99), (1, 3)), {})
        self.assertEqual(result["comparedStates"], 1)
        self.assertIsNone(result["firstValueDivergence"])
        self.assertEqual(result["firstControlDivergence"]["stateIndex"], 1)

    def test_callstack_loop_and_length(self):
        a = trace((1, 2, 3), (4, 4, 4))
        self.assertEqual(compare_traces(a, a, {})["comparedStates"], 3)
        b = copy.deepcopy(a); b["steps"][1]["callstack"] = ["nested"]
        self.assertEqual(compare_traces(a, b, {})["comparedStates"], 1)
        self.assertIsNotNone(compare_traces(a, trace((1,), (4,)), {})["firstControlDivergence"])

    def test_truncation_and_unknown(self):
        a = trace(); a["completion"]["status"] = "truncated"
        self.assertEqual(compare_traces(a, trace(), {})["status"], "incomplete")
        a = trace(); a["steps"][0]["changes"][0]["after"] = {"name": "r0", "type": "Resource"}
        self.assertTrue(compare_traces(a, a, {})["unknownVariables"])

    def test_initial_values_and_removal(self):
        a,b = trace(),trace(); b["initial"]["inputs"][0]["values"] = [9]
        self.assertEqual(compare_traces(a,b,{})["firstValueDivergence"]["phase"], "initial")
        a["steps"][1]["changes"][0]["after"] = {"name": ""}
        self.assertEqual(compare_traces(a,a,{})["status"], "equal_in_recorded_scope")

    def test_shader_replacement_and_legacy_rejection(self):
        a,b=trace(),trace(); b["metadata"]["shaderSHA256"] = "different"
        with self.assertRaises(ToolError): compare_traces(a,b,{})
        b=trace(); b["metadata"]["replacementState"] = {"r": "new"}
        with self.assertRaises(ToolError): compare_traces(a,b,{})
        with self.assertRaises(ToolError): compare_traces({"steps": []},a,{})

    def test_contract_budgets(self):
        base = {"sessionId": "s", "eventId": 1, "stage": "Pixel", "x": 0, "y": 0}
        for extra in ({"maxSteps": 0}, {"maxBytes": 10}, {"maxSeconds": math.inf}, {"maxSteps": 1000001}):
            with self.assertRaises(ToolError): validate("debug_shader", dict(base, **extra))
        validate("debug_shader", dict(base, maxSteps=4, maxBytes=4096))

    def test_batch_budget_and_native_failure_cleanup(self):
        state = NS(stepIndex=0, nextInstruction=1, callstack=[], flags=0, changes=[])
        controller = NS(ContinueDebug=lambda debugger: [state] * 10)
        t = NS(debugger=1, inputs=[], constantBlocks=[])
        result = record_trace(controller,t,lambda v:v,lambda v:v,lambda *a:"",None,{}, {"maxSteps": 3})
        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(result["completion"]["reason"], "step_budget")
        state.changes = [NS(before=var("r", "x"*5000), after=var("r", 1))]
        result=record_trace(controller,t,lambda v:v,lambda v:v,lambda *a:"",None,{}, {"maxBytes": 4096})
        self.assertEqual(result["completion"]["reason"], "byte_budget")
        freed=[]
        rd=NS(DebugPixelInputs=lambda:NS(), ShaderStage=NS(Pixel=1), ShaderEvents=NS())
        replay=Replay(rd,"unused"); replay.variable=lambda v:v
        replay.set_event=lambda e:NS(GetShaderReflection=lambda s:None, GetShader=lambda s:None)
        def fail(d): raise RuntimeError("native failure")
        replay.controller=NS(DebugPixel=lambda *a:t, ContinueDebug=fail, FreeTrace=lambda tr:freed.append(tr))
        with self.assertRaises(RuntimeError): replay.debug_shader({"eventId":1,"stage":"Pixel","x":0,"y":0})
        self.assertEqual(freed,[t])


class ReportTests(unittest.TestCase):
    def test_zero_alpha_preview_preserves_rgb_and_original_bytes(self):
        from PIL import Image
        from workflows.analysis import file_artifact
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'zero-alpha.png'
            Image.new('RGBA', (2, 1), (120, 80, 40, 0)).save(source)
            original_bytes = source.read_bytes()
            artifact = file_artifact(d, original_bytes, 'png')
            payload = {'capture': {'path': 'private.rdc', 'sha256': 'abc'},
                'summary': {'api': 'D3D11', 'frame': {}, 'actionCount': 1}, 'annotations': [],
                'evidence': [{'action': {'eventId': 1, 'name': 'Cloth', 'numIndices': 3, 'flags': []},
                    'previews': [{'resourceId': 'ResourceId::1', 'image': artifact}]}]}
            before = copy.deepcopy(payload)
            result = export_bundle(payload, [], {}, Path(d) / 'bundles')
            root = Path(result['directory'])
            preview = json.loads((root / 'analysis.json').read_text())['evidence'][0]['previews'][0]
            self.assertEqual((root / preview['image']['path']).read_bytes(), original_bytes)
            with Image.open(root / preview['displayImage']['path']) as display:
                self.assertEqual(display.mode, 'RGB')
                self.assertEqual(display.getpixel((0, 0)), (120, 80, 40))
            self.assertIn(preview['displayImage']['path'], (root / 'REPORT.html').read_text())
            self.assertIn(preview['displayImage']['path'], (root / 'REPORT.md').read_text())
            self.assertEqual(preview['displayImage']['sourceSHA256'], artifact['sha256'])
            self.assertEqual(payload, before)

    def test_large_integer_counter_keeps_exact_display(self):
        payload={'counters':[],'events':[{'counters':[{'value':2**64-2}]}]}
        page=profile_report(payload,'large')
        self.assertIn('"value": "18446744073709551614"',page)
        self.assertEqual(payload['events'][0]['counters'][0]['value'],2**64-2)

    def test_html_escape_and_offline_data(self):
        payload={"counters":[{"counterId":1,"name":"duration","unit":"Seconds"}],"events":[],"actions":[],
                 "identity":{"captureId":"</script><script>alert(1)</script>"}}
        page=profile_report(payload,"<unsafe>")
        self.assertNotIn(payload["identity"]["captureId"], page)
        self.assertIn("&lt;unsafe&gt;",page)
        self.assertNotIn("https://",page)

    def test_bundle_html_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as d:
            payload={"capture":{"path":"private.rdc","sha256":"abc"},"summary":{"path":"private.rdc","api":"D3D11","frame":{},"actionCount":0},
                     "annotations":[{"note":"<script>attack</script>"}],"evidence":[]}
            result=export_bundle(payload,[],{},d)
            page=Path(result["htmlReport"]["path"]).read_text()
            self.assertIn("&lt;script&gt;",page)
            self.assertNotIn("private.rdc",page)
            import zipfile
            with zipfile.ZipFile(result["archive"]["path"]) as z:
                self.assertIn("REPORT.html", z.namelist())

    def test_bundle_includes_nested_capture_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            from workflows.analysis import file_artifact
            thumbnail = file_artifact(d, b'capture thumbnail', 'png')
            pixels = file_artifact(d, b'raw capture pixels', 'rgb')
            payload = {"capture": {"path": "private.rdc", "sha256": "abc", "thumbnail": thumbnail,
                                   "metadata": {"previews": [{"pixels": pixels}]}},
                       "summary": {"api": "D3D11", "frame": {}, "actionCount": 0},
                       "annotations": [], "evidence": []}
            original = copy.deepcopy(payload)
            supplied = []
            result = export_bundle(payload, supplied, {}, Path(d) / 'bundles')
            saved = json.loads(Path(result["index"]["path"]).read_text(encoding='utf-8'))
            descriptors = [saved['capture']['thumbnail'], saved['capture']['metadata']['previews'][0]['pixels']]
            import zipfile
            with zipfile.ZipFile(result['archive']['path']) as z:
                for item in descriptors:
                    self.assertTrue(item['path'].startswith('artifacts/'))
                    self.assertEqual(hashlib.sha256(z.read(item['path'])).hexdigest(), item['sha256'])
            self.assertEqual(result['artifactCount'], 2)
            self.assertEqual(payload, original)
            self.assertEqual(supplied, [])


class DoctorTests(unittest.TestCase):
    def matrix(self, directory):
        root=Path(directory);binary=root/'sample.exe';binary.write_bytes(b'fixture')
        core=root/'core.dll';core.write_bytes(b'core')
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        phases=[]
        for phase in ('baseline','early','after-factory','after-swapchain'):
            stages=['create_factory','create_device','create_queue','create_swapchain','present']
            if phase=='early':stages.insert(0,'load_core')
            if phase=='after-factory':stages.insert(1,'load_core')
            if phase=='after-swapchain':stages.insert(4,'load_core')
            records=[{'phase':phase,'pid':123}]+[{'stage':s,'hresult':'0x00000000','succeeded':True} for s in stages]+[{'terminal':True,'exitCode':0}]
            report=root/(phase+'.jsonl');report.write_text('\n'.join(json.dumps(e) for e in records))
            phases.append({'phase':phase,'exitCode':0,'events':records,'captures':[],'report':{'path':str(report),'sha256':digest(report)}})
        value={'schemaVersion':2,'kind':'d3d12-order-matrix','identity':{'fixturePath':str(binary),'fixtureSHA256':digest(binary),'corePath':str(core),'coreSHA256':digest(core)},'phases':phases}
        path=root/'matrix.json';path.write_text(json.dumps(value))
        return path,value

    def test_order_matrix_keeps_fixture_observations_separate(self):
        with tempfile.TemporaryDirectory() as d:
            path,m=self.matrix(d)
            result=order_matrix_evidence(path,m['identity']['coreSHA256'])
            self.assertEqual(len(result['phases']),4)
            states={c['check']:c['state'] for c in result['phases'][1]['checks']}
            self.assertEqual(states['create_device'],'observed')
            self.assertEqual(states['capture_saved'],'unknown')
            self.assertEqual(next(c['state'] for c in diagnose()['checks'] if c['check']=='device_wrapping'),'unknown')

    def test_order_matrix_rejects_core_report_and_event_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            path,m=self.matrix(d)
            with self.assertRaises(ToolError):order_matrix_evidence(path,'0'*64)
            m['phases'][0]['events'][1]['succeeded']=False;path.write_text(json.dumps(m))
            with self.assertRaises(ToolError):order_matrix_evidence(path,m['identity']['coreSHA256'])
            path,m=self.matrix(d);Path(m['phases'][0]['report']['path']).write_text('changed')
            with self.assertRaises(ToolError):order_matrix_evidence(path,m['identity']['coreSHA256'])

    def test_order_matrix_rejects_mislabelled_load_phase(self):
        with tempfile.TemporaryDirectory() as d:
            path,m=self.matrix(d);p=m['phases'][1]
            p['events'][1],p['events'][2]=p['events'][2],p['events'][1]
            report=Path(p['report']['path']);report.write_text('\n'.join(json.dumps(e) for e in p['events']))
            p['report']['sha256']=hashlib.sha256(report.read_bytes()).hexdigest();path.write_text(json.dumps(m))
            with self.assertRaises(ToolError):order_matrix_evidence(path,m['identity']['coreSHA256'])

    def test_unknown_is_not_failure(self):
        checks={c["check"]:c for c in diagnose(connection={"connected":True,"api":"D3D12"})["checks"]}
        self.assertEqual(checks["factory_wrapping"]["state"],"unknown")
        self.assertEqual(checks["control_connection"]["state"],"observed")

    def test_health_requires_hash_match(self):
        health={"kind":"capture-health","captures":[{"captureSHA256":"abc","status":"degraded"}]}
        self.assertEqual(diagnose(capture={"sha256":"ABC"},health=health)["health"]["status"],"degraded")
        with self.assertRaises(ToolError): diagnose(capture={"sha256":"other"},health=health)

    def test_connection_error_does_not_fail_unattempted_replay(self):
        checks={c["check"]:c for c in diagnose(errors=[{"scope":"connection","code":"missing_connection"}])["checks"]}
        self.assertEqual(checks["control_connection"]["state"],"failed")
        self.assertEqual(checks["replay_open"]["state"],"unknown")


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_pair_serial_inputs_and_saved_diff(self):
        with tempfile.TemporaryDirectory() as d:
            service=Service(d,d,sys.executable,Path(d)/"out")
            from workflows.analysis import file_artifact
            calls=[]
            async def query(name,args):
                calls.append(args)
                t=trace((args['x'],2))
                t['metadata'].update(captureId='capture-'+args['sessionId'],inputs=args)
                artifact=file_artifact(d,json.dumps(t));service.register(artifact)
                return {'trace':artifact}
            service.query=query
            args={'left':{'sessionId':'a','eventId':1,'x':4,'y':5},'right':{'sessionId':'b','eventId':2,'x':9,'y':6}}
            job=await service.call('debug_pixel_pair',args);await service.tasks[job['jobId']]
            info=service.db['jobs'][job['jobId']]
            self.assertEqual(info['status'],'completed')
            self.assertEqual(info['result']['status'],'different')
            self.assertEqual([c['sessionId'] for c in calls],['a','b'])
            self.assertEqual(info['result']['firstValueDivergence']['stateIndex'],0)
            self.assertEqual(info['result']['left']['captureId'],'capture-a')
            service.output_lock.close()

    async def test_registered_trace_diff_job_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            service=Service(d,d,sys.executable,Path(d)/"out")
            from workflows.analysis import file_artifact
            artifact=file_artifact(d,json.dumps(trace()))
            service.register(artifact)
            args={"leftArtifactId":artifact["artifactId"],"rightArtifactId":artifact["artifactId"]}
            job=await service.call("diff_shader_traces",args)
            await service.tasks[job["jobId"]]
            info=service.db["jobs"][job["jobId"]]
            self.assertEqual(info["status"],"completed")
            self.assertEqual(info["result"]["status"],"equal_in_recorded_scope")
            Path(artifact["path"]).write_text('{}')
            with self.assertRaises(ToolError): service.load_json_artifact(artifact["artifactId"])
            service.output_lock.close()


if __name__ == '__main__':
    unittest.main()
