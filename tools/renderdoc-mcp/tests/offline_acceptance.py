"""Exercise the compiled portable binary using an existing capture only.

No discovery, connection, injection or capture request is sent to a live target.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import VERSION
from contracts.catalog import TOOLS


class ToolFailure(RuntimeError):
    def __init__(self,payload):
        self.payload=payload
        super().__init__(str(payload))


async def run(args):
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    package=Path(args.package).resolve()
    environment=os.environ.copy()
    environment.pop('PYTHONHOME',None);environment.pop('PYTHONPATH',None)
    environment['PATH']=r'C:\Windows\System32;C:\Windows'
    log=open(root/'server-stderr.log','wb')
    process=await asyncio.create_subprocess_exec(str(package/'renderdoc-mcp.exe'),'--output-dir',str(root/'data'),'serve','--stdio',
        cwd=r'C:\Windows',env=environment,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=log,limit=128*1024*1024)
    counter=0;proof={"scope":"Compiled MCP + packaged Python 3.6 worker, existing RDC offline replay only", "checks":{}, "runtimeGameValidation":"Pending"}
    async def request(method,params):
        nonlocal counter
        counter+=1
        process.stdin.write((json.dumps({"jsonrpc":"2.0","id":counter,"method":method,"params":params})+'\n').encode())
        await process.stdin.drain()
        while True:
            line=await asyncio.wait_for(process.stdout.readline(),180)
            if not line: raise RuntimeError('MCP exited')
            message=json.loads(line)
            if message.get('id')==counter:
                if 'error' in message: raise RuntimeError(message['error'])
                return message['result']
    async def tool(name,**params):
        result=await request('tools/call',{"name":name,"arguments":params})
        if result.get('isError'): raise RuntimeError(result['content'][0]['text'])
        value=result.get('structuredContent') or json.loads(result['content'][0]['text'])
        if 'jobId' in value and name!='get_job':
            while True:
                job=await tool('get_job',jobId=value['jobId'])
                if job['status'] in ('completed','failed','cancelled'):
                    if job['status']!='completed': raise ToolFailure(job.get('error',job))
                    value=job['result'];break
                await asyncio.sleep(.25)
        if name!='get_job':
            proof['checks'][name]=value
            (root/'results.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
            print(name+' passed',flush=True)
        return value
    try:
        identity=await request('initialize',{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"offline-extension-acceptance","version":"1"}})
        assert identity['serverInfo']['version']==VERSION,identity
        process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n');await process.stdin.drain()
        catalog=await request('tools/list',{})
        assert {item['name'] for item in catalog['tools']}==set(TOOLS),len(catalog['tools'])
        proof['serverIdentity']=identity['serverInfo'];proof['toolCount']=len(catalog['tools'])
        opened=await tool('open_capture',path=str(Path(args.capture).resolve()))
        session=opened['sessionId']
        await tool('get_capabilities',sessionId=session)
        await tool('debug_shader',sessionId=session,eventId=args.event,stage='Vertex',vertex=0,index=0,maxSteps=128,maxBytes=1024*1024,maxSeconds=10)
        vertex=proof['checks']['debug_shader']
        payload=json.loads(Path(vertex['trace']['path']).read_text())
        assert payload['schemaVersion']==2 and payload['metadata']['captureId']==opened['captureId']
        await tool('query_shader_trace',artifactId=vertex['trace']['artifactId'],limit=3)
        # Pixel identity comparison requires an actual covered fragment.
        # A failure is retained as an unsupported candidate, not equal output.
        actions=await tool('find_actions',sessionId=session,flags='Drawcall',limit=10000)
        candidates=[args.event]+[a['eventId'] for a in reversed(actions['actions']) if a.get('numIndices') in (3,6)][:3]
        proof['pixelCandidates']=[]
        for event in dict.fromkeys(candidates):
            side={"sessionId":session,"eventId":event,"x":args.x,"y":args.y,"sample":0,"primitive":0,"maxSteps":4096,"maxBytes":4*1024*1024,"maxSeconds":10}
            try:
                pair=await tool('debug_pixel_pair',left=side,right=side)
                assert pair['firstValueDivergence'] is None and pair['firstControlDivergence'] is None,pair
                assert pair['status'] in ('equal_in_recorded_scope','incomplete'),pair
                saved=await tool('diff_shader_traces',leftArtifactId=pair['leftArtifactId'],rightArtifactId=pair['rightArtifactId'])
                assert saved['status']==pair['status']
                proof['pixelCandidates'].append({'eventId':event,'status':pair['status']})
                break
            except ToolFailure as exc:
                if exc.payload.get('code')!='unsupported':raise
                proof['pixelCandidates'].append({'eventId':event,'status':'unsupported','error':exc.payload})
        report=await tool('export_profile_report',sessionId=session,title='Offline replay acceptance')
        assert Path(report['report']['path']).is_file()
        doctor=await tool('capture_doctor',sessionId=session,**({'orderMatrixPath':str(Path(args.order_matrix).resolve())} if args.order_matrix else {}))
        checks={c['check']:c for c in doctor['checks']}
        assert checks['replay_open']['state']=='observed' and checks['factory_wrapping']['state']=='unknown'
        if args.order_matrix:
            assert len(doctor['orderMatrixEvidence']['phases'])==4
        await tool('annotate_capture',captureId=opened['captureId'],note='<script>escaped evidence</script>',eventId=args.event)
        bundle=await tool('export_analysis_bundle',captureId=opened['captureId'],eventIds=[args.event],artifactIds=[report['report']['artifactId']],includeConstants=False)
        assert '&lt;script&gt;' in Path(bundle['htmlReport']['path']).read_text(encoding='utf-8')
        await tool('close_capture',sessionId=session)
        proof['status']='passed'
        (root/'results.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    finally:
        process.stdin.close()
        try: await asyncio.wait_for(process.wait(),30)
        except asyncio.TimeoutError:
            process.kill();await process.wait()
        log.close()
    if process.returncode: raise RuntimeError('Server exit '+str(process.returncode))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',required=True);p.add_argument('--capture',required=True);p.add_argument('--output',required=True)
    p.add_argument('--event',type=int,default=2087);p.add_argument('--x',type=int,default=1024);p.add_argument('--y',type=int,default=576)
    p.add_argument('--order-matrix')
    asyncio.run(run(p.parse_args()))
