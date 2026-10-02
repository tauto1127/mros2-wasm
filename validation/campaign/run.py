#!/usr/bin/env python3
"""Owned, serial application checkpoint/restore campaign runner.

No network recreation or proxy restart is performed. Container operations are
restricted to containers bearing this run's unique ownership label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import struct
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

APP_DEFAULT = Path('/tmp/locks-native-T11-20261002/build-echoback_string/echoback_string.wasm')
RUNTIME_DEFAULT = Path('/tmp/mros2-wasm-no-udp-recover-experiment-build-03/runtime/iwasm')
PEER_DEFAULT = Path('/tmp/mros2-posix-run04-final-build/mros2-posix')
HASHES = {
    'app': 'b9b01ebf0523048e3af1ca07655c010a72ed364d7eacee05c61277058f09e9d9',
    'runtime': '77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60',
    'peer': '8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1',
}
NETWORK = 'mros2-cr-net'
NETWORK_ID = '609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408'
SUBNET = '172.18.0.0/16'
IMAGE = 'ros:humble'
IMAGE_ID = 'sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138'
LABEL_KEY = 'io.mros2-cr.validation-run'
FREE_MIN = 3 * 1024**3
MEMORY_BYTES = 1024**3
STALL_SECONDS = 300
BODY = 'Hello from mros2-posix onto Linux: {mid}'
KINDS = ('publish', 'receive', 'echo', 'callback')
PUB = re.compile(r"publishing msg: 'Hello from mros2-posix onto Linux: (\d+)'")
CALL = re.compile(r"subscribed msg: 'Hello from mros2-posix onto Linux: (\d+)'")
RECV = re.compile(r"event=peer_receive topic=/to_linux id=(-?\d+) payload='([^']*)'")
ECHO = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(-?\d+) payload='([^']*)'")
TRACE = re.compile(r"RTPS_TRACE seq=(\d+) kind=(\d+) result=(\d+) current=(\d+) applied=(\d+) detail=(\d+) aux=(\d+) thread=(\d+)")
TRACE_METRICS = re.compile(r"RTPS_TRACE_METRICS attempts=(\d+) winners=(\d+) busy=(\d+) failed=(\d+) outcomes=(\d+) probe_completions=(\d+) active=(\d+) max_active=(\d+) lost=(\d+) lockfree=(\d+)")
TRACE_KINDS = {1:'eintr', 2:'trylock_attempt', 3:'trylock_outcome', 4:'probe_enter', 5:'probe_exit',
               6:'current', 7:'applied', 8:'prepare_begin', 9:'prepare_fail', 10:'commit',
               11:'applied_last', 12:'equal', 13:'retry'}
TRACE_RESULTS = {0:'unavailable', 1:'busy', 2:'failed', 3:'unchanged', 4:'changed'}
TRACE_SCHEMA = 'traceoverlay_event-v2;seq:u32,kind:u16,result:u16,current_ip:u32,applied_ip:u32,detail:u32,aux:u32,thread_id:u64;metrics include lost,lockfree,active,max_active'


def utc(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')
def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()
def write(path, text):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding='utf-8')
def docker(args, timeout=60):
    return subprocess.run(['rtk','proxy','docker',*map(str,args)], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout, check=False)
def sha_record(paths): return {key:{'path':str(p),'sha256':digest(p)} for key,p in paths.items()}

def parse_trace_line(line):
    event=TRACE.search(line)
    if event:
        seq,kind,result,current,applied,detail,aux,thread=map(int,event.groups())
        return ('trace',{'seq':seq,'kind':kind,'result':result,'current_ip':current,
            'applied_ip':applied,'detail':detail,'aux':aux,'thread_id':thread})
    metrics=TRACE_METRICS.search(line)
    if metrics:
        names=('attempts','winners','busy','failed','outcomes','probe_completions',
               'active','max_active','lost','lockfree')
        return ('trace_metrics',dict(zip(names,map(int,metrics.groups()))))
    return None

class Collector:
    def __init__(self, path, source, events, lock):
        self.path, self.source, self.events, self.lock = path, source, events, lock
    def consume(self, proc):
        with self.path.open('w', encoding='utf-8') as out:
            for line in proc.stdout:
                now = time.monotonic_ns()
                rendered = f'host_utc={utc()} host_mono_ns={now} {line.rstrip()}\n'
                out.write(rendered); out.flush()
                parsed=parse_trace_line(line)
                if parsed:
                    kind, values=parsed
                    if kind=='trace': values.update(collector_mono_ns=now,source=self.source)
                    with self.lock: self.events.append((kind,values))
                found = None
                for kind, rx in (('publish',PUB),('callback',CALL),('receive',RECV),('echo',ECHO)):
                    m = rx.search(line)
                    if m:
                        mid = int(m.group(1))
                        if kind in ('receive','echo') and (mid < 0 or m.group(2) != BODY.format(mid=mid)): break
                        found = (kind,mid,now); break
                if found:
                    with self.lock: self.events.append((*found, self.source))
            status = proc.wait()
            out.write(f'host_utc={utc()} host_mono_ns={time.monotonic_ns()} event=collector_exit rc={status}\n')
        return status

class Session:
    def __init__(self, args):
        self.args=args; self.sid=f'{int(time.time())}-{uuid.uuid4().hex[:10]}'
        self.root=Path(args.output).resolve()/self.sid; self.raw=self.root/'raw'; self.states=self.root/'state'
        self.label='validation-'+self.sid; self.names=[]; self.peer_name=f'mros2-cr-{self.sid}-peer'
        self.peer_pid=None; self.peer_collector=None; self.peer_thread=None
        self.current_name=None; self.current_ip=None; self.events=[]; self.lock=threading.Lock(); self.threads=[]
        self.hashes={k:digest(v) for k,v in {'app':args.app,'runtime':args.runtime,'peer':args.peer}.items()}
        self.owned_file=self.root/'ownership.json'

    def preflight(self, need_ip=True):
        free=shutil.disk_usage(self.root.parent).free
        net=docker(['network','inspect',NETWORK])
        if net.returncode: raise RuntimeError('network inspect failed: '+net.stderr.strip())
        nd=json.loads(net.stdout)[0]
        if nd.get('Id')!=NETWORK_ID or nd['IPAM']['Config'][0]['Subnet']!=SUBNET: raise RuntimeError('network identity/subnet mismatch')
        containers=docker(['ps','-a','--format','{{.Names}}'])
        if containers.returncode: raise RuntimeError('docker ps failed: '+containers.stderr.strip())
        image=docker(['image','inspect',IMAGE])
        if image.returncode or json.loads(image.stdout)[0]['Id']!=IMAGE_ID: raise RuntimeError('pinned image identity mismatch')
        occupied={x.get('IPv4Address','').split('/')[0]:x.get('Name') for x in (nd.get('Containers') or {}).values() if x.get('IPv4Address')}
        planned={'172.18.0.5'} if not need_ip else {'172.18.0.3','172.18.0.5'}
        if self.args.mode in ('changed','repeated'): planned.add('172.18.0.6')
        conflicts=planned & occupied.keys()
        if '172.18.0.5' in conflicts and str(occupied['172.18.0.5']).lstrip('/')==self.peer_name and self.inspect_owned(self.peer_name):
            conflicts.remove('172.18.0.5')
        if conflicts: raise RuntimeError(f'planned addresses occupied: { {ip:occupied[ip] for ip in conflicts} }')
        if self.peer_name in containers.stdout.splitlines() and not self.inspect_owned(self.peer_name): raise RuntimeError('peer name exists but is not owned by this session')
        if free < FREE_MIN: raise RuntimeError(f'free bytes {free} below 3 GiB reserve')
        return {'utc':utc(),'free_bytes':free,'minimum_free_bytes':FREE_MIN,'network_id':nd['Id'],'subnet':SUBNET,'occupied_ips':occupied,'image_id':IMAGE_ID,'artifact_hashes':self.hashes}

    def inspect_owned(self,name):
        r=docker(['inspect',name])
        if r.returncode: return None
        x=json.loads(r.stdout)[0]
        if x['Config']['Labels'].get(LABEL_KEY)!=self.label: raise RuntimeError(f'refusing non-owned container {name}')
        return x

    def create(self,name,ip,mounts,command='sleep infinity'):
        if docker(['inspect',name]).returncode==0: raise RuntimeError('refusing existing container name '+name)
        argv=['run','-d','--name',name,'--label',f'{LABEL_KEY}={self.label}','--network',NETWORK,'--ip',ip]
        for host,dst,ro in mounts:
            spec=f'type=bind,src={host},dst={dst}'+(',readonly' if ro else '')
            argv += ['--mount',spec]
        argv += [IMAGE,'sh','-c',command]
        r=docker(argv,120)
        with (self.raw/'docker-commands.log').open('a') as f: f.write(f'{utc()} rc={r.returncode} {shlex.join(argv)}\n{r.stdout}{r.stderr}\n')
        if r.returncode: raise RuntimeError(f'container create failed: {r.stderr.strip() or r.stdout.strip()}')
        self.names.append(name)
        rec=self.inspect_owned(name)
        if not rec or not rec['State']['Running']: raise RuntimeError(f'owned container not running {name}')
        return rec

    def launch(self,name,cmd,path,source):
        argv=['rtk','proxy','docker','exec',name,'sh','-c',cmd]
        write(path.with_suffix('.command.txt'),shlex.join(argv)+'\n')
        p=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
        c=Collector(path,source,self.events,self.lock)
        t=threading.Thread(target=c.consume,args=(p,),daemon=True); t.start(); self.threads.append((p,t))
        return p

    def wait_pid(self,name,path,proc,restore):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if path.exists() and path.read_text().strip().isdigit():
                pid=int(path.read_text().strip()); r=docker(['exec',name,'sh','-c',f'ps -p {pid} -o args='])
                args=r.stdout.strip()
                if '/runtime/iwasm' in args and ('--restore' in args)==restore: return pid,args
            if proc.poll() is not None: break
            time.sleep(.1)
        raise RuntimeError('iwasm process identity could not be verified')

    def ready_roundtrips(self, *, after=None, timeout=STALL_SECONDS):
        deadline=time.monotonic()+timeout; last=0
        while time.monotonic()<deadline:
            with self.lock: ev=list(self.events)
            groups=defaultdict(set)
            for event in ev:
                if event[0].startswith('trace'): continue
                kind,mid,_,source = event
                if kind in ('publish','callback') and source!='wasm': continue
                if kind in ('receive','echo') and source!='peer': continue
                if after is None or mid>after: groups[mid].add(kind)
            ids=sorted(mid for mid,kinds in groups.items() if all(k in kinds for k in KINDS))
            run=[]
            for mid in ids:
                if run and mid!=run[-1]+1: run=[]
                run.append(mid)
                if len(run)>=10: return run[-10:]
            last=max(ids,default=last)
            time.sleep(.1)
        raise RuntimeError(f'roundtrip gate timeout; last fully correlated ID={last}')

    def create_peer(self):
        raw=self.raw/'peer'; raw.mkdir(parents=True,exist_ok=True)
        self.create(self.peer_name,'172.18.0.5',[(self.raw,'/run/raw',False),(self.args.peer,'/native-peer',True)],'sleep infinity')
        pidfile=raw/'peer.pid'
        self.peer_proc=self.launch(self.peer_name,'echo $$ > /run/raw/peer/peer.pid; exec /native-peer',raw/'native-peer.log','peer')
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if pidfile.exists() and pidfile.read_text().strip().isdigit():
                self.peer_pid=int(pidfile.read_text().strip()); break
            if self.peer_proc.poll() is not None: break
            time.sleep(.1)
        if not self.peer_pid: raise RuntimeError('native peer PID unavailable')
        r=docker(['exec',self.peer_name,'sh','-c',f'ps -p {self.peer_pid} -o args='])
        if r.returncode or '/native-peer' not in r.stdout: raise RuntimeError('peer identity not verified')
        write(self.owned_file,json.dumps({'session_id':self.sid,'label_key':LABEL_KEY,'label_value':self.label,'peer_container':self.peer_name,'peer_pid':self.peer_pid,'peer_restarts':0},indent=2)+'\n')

    def create_app_container(self,ip,phase,state_override=None):
        name=f'mros2-cr-{self.sid}-app-{phase}'
        self.current_name=name; self.current_ip=ip
        raw=self.raw/phase; raw.mkdir(parents=True,exist_ok=True)
        state=Path(state_override) if state_override is not None else self.states/phase
        state.mkdir(parents=True,exist_ok=True)
        mounts=[(self.raw,'/run/raw',False),(self.args.runtime.parent,'/runtime',True),(self.args.app.parent,'/artifact',True),(state,'/state',False)]
        self.create(name,ip,mounts,'cd /state && sleep infinity')
        return name,raw,state

    def stop_owned(self,name):
        rec=self.inspect_owned(name)
        if not rec: return
        r=docker(['stop','--time','5',name],30)
        if r.returncode: raise RuntimeError(f'owned stop failed {name}: {r.stderr.strip()}')
        r=docker(['rm',name],30)
        if r.returncode: raise RuntimeError(f'owned rm failed {name}: {r.stderr.strip()}')

    def start_app(self,name,raw,restore):
        pidfile='/run/raw/'+raw.name+('/restore.pid' if restore else '/checkpoint.pid')
        log=raw/('restore.log' if restore else 'checkpoint.log')
        cmd=f"cd /state && echo $$ > {pidfile}; exec /runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 {'--restore ' if restore else ''}/artifact/{self.args.app.name}"
        proc=self.launch(name,cmd,log,'wasm')
        pid,args=self.wait_pid(name,raw/('restore.pid' if restore else 'checkpoint.pid'),proc,restore)
        write(raw/('restore.identity.txt' if restore else 'checkpoint.identity.txt'),f'pid={pid}\nargs={args}\n')
        return proc,pid

    def stop_app_process(self,name,pid,restore):
        r=docker(['exec',name,'sh','-c',f'ps -p {pid} -o args='])
        args=r.stdout.strip()
        if not args or '/runtime/iwasm' not in args or ('--restore' in args)!=restore:
            if not args: return
            raise RuntimeError('refusing to signal unexpected iwasm process')
        docker(['exec',name,'kill','-TERM',str(pid)],15)

    def state_manifest(self,state,raw):
        memory=state/'main-memory.img'; sock=state/'main-socket.img'
        if not memory.is_file() or memory.stat().st_size!=MEMORY_BYTES or not sock.is_file() or not sock.stat().st_size:
            raise RuntimeError('checkpoint is not exact fixed 1 GiB memory plus nonempty socket image')
        files=[]
        for p in sorted(state.rglob('*')):
            if p.is_symlink(): raise RuntimeError(f'checkpoint state contains symlink: {p}')
            if p.is_file(): files.append({'path':p.relative_to(state).as_posix(),'size':p.stat().st_size,'sha256':digest(p)})
        manifest={'state_dir':str(state.resolve()),'files':files,'memory_size':memory.stat().st_size,'socket_size':sock.stat().st_size}
        write(raw/'state-manifest.json',json.dumps(manifest,indent=2)+'\n')
        snap=self.guest_state(raw)
        manifest['guest_state']=snap
        write(raw/'state-manifest.json',json.dumps(manifest,indent=2)+'\n')
        return manifest

    def guest_state(self,raw):
        log=raw/'checkpoint.log'; lines=log.read_text(errors='replace').splitlines() if log.exists() else []
        candidates=[]
        for line in lines:
            if 'PHASE0 ' in line:
                fields=dict(re.findall(r'(\w+)=([^\s]+)',line.split('PHASE0 ',1)[1]))
                keys=('canary','default','ip','canary_addr','default_addr','ip_addr')
                if all(k in fields for k in keys): candidates.append(fields)
        if not candidates: raise RuntimeError('checkpoint log has no complete guest-state snapshot; state retained')
        fields=candidates[-1]
        required=('canary','default','ip','canary_addr','default_addr','ip_addr')
        if not all(re.fullmatch(r'0x[0-9a-fA-F]+',fields[k]) for k in required):
            raise RuntimeError('guest-state snapshot fields are not hexadecimal u32/addresses')
        memory=self.states/'phase-01'/'main-memory.img'
        image={}
        with memory.open('rb') as stream:
            for key in ('canary','default','ip'):
                stream.seek(int(fields[key+'_addr'],16)); image[key]=struct.unpack('<I',stream.read(4))[0]
        expected={key:int(fields[key],16) for key in ('canary','default','ip')}
        if image!=expected: raise RuntimeError(f'guest memory state mismatch: expected={expected} image={image}')
        return {'source':'main-memory.img; wasm32 little-endian u32 at logged guest offsets','values':{k:fields[k] for k in ('canary','default','ip')},'addresses':{k:fields[k+'_addr'] for k in ('canary','default','ip')},'image_values':image,'matches_snapshot':True}

    def verify_manifest(self,state,raw):
        m=json.loads((raw/'state-manifest.json').read_text())
        if Path(m['state_dir']).resolve()!=state.resolve() or state.resolve().parent!=self.states.resolve(): raise RuntimeError('state ownership path assertion failed')
        for item in m['files']:
            rel=Path(item['path'])
            if rel.is_absolute() or '..' in rel.parts: raise RuntimeError('unsafe state manifest path')
            p=state/rel
            if p.is_symlink() or not p.is_file() or p.stat().st_size!=item['size'] or digest(p)!=item['sha256']: raise RuntimeError('state manifest hash mismatch: '+item['path'])
        if not m.get('guest_state') or not all(m['guest_state'].get('values',{}).values()): raise RuntimeError('guest-state assertion missing')
        return m

    def remove_pass_state(self,state,raw,preserve_directory=False):
        # This method is called only after successful restore and round-trip gates.
        m=self.verify_manifest(state,raw)
        if Path(m['state_dir']).resolve()!=state.resolve() or state.resolve().parent!=self.states.resolve(): raise RuntimeError('refusing state cleanup outside this run')
        for item in m['files']:
            p=state/item['path']
            if not p.is_file() or digest(p)!=item['sha256']: raise RuntimeError('state changed before cleanup')
        for item in m['files']:
            (state/item['path']).unlink()
        if not preserve_directory:
            for p in sorted(state.rglob('*'),reverse=True):
                if p.is_dir(): p.rmdir()
            state.rmdir()
        write(raw/'pass-state-cleanup.json',json.dumps({'state':str(state),'manifest_sha256':digest(raw/'state-manifest.json'),'assertions':'manifest hashes + guest snapshot + restore roundtrip gate passed'},indent=2)+'\n')

    def phase(self,index,ip,after=None):
        raw=self.raw/f'phase-{index:02d}'; raw.mkdir(parents=True,exist_ok=False)
        preflight=self.preflight()
        write(raw/'preflight.json',json.dumps(preflight,indent=2)+'\n')
        name,state_raw,state=self.create_app_container(ip,f'phase-{index:02d}')
        proc,pid=self.start_app(name,state_raw,False)
        pre=self.ready_roundtrips(after=after)
        write(raw/'pre-roundtrips.json',json.dumps({'ids':pre,'fully_correlated':True,'body_match':True},indent=2)+'\n')
        free=shutil.disk_usage(self.root.parent).free
        if free<FREE_MIN: raise RuntimeError(f'checkpoint preflight free {free} below 3GiB')
        # Recheck app and container ownership immediately before SIGUSR2.
        if not self.inspect_owned(name): raise RuntimeError('app container ownership vanished')
        r=docker(['exec',name,'kill','-USR2',str(pid)],15)
        if r.returncode: raise RuntimeError('SIGUSR2 checkpoint failed: '+r.stderr.strip())
        proc.wait(timeout=600)
        if proc.returncode!=0: raise RuntimeError(f'checkpoint iwasm exit status {proc.returncode}; raw payload retained')
        manifest=self.state_manifest(state,state_raw)
        boundary=max(pre)
        # same restore address; changed/repeated alternate source and destination while peer remains untouched.
        dest_ip=ip
        if self.args.mode in ('changed','repeated') and index%2==1: dest_ip='172.18.0.6'
        restore_raw=state_raw
        if dest_ip!=ip:
            self.stop_owned(name)
            name,restore_raw,state=self.create_app_container(dest_ip,f'phase-{index:02d}-restore',state_override=state)
        restore_proc,restore_pid=self.start_app(name,restore_raw,True)
        post=self.ready_roundtrips(after=boundary)
        write(raw/'post-roundtrips.json',json.dumps({'ids':post,'fully_correlated':True,'body_match':True},indent=2)+'\n')
        self.verify_manifest(state,state_raw)
        write(raw/'assertions.json',json.dumps({'mode':self.args.mode,'phase':index,'same_lineage_state_restored':True,'pre_ids':pre,'post_ids':post,'unique_ids_after_checkpoint':min(post)>boundary,'guest_state_asserted':True,'checkpoint_memory_bytes':manifest['memory_size'],'application_hashes':self.hashes,'peer_container':self.peer_name,'peer_not_restarted':True},indent=2)+'\n')
        # On PASS, release the validated 1 GiB state before the next checkpoint.
        # The live restored process remains running; only its consumed dump files are removed.
        self.remove_pass_state(state,state_raw,preserve_directory=(self.args.mode=='repeated'))
        return restore_proc,restore_pid,name,dest_ip,max(post)

    def trace_report(self):
        with self.lock:
            records=[e[1] for e in self.events if e[0]=='trace']
            snapshots=[e[1] for e in self.events if e[0]=='trace_metrics']
        counts=defaultdict(int)
        for e in records:
            counts[f"kind_{TRACE_KINDS.get(e['kind'],'unknown')}"]+=1
            counts[f"result_{TRACE_RESULTS.get(e['result'],'unknown')}"]+=1
        outcomes=[e for e in records if e['kind']==3]
        sequential_duplicates=sum(1 for a,b in zip(outcomes,outcomes[1:])
            if a['current_ip']==b['current_ip'] and a['applied_ip']==b['applied_ip'] and a['result']==b['result'])
        metrics=snapshots[-1] if snapshots else None
        seqs=[e['seq'] for e in records]
        sequence_gaps=bool(seqs and any(b != a+1 for a,b in zip(seqs,seqs[1:])))
        eintr=sum(e['kind']==1 for e in records)
        probe_in=sum(e['kind']==4 for e in records); probe_out=sum(e['kind']==5 for e in records)
        failed=any(e['kind']==9 or (e['kind']==3 and e['result']==2) for e in records)
        applied_events=[e for e in records if e['kind']==11]
        final_applied=applied_events[-1] if applied_events else None
        reasons=[]
        if not records or eintr==0: reasons.append('missing EINTR/event telemetry')
        if metrics is None: reasons.append('missing observer metrics/loss counters')
        elif metrics['lost'] != 0: reasons.append('observer loss/overflow nonzero')
        if metrics and metrics['lockfree'] != 1: reasons.append('observer atomics not lockfree')
        if metrics and metrics['max_active'] > 1: reasons.append('measured probe overlap max_active > 1')
        if metrics and metrics['active'] != 0: reasons.append('probe interval left active')
        if metrics and (metrics['attempts'] != metrics['outcomes'] or
                        metrics['outcomes'] != metrics['winners']+metrics['busy']+metrics['failed']):
            reasons.append('trylock counter inconsistency')
        if metrics and metrics['probe_completions'] != probe_out: reasons.append('probe completion counter mismatch')
        if probe_in != probe_out or (metrics and metrics['probe_completions'] != probe_in):
            reasons.append('probe boundary imbalance')
        if sequence_gaps: reasons.append('trace sequence gap')
        if failed: reasons.append('projection preparation/refresh failure observed')
        return {'schema':TRACE_SCHEMA,'event_count':len(records),'counts':dict(sorted(counts.items())),
            'eintr_count':eintr,'probe_attempts':sum(e['kind']==2 for e in records),
            'trylock_outcomes':len(outcomes),'busy':sum(e['kind']==3 and e['result']==1 for e in records),
            'failed':sum(e['kind']==3 and e['result']==2 for e in records),
            'unchanged':sum(e['kind']==3 and e['result']==3 for e in records),
            'changed':sum(e['kind']==3 and e['result']==4 for e in records),
            'probe_enter':probe_in,'probe_exit':probe_out,'probe_overlap_max_active':metrics['max_active'] if metrics else None,
            'probe_completions':metrics['probe_completions'] if metrics else None,
            'sequential_duplicate_outcomes':sequential_duplicates,
            'current_events':sum(e['kind']==6 for e in records),'applied_events':sum(e['kind']==7 for e in records),
            'current_applied_observations':[{'kind':TRACE_KINDS.get(e['kind']),'current_ip':e['current_ip'],
                'applied_ip':e['applied_ip'],'thread_id':e['thread_id']} for e in records if e['kind'] in (6,7,11,12)],
            'final_applied_convergence':None if final_applied is None else {
                'current_ip':final_applied['current_ip'],'applied_ip':final_applied['applied_ip'],
                'converged':final_applied['current_ip']==final_applied['applied_ip']},
            'prepare_begin':sum(e['kind']==8 for e in records),'prepare_fail':sum(e['kind']==9 for e in records),
            'commit':sum(e['kind']==10 for e in records),'applied_last':sum(e['kind']==11 for e in records),
            'retry':sum(e['kind']==13 for e in records),'observer_metrics':metrics,
            'overflow':None if metrics is None else metrics['lost'],'sequence_gap':sequence_gaps,
            'telemetry_status':'READY' if not reasons else 'NOT PASS','not_pass_reasons':reasons,
            'records':records}

    def persist_trace_report(self):
        report=self.trace_report()
        write(self.root/'trace-report.json',json.dumps(report,indent=2)+'\\n')
        return report

    def run(self):
        self.root.mkdir(parents=True,exist_ok=False); self.raw.mkdir(); self.states.mkdir()
        write(self.root/'inputs.json',json.dumps({'session_id':self.sid,'mode':self.args.mode,'app':str(self.args.app),'runtime':str(self.args.runtime),'peer':str(self.args.peer),'hashes':self.hashes,'trace_app':str(self.args.trace_app.resolve()),'trace_manifest':str(self.args.trace_manifest.resolve()),'trace_schema':TRACE_SCHEMA,'telemetry_status':'awaiting runtime events and zero-loss/max_active readiness; NOT PASS'},indent=2)+'\n')
        setup=self.preflight()
        setup.update({'artifacts':{'app':str(self.args.app.resolve()),'runtime':str(self.args.runtime.resolve()),
            'peer':str(self.args.peer.resolve()),'trace_manifest':str(self.args.trace_manifest.resolve()) if self.args.trace_manifest else None},
            'artifact_hashes':self.hashes,'trace_schema':TRACE_SCHEMA,
            'commands':{'runtime':['/runtime/iwasm','--addr-pool=0.0.0.0/0','--max-threads=32','-v=5'],
                'peer':['/native-peer'],'observer_dump':'RTPS_TRACE seq=... parsed from native runtime stdout'},
            'disk_readiness':{'free_bytes':setup['free_bytes'],'minimum_per_checkpoint_bytes':FREE_MIN,
                'ready':setup['free_bytes'] >= FREE_MIN}})
        write(self.root/'setup.json',json.dumps(setup,indent=2)+'\n')
        self.create_peer()
        if self.args.mode=='no-cr':
            name,raw,_state=self.create_app_container('172.18.0.3','no-cr')
            proc,pid=self.start_app(name,raw,False)
            ids=self.ready_roundtrips()
            write(raw/'roundtrips.json',json.dumps({'ids':ids,'fully_correlated':True,'body_match':True},indent=2)+'\n')
            self.stop_app_process(name,pid,False)
            trace_report=self.persist_trace_report()
            write(self.root/'result.json',json.dumps({'status':'NO-CR communication smoke only','checkpoint_count':0,'ids':ids,'telemetry':trace_report['telemetry_status']},indent=2)+'\n')
            return
        initial_ip='172.18.0.3'
        proc,pid,app,ip,boundary=self.phase(1,initial_ip)
        count=1
        target=2 if self.args.mode=='repeated' else 1
        while count<target:
            count+=1
            # Continue the exact restored iwasm PID/container lineage, checkpoint it again.
            raw=self.raw/f'phase-{count:02d}'; raw.mkdir(parents=True,exist_ok=False)
            pre=self.ready_roundtrips(after=boundary)
            free=shutil.disk_usage(self.root.parent).free
            if free<FREE_MIN: raise RuntimeError(f'checkpoint preflight free {free} below 3GiB')
            r=docker(['exec',app,'kill','-USR2',str(pid)],15)
            if r.returncode: raise RuntimeError('repeat SIGUSR2 failed: '+r.stderr.strip())
            proc.wait(timeout=600)
            # Reuse the exact bind-mounted directory belonging to this restored app.
            state=self.states/'phase-01'; state_raw=raw
            # State directory mounted into app as /state only for first checkpoint; repeated dump writes there.
            # Record its complete exact-size image hashes and guest assertion before restore.
            manifest=self.state_manifest(state,raw)
            restore_proc,restore_pid=self.start_app(app,raw,True)
            post=self.ready_roundtrips(after=max(pre))
            self.verify_manifest(state,raw)
            write(raw/'assertions.json',json.dumps({'same_restored_lineage':True,'phase':count,'pre_ids':pre,'post_ids':post,'guest_state_asserted':True,'peer_not_restarted':True},indent=2)+'\n')
            self.remove_pass_state(state,raw,preserve_directory=True)
            proc,pid=restore_proc,restore_pid; boundary=max(post)
        # Retain a running restored app only until all assertions complete; terminate only owned process/container.
        self.stop_app_process(app,pid,True)
        trace_report=self.persist_trace_report()
        campaign_status='T12 NOT PASS; '+trace_report['telemetry_status']
        write(self.root/'result.json',json.dumps({'status':campaign_status,'runner_assertions':'PASS; named mode only','mode':self.args.mode,'checkpoint_count':count,'peer_restarts':0,'telemetry':trace_report['telemetry_status'],'application_hashes':self.hashes},indent=2)+'\n')

    def cleanup(self,keep_state):
        # Failed payloads may have been written into an owned container working tree;
        # preserve all owned containers until their files are captured and audited.
        if keep_state:
            write(self.root/'state-kept.txt','Failure/interrupt payload retained; owned containers preserved for artifact capture.\n')
            return
        # Container removal is limited to names created by this session and label-verified before action.
        for name in reversed(self.names):
            try: self.stop_owned(name)
            except Exception as e: write(self.root/'cleanup-error.txt',f'{name}: {e}\n')


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,default=APP_DEFAULT); p.add_argument('--runtime',type=Path,default=RUNTIME_DEFAULT); p.add_argument('--peer',type=Path,default=PEER_DEFAULT)
    p.add_argument('--mode',choices=('same','changed','repeated','no-cr'),default='same')
    p.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'runs')
    p.add_argument('--trace-app',type=Path); p.add_argument('--trace-manifest',type=Path)
    p.add_argument('--dry-run',action='store_true',help='validate artifact identity and print exact campaign plan; no Docker calls')
    return p.parse_args(argv)

def main(argv=None):
    args=parse_args(argv)
    paths={'app':args.app,'runtime':args.runtime,'peer':args.peer}
    missing=[f'{k}={v}' for k,v in paths.items() if not v.is_file()]
    if missing: raise SystemExit('missing artifact(s): '+', '.join(missing))
    actual={k:digest(v) for k,v in paths.items()}
    pinned={k:actual[k] for k in ('app','runtime','peer')}
    wrong={k:(pinned[k],HASHES[k]) for k in pinned if pinned[k]!=HASHES[k]}
    if wrong: raise SystemExit(f'artifact hash mismatch against T11 default pins: {wrong}')
    trace_status=''
    if not args.trace_app or not args.trace_manifest or not args.trace_app.is_file() or not args.trace_manifest.is_file():
        raise SystemExit('T12 execution requires --trace-app and --trace-manifest; uninstrumented fallback is forbidden')
    if args.trace_app or args.trace_manifest:
        try: tm=json.loads(args.trace_manifest.read_text())
        except Exception as e: raise SystemExit(f'invalid trace build manifest: {e}')
        if tm.get('status') != 'actual MODULE_echoback_string build passed' or tm.get('observer_linked_once') is not True:
            raise SystemExit('trace manifest does not prove successful private derivative build and single observer link')
        if Path(tm.get('wasm_path','')).resolve() != args.trace_app.resolve() or tm.get('wasm_sha256') != digest(args.trace_app):
            raise SystemExit('trace app path/hash does not match private derivative manifest')
        if tm.get('sysroot_mutated') is not False or tm.get('normal_artifacts_mutated') is not False:
            raise SystemExit('trace derivative manifest does not attest read-only normal artifacts/sysroot')
        telemetry=tm.get('trace_telemetry',{})
        if telemetry.get('schema')!='traceoverlay_event-v2' or telemetry.get('thread_id_printed') is not True or 'max_active' not in telemetry.get('metrics_printed',[]) or 'lost' not in telemetry.get('metrics_printed',[]):
            raise SystemExit('trace derivative does not attest full event/thread/loss/overlap telemetry')
        paths['app']=args.trace_app
        args.app=args.trace_app
        trace_status='private derivative manifest/path/hash validated; telemetry still must satisfy runtime readiness'
    plan={'mode':args.mode,'artifacts':sha_record(paths),'trace_status':trace_status,'checkpoint_count':0 if args.mode=='no-cr' else (2 if args.mode=='repeated' else 1),'peer_policy':'one owned peer container; no restart across campaign phases','disk_preflight':'>=3 GiB before every checkpoint','roundtrip_gate':'>=10 contiguous fully ID/body-correlated peer receive/echo + Wasm publish/callback tuples before and after each checkpoint','telemetry':'observer metrics/loss/overlap parser required; runtime telemetry unobserved; NOT T12 PASS'}
    if args.dry_run:
        print(json.dumps(plan,indent=2)); return 0
    sess=Session(args); success=False
    try:
        sess.run(); success=True
    except BaseException as e:
        if sess.root.exists():
            write(sess.root/'failure.json',json.dumps({'utc':utc(),'type':type(e).__name__,'message':str(e),'raw_payloads_retained':True},indent=2)+'\n')
        raise
    finally:
        if sess.root.exists(): sess.cleanup(keep_state=not success)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
