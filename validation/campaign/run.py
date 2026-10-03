#!/usr/bin/env python3
"""Owned, serial application checkpoint/restore campaign runner.

No network recreation or proxy restart is performed. Container operations are
restricted to containers bearing this run's unique ownership label.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
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
RUNTIME_DEFAULT = Path('/tmp/wamr-parent-restore-park-fix-20261002/build-fixed/iwasm')
PEER_DEFAULT = Path('/tmp/mros2-posix-run04-final-build/mros2-posix')
HASHES = {
    'app': 'b9b01ebf0523048e3af1ca07655c010a72ed364d7eacee05c61277058f09e9d9',
    'runtime': '70bfcdc4b109041deec3eef4677a605a3fb8d5e03cf16fb026ca4ca8a85938f3',
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
TRACE_METRICS = re.compile(r"RTPS_TRACE_METRICS (.*)")
TRACE_KINDS = {1:'eintr', 2:'trylock_attempt', 3:'trylock_outcome', 4:'probe_enter', 5:'probe_exit',
               6:'current', 7:'applied', 8:'prepare_begin', 9:'prepare_fail', 10:'commit',
               11:'applied_last', 12:'equal', 13:'retry'}
TRACE_RESULTS = {0:'unavailable', 1:'busy', 2:'failed', 3:'unchanged', 4:'changed'}
TRACE_SCHEMA = 'traceoverlay_event-v2;dedicated shared append observer;process windows, atomic batch delimiters, event sequence/byte boundaries, actual counter values/addresses, image-read baselines, explicit replay attribution'
GUEST_STATE_SCHEMA = 'guest-state-v1;actual wasm32 addresses + copied values;raw memory little-endian;IPv4 semantic bytes network-order'
GUEST_STATE_LINE = 'RTPS_GUEST_STATE '


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


def validate_normal_build_manifest(manifest_path, app, runtime, peer):
    try: manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    except Exception as exc: raise ValueError(f'invalid normal build provenance manifest: {exc}') from exc
    if manifest.get('schema')!='normal-wasm-build-provenance-v1' or manifest.get('status')!='clean normal build passed':
        raise ValueError('normal build provenance manifest schema/status mismatch')
    expected={'app':Path(app).resolve(),'runtime':Path(runtime).resolve(),'peer':Path(peer).resolve()}
    for key,path in expected.items():
        record=manifest.get('artifacts',{}).get(key,{})
        if Path(record.get('path','')).resolve()!=path:
            raise ValueError(f'normal build provenance {key} path mismatch')
        if record.get('sha256')!=digest(path):
            raise ValueError(f'normal build provenance {key} hash mismatch')
    sources=manifest.get('sources')
    if not isinstance(sources,list) or not sources:
        raise ValueError('normal build provenance source pins missing')
    for record in sources:
        path=Path(record.get('path',''))
        if not path.is_file() or digest(path)!=record.get('sha256'):
            raise ValueError(f'normal build source pin mismatch: {path}')
    if not manifest.get('configure_command') or not manifest.get('build_command'):
        raise ValueError('normal build provenance build commands missing')
    return manifest

def parse_trace_line(line):
    event=TRACE.fullmatch(line.strip())
    if event:
        seq,kind,result,current,applied,detail,aux,thread=map(int,event.groups())
        return ('trace',{'seq':seq,'kind':kind,'result':result,'current_ip':current,
            'applied_ip':applied,'detail':detail,'aux':aux,'thread_id':thread})
    metrics=TRACE_METRICS.fullmatch(line.strip())
    if metrics:
        values={}
        for token in metrics.group(1).split():
            if '=' not in token: return None
            key,value=token.split('=',1)
            try: values[key]=int(value,16 if key.startswith('addr_') else 10)
            except ValueError: values[key]=value
        return ('trace_metrics',values)
    for prefix,kind in (('RTPS_TRACE_WINDOW_START ','trace_window_start '),
                        ('RTPS_TRACE_BATCH_BEGIN ','trace_batch_begin '),
                        ('RTPS_TRACE_BATCH_END ','trace_batch_end ')):
        if line.startswith(prefix):
            values={}
            for token in line[len(prefix):].split():
                if '=' not in token: return None
                key,value=token.split('=',1)
                try: values[key]=int(value,16 if key.startswith('addr_') else 10)
                except ValueError: values[key]=value
            return (kind.strip(),values)
    return None


def parse_observer_channel(data):
    records=[]; batches=[]; current=None; errors=[]
    for line_number,line in enumerate(data.decode('utf-8',errors='replace').splitlines(),1):
        if not line: errors.append(f'empty observer line {line_number}'); continue
        if line.startswith('{'):
            try: records.append(('guest_state',json.loads(line)))
            except json.JSONDecodeError: errors.append(f'malformed JSON observer line {line_number}')
            continue
        parsed=parse_trace_line(line)
        if parsed and parsed[0]=='trace':
            if current is None: errors.append(f'trace event outside batch at line {line_number}')
            else: current['events'].append(parsed[1])
            continue
        if parsed and parsed[0]=='trace_metrics':
            if current is None: errors.append(f'metrics outside batch at line {line_number}')
            else: current['metrics'].append(parsed[1])
            continue
        if parsed and parsed[0]=='trace_window_start':
            if current is not None: errors.append(f'window start inside open batch at line {line_number}')
            records.append(('window_start',parsed[1])); continue
        if parsed and parsed[0]=='trace_batch_begin':
            if current is not None: errors.append(f'nested trace batch at line {line_number}')
            current={'begin':parsed[1],'events':[],'metrics':[],'line':line_number}; continue
        if parsed and parsed[0]=='trace_batch_end':
            if current is None: errors.append(f'batch end without start at line {line_number}'); continue
            end=parsed[1]; current['end']=end
            begin=current['begin']; events=current['events']; metrics=current['metrics']
            if begin.get('batch')!=end.get('batch'): errors.append(f'batch id mismatch at line {line_number}')
            if end.get('events')!=len(events): errors.append(f'batch event count mismatch at line {line_number}')
            if len(metrics)!=2 or [m.get('edge') for m in metrics]!=['before','after']:
                errors.append(f'batch counter snapshots incomplete at line {line_number}')
            elif metrics[0].get('batch')!=begin.get('batch') or metrics[1].get('batch')!=end.get('batch'):
                errors.append(f'batch metrics ID mismatch at line {line_number}')
            if events and (end.get('first')!=events[0]['seq'] or end.get('last')!=events[-1]['seq']):
                errors.append(f'batch event sequence boundary mismatch at line {line_number}')
            if len(metrics)==2:
                before,after=metrics
                if before.get('stable') not in (0,1) or after.get('stable') not in (0,1):
                    errors.append(f'batch lacks explicit stable/pending snapshot flags at line {line_number}')
                if before.get('read')!=begin.get('read') or before.get('next')!=begin.get('next'):
                    errors.append(f'batch start/counter sequence mismatch at line {line_number}')
                if end.get('read')!=after.get('read') or end.get('next')!=after.get('next'):
                    errors.append(f'batch end/counter sequence mismatch at line {line_number}')
                if ((after.get('read',0)-before.get('read',0))&0xffffffff)!=len(events):
                    errors.append(f'batch drained sequence count mismatch at line {line_number}')
                if any(event['seq']!=((before.get('read',0)+i)&0xffffffff) for i,event in enumerate(events)):
                    errors.append(f'batch interior sequence gap at line {line_number}')
                kinds=defaultdict(int)
                for event in events: kinds[event['kind']]+=1
                expected={'attempts':kinds[2],'outcomes':kinds[3],
                    'winners':sum(e['kind']==3 and e['result'] not in (1,2) for e in events),
                    'busy':sum(e['kind']==3 and e['result']==1 for e in events),
                    'failed':sum(e['kind']==3 and e['result']==2 for e in events),
                    'probe_completions':kinds[5]}
                stable=before.get('stable')==1 and after.get('stable')==1
                matched=all(((after.get(k,0)-before.get(k,0))&0xffffffff)==v for k,v in expected.items())
                current['counter_state']='closed' if stable and matched else 'pending'
                current['pending_reason']=None if stable and matched else 'counter snapshots unstable or include concurrent/prior events'
            batches.append(current); current=None; continue
        errors.append(f'unrecognized observer record at line {line_number}: {line[:100]}')
    if current is not None: errors.append('unterminated trace batch')
    return {'records':records,'batches':batches,'errors':errors}

class Collector:
    def __init__(self, path, source, events, lock):
        self.path, self.source, self.events, self.lock = path, source, events, lock
    def consume(self, proc):
        with self.path.open('w', encoding='utf-8') as out:
            for line in proc.stdout:
                now = time.monotonic_ns()
                rendered = f'host_utc={utc()} host_mono_ns={now} {line.rstrip()}\n'
                out.write(rendered); out.flush()
                # Trace rows are intentionally accepted only from the separate observer append file.
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
        self.reused_peer=False; self.peer_session_record=None; self.tail_procs=[]
        self.observer_windows=[]; self.observer_windows_by_proc={}; self.pass_states=[]
        self.final_pass=False; self.pending_restore_baseline=None
        self.checkpoint_archives=[]
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
        if self.args.mode=='no-cr':
            planned={self.args.no_cr_ip,'172.18.0.5'}
        else:
            planned={'172.18.0.3','172.18.0.5'} if need_ip else {'172.18.0.5'}
            if self.args.mode in ('changed','repeated'): planned.add('172.18.0.6')
        conflicts=planned & occupied.keys()
        reused_record=None; reused_name=None
        if self.args.reuse_peer_session:
            reused_record=json.loads(self.args.reuse_peer_session.read_text(encoding='utf-8'))
            reused_name=reused_record.get('peer_container')
            if not reused_name or not self.verify_reused_peer(reused_record):
                raise RuntimeError('reuse manifest does not prove live owned peer identity/log mount')
        if '172.18.0.5' in conflicts and str(occupied['172.18.0.5']).lstrip('/')==reused_name:
            conflicts.remove('172.18.0.5')
        elif '172.18.0.5' in conflicts and str(occupied['172.18.0.5']).lstrip('/')==self.peer_name and self.inspect_owned(self.peer_name):
            conflicts.remove('172.18.0.5')
        if conflicts: raise RuntimeError(f'planned addresses occupied: { {ip:occupied[ip] for ip in conflicts} }')
        if self.peer_name in containers.stdout.splitlines():
            if not (reused_record and self.peer_name==reused_name) and not self.inspect_owned(self.peer_name):
                raise RuntimeError('peer name exists but is not verified for this session')
        if free < FREE_MIN: raise RuntimeError(f'free bytes {free} below 3 GiB reserve')
        return {'utc':utc(),'free_bytes':free,'minimum_free_bytes':FREE_MIN,'network_id':nd['Id'],'subnet':SUBNET,'occupied_ips':occupied,'image_id':IMAGE_ID,'artifact_hashes':self.hashes}

    @staticmethod
    def _docker_argv(args):
        return ['rtk','proxy','docker',*map(str,args)]

    @staticmethod
    def _stream_text(value):
        if value is None: return ''
        if isinstance(value,bytes): return value.decode('utf-8',errors='replace')
        return str(value)

    @classmethod
    def _docker_exception_evidence(cls,args,exc):
        output=getattr(exc,'stdout',None)
        if output is None: output=getattr(exc,'output',None)
        message=f'{type(exc).__name__}: {exc}'
        return {'argv':cls._docker_argv(args),'docker_args':list(map(str,args)),
            'returncode':getattr(exc,'returncode',None),'stdout':cls._stream_text(output),
            'stderr':cls._stream_text(getattr(exc,'stderr',None)),
            'exception_type':type(exc).__name__,'error':message}

    def inspect_owned(self,name,expected_label=None,*,_audit_evidence=None):
        args=['inspect',name]
        try: r=docker(args)
        except Exception as exc:
            if _audit_evidence is not None: _audit_evidence.append(self._docker_exception_evidence(args,exc))
            raise
        evidence={'argv':self._docker_argv(args),'docker_args':args,'returncode':r.returncode,
            'stdout':r.stdout,'stderr':r.stderr}
        if _audit_evidence is not None: _audit_evidence.append(evidence)
        if r.returncode: return None
        x=json.loads(r.stdout)[0]
        if x['Config']['Labels'].get(LABEL_KEY)!=(expected_label or self.label): raise RuntimeError(f'refusing non-owned container {name}')
        return x

    def verify_reused_peer(self,record):
        if record.get('peer_sha256')!=self.hashes['peer'] or record.get('network_id')!=NETWORK_ID:
            raise RuntimeError('reused peer artifact/network hash mismatch')
        x=self.inspect_owned(record.get('peer_container',''),record.get('label_value'))
        if not x or x.get('Id')!=record.get('peer_container_id') or not x['State']['Running']:
            raise RuntimeError('reused peer container ID/ownership/runtime mismatch')
        network=x['NetworkSettings']['Networks'].get(NETWORK,{})
        if network.get('NetworkID')!=NETWORK_ID or network.get('IPAddress')!='172.18.0.5':
            raise RuntimeError('reused peer network address mismatch')
        mounts=x.get('Mounts',[])
        peer_mount=next((m for m in mounts if m['Destination']=='/native-peer' and not m['RW']),None)
        log_mount=next((m for m in mounts if m['Destination']=='/run/raw'),None)
        if not peer_mount or digest(peer_mount['Source'])!=self.hashes['peer']:
            raise RuntimeError('reused peer binary bind/hash mismatch')
        log=Path(record.get('peer_log','')).resolve()
        if not log.is_file() or not log_mount or str(Path(log_mount['Source']).resolve())!=record.get('peer_mount_source') or log.parent.parent!=Path(log_mount['Source']).resolve():
            raise RuntimeError('reused peer persistent log/mount mismatch')
        identity=docker(['exec',record['peer_container'],'sh','-c',f"ps -p {int(record['peer_pid'])} -o args=; cat /proc/{int(record['peer_pid'])}/stat"])
        lines=identity.stdout.splitlines()
        if identity.returncode or len(lines)<2 or '/native-peer' not in lines[0]:
            raise RuntimeError('reused peer process is not live')
        stat_fields=lines[1].split()
        if len(stat_fields)<22 or stat_fields[21]!=str(record.get('peer_start_ticks')):
            raise RuntimeError('reused peer PID/start identity changed')
        return True

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
        if self.args.reuse_peer_session:
            record_path=self.args.reuse_peer_session.resolve()
            record=json.loads(record_path.read_text(encoding='utf-8'))
            self.peer_name=record['peer_container']; self.peer_pid=int(record['peer_pid'])
            self.verify_reused_peer(record)
            if record.get('peer_sha256')!=self.hashes['peer'] or record.get('network_id')!=NETWORK_ID:
                raise RuntimeError('reused peer artifact/network identity mismatch')
            rec=self.inspect_owned(self.peer_name,record.get('label_value'))
            if not rec or rec['NetworkSettings']['Networks'][NETWORK]['IPAddress']!='172.18.0.5':
                raise RuntimeError('reused peer ownership/address mismatch')
            if rec['Config']['Labels'].get(LABEL_KEY)!=record.get('label_value'):
                raise RuntimeError('reused peer label does not match ownership record')
            identity=docker(['exec',self.peer_name,'sh','-c',f'ps -p {self.peer_pid} -o args=; awk \'{{print $22}}\' /proc/{self.peer_pid}/stat'])
            lines=identity.stdout.splitlines()
            if identity.returncode or not lines or '/native-peer' not in lines[0] or len(lines)<2 or lines[1]!=str(record['peer_start_ticks']):
                raise RuntimeError('reused peer PID/start identity is not continuous')
            log=Path(record['peer_log']); offset=log.stat().st_size
            tail=subprocess.Popen(['tail','-c',f'+{offset+1}','-F',str(log)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
            collector=Collector(self.raw/'peer/native-peer.log','peer',self.events,self.lock)
            thread=threading.Thread(target=collector.consume,args=(tail,),daemon=True); thread.start()
            self.threads.append((tail,thread)); self.tail_procs.append(tail); self.reused_peer=True; self.peer_session_record=record
            self.peer_collector=record_path
            write(self.owned_file,json.dumps({'session_id':self.sid,'reuses_session':record['session_id'],'label_key':LABEL_KEY,'label_value':record['label_value'],'peer_container':self.peer_name,'peer_pid':self.peer_pid,'peer_start_ticks':record['peer_start_ticks'],'peer_restarts':0},indent=2)+'\\n')
            return
        logfile=raw/'native-peer-live.log'
        peer_rec=self.create(self.peer_name,'172.18.0.5',[(self.raw,'/run/raw',False),(self.args.peer,'/native-peer',True)],'sleep infinity')
        pidfile=raw/'peer.pid'
        self.peer_proc=self.launch(self.peer_name,'echo $$ > /run/raw/peer/peer.pid; exec /native-peer >> /run/raw/peer/native-peer-live.log 2>&1',raw/'native-peer-exec.log','peer')
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if pidfile.exists() and pidfile.read_text().strip().isdigit():
                self.peer_pid=int(pidfile.read_text().strip()); break
            if self.peer_proc.poll() is not None: break
            time.sleep(.1)
        if not self.peer_pid: raise RuntimeError('native peer PID unavailable')
        identity=docker(['exec',self.peer_name,'sh','-c',f'ps -p {self.peer_pid} -o args=; awk \'{{print $22}}\' /proc/{self.peer_pid}/stat'])
        lines=identity.stdout.splitlines()
        if identity.returncode or not lines or '/native-peer' not in lines[0] or len(lines)<2: raise RuntimeError('peer identity not verified')
        start_ticks=lines[1]
        tail=subprocess.Popen(['tail','-F',str(logfile)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
        collector=Collector(raw/'native-peer.log','peer',self.events,self.lock)
        thread=threading.Thread(target=collector.consume,args=(tail,),daemon=True); thread.start()
        self.threads.append((tail,thread)); self.tail_procs.append(tail)
        record={'session_id':self.sid,'label_key':LABEL_KEY,'label_value':self.label,'peer_container':self.peer_name,'peer_container_id':peer_rec['Id'],'peer_pid':self.peer_pid,'peer_start_ticks':start_ticks,'peer_restarts':0,'peer_log':str(logfile.resolve()),'peer_mount_source':str(self.raw.resolve()),'peer_sha256':self.hashes['peer'],'network_id':NETWORK_ID}
        write(self.owned_file,json.dumps(record,indent=2)+'\n')
        if self.args.peer_session_file:
            write(self.args.peer_session_file,json.dumps(record,indent=2)+'\n')

    def create_app_container(self,ip,phase,state_override=None):
        name=f'mros2-cr-{self.sid}-app-{phase}'
        self.current_name=name; self.current_ip=ip
        raw=self.raw/phase; raw.mkdir(parents=True,exist_ok=True)
        state=Path(state_override) if state_override is not None else self.states/phase
        state.mkdir(parents=True,exist_ok=True)
        (self.raw/'observer').mkdir(parents=True,exist_ok=True)
        mounts=[(self.raw,'/run/raw',False),(self.args.runtime.parent,'/runtime',True),(self.args.app.parent,'/artifact',True),(state,'/state',False)]
        self.create(name,ip,mounts,'cd /state && sleep infinity')
        return name,raw,state

    @staticmethod
    def _lifecycle_status(rec):
        return dict(rec.get('State') or {})

    @staticmethod
    def _lifecycle_endpoint(rec):
        settings=rec.get('NetworkSettings')
        if not isinstance(settings,dict): return {'identity_error':'NetworkSettings missing or malformed'}
        networks=settings.get('Networks')
        if not isinstance(networks,dict): return {'identity_error':'NetworkSettings.Networks missing or malformed'}
        if NETWORK not in networks: return None
        endpoint=networks[NETWORK]
        if not isinstance(endpoint,dict): return {'identity_error':'campaign network endpoint malformed'}
        keys=('NetworkID','EndpointID','IPAddress','IPPrefixLen','Gateway','MacAddress')
        copied={key:endpoint.get(key) for key in keys}
        if not all(copied.get(key) for key in ('NetworkID','EndpointID','IPAddress')):
            return {'identity_error':'campaign endpoint identity fields are incomplete'}
        return copied

    def _append_lifecycle_audit(self,record):
        path=self.root/'container-lifecycle.jsonl'
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,sort_keys=True)+'\n')
            stream.flush(); os.fsync(stream.fileno())

    def _inspect_owned_container_id(self,container_id):
        args=['inspect',container_id]
        try: result=docker(args)
        except Exception as exc:
            evidence=self._docker_exception_evidence(args,exc)
            return None,evidence,evidence['error']
        evidence={'argv':self._docker_argv(args),'docker_args':args,'returncode':result.returncode,
            'stdout':result.stdout,'stderr':result.stderr}
        if result.returncode: return None,evidence,'container ID inspect failed'
        try: rec=json.loads(result.stdout)[0]
        except (json.JSONDecodeError,IndexError,TypeError): return None,evidence,'container ID inspect returned malformed JSON'
        if not isinstance(rec,dict): return None,evidence,'container ID inspect returned malformed object'
        if rec.get('Id')!=container_id: return None,evidence,'container ID identity mismatch'
        labels=(rec.get('Config') or {}).get('Labels') or {}
        if labels.get(LABEL_KEY)!=self.label: return rec,evidence,'container ownership label mismatch'
        return rec,evidence,None

    def _audit_lifecycle_rejection(self,name,container_id,action,error,*,inspection=None,before=None,endpoint=None,observed_after=None,endpoint_after=None):
        self._append_lifecycle_audit({'schema':'container-lifecycle-v1','utc':utc(),'action':action,
            'requested_name':name,'container_id':container_id,'ownership_inspection':inspection,
            'status_before':self._lifecycle_status(before) if before else None,
            'status_after':self._lifecycle_status(observed_after) if observed_after else None,
            'endpoint_before':endpoint,'endpoint_after':endpoint_after,
            'command':None,'docker_args':None,'returncode':None,'stdout':'','stderr':'','error':str(error),
            'inspection_exception':inspection if isinstance(inspection,dict) and inspection.get('exception_type') else None,
            'outcome':'rejected'})

    def stop_owned(self,name):
        initial_inspection=[]
        try:
            rec=self.inspect_owned(name,_audit_evidence=initial_inspection)
        except Exception as exc:
            evidence=initial_inspection[-1] if initial_inspection else self._docker_exception_evidence(['inspect',name],exc)
            self._audit_lifecycle_rejection(name,None,'stop',exc,inspection=evidence)
            raise
        if not rec:
            evidence=initial_inspection[-1] if initial_inspection else None
            self._audit_lifecycle_rejection(name,None,'stop','container not found or not owned',inspection=evidence)
            return
        container_id=rec.get('Id')
        endpoint=self._lifecycle_endpoint(rec)
        actual_name=str(rec.get('Name','')).lstrip('/')
        if not container_id:
            error='owned container immutable ID unavailable'
            self._audit_lifecycle_rejection(name,None,'stop',error,before=rec,endpoint=endpoint)
            raise RuntimeError(error)
        if actual_name==getattr(self,'peer_name',None) or (endpoint and endpoint.get('IPAddress')=='172.18.0.5'):
            error='refusing to retire the protected continuous .5 peer'
            self._audit_lifecycle_rejection(name,container_id,'stop',error,before=rec,endpoint=endpoint)
            raise RuntimeError(error)
        if endpoint and endpoint.get('NetworkID')!=NETWORK_ID:
            error='refusing container with unexpected campaign network identity'
            self._audit_lifecycle_rejection(name,container_id,'stop',error,before=rec,endpoint=endpoint)
            raise RuntimeError(error)

        # Always target and re-inspect the immutable full ID; names are only used
        # for initial ownership resolution and audit readability.
        before,inspection,error=self._inspect_owned_container_id(container_id)
        if error or not before or before.get('Id')!=container_id:
            message=error or 'owned container identity disappeared before stop'
            self._audit_lifecycle_rejection(name,container_id,'stop',message,inspection=inspection,before=rec,endpoint=endpoint)
            raise RuntimeError(message)
        fresh_endpoint=self._lifecycle_endpoint(before)
        if fresh_endpoint!=endpoint:
            message='owned container endpoint identity changed before stop'
            self._audit_lifecycle_rejection(name,container_id,'stop',message,inspection=inspection,before=before,endpoint=fresh_endpoint)
            raise RuntimeError(message)
        args=['stop','--time','5',container_id]
        result=None; command_exception=None
        try: result=docker(args,30)
        except Exception as exc: command_exception=self._docker_exception_evidence(args,exc)
        after,after_inspection,after_error=self._inspect_owned_container_id(container_id)
        outcome='passed' if result and result.returncode==0 and not after_error and after and self._lifecycle_status(after).get('Running') is False else 'failed'
        errors=[]
        if command_exception: errors.append(command_exception['error'])
        elif result and result.returncode: errors.append(f'docker stop rc={result.returncode}: {result.stderr.strip() or result.stdout.strip()}')
        if after_error: errors.append(after_error)
        elif after and self._lifecycle_status(after).get('Running') is not False:
            errors.append('container stopped status unknown after stop')
        error='; '.join(errors) or None
        self._append_lifecycle_audit({'schema':'container-lifecycle-v1','utc':utc(),'action':'stop',
            'requested_name':name,'container_id':container_id,'ownership_inspection':inspection,
            'after_inspection':after_inspection,'endpoint_before':fresh_endpoint,
            'endpoint_after':self._lifecycle_endpoint(after) if after else None,
            'status_before':self._lifecycle_status(before),'status_after':self._lifecycle_status(after) if after else None,
            'command':self._docker_argv(args),'docker_args':args,
            'returncode':result.returncode if result else (command_exception or {}).get('returncode'),
            'stdout':result.stdout if result else (command_exception or {}).get('stdout',''),
            'stderr':result.stderr if result else (command_exception or {}).get('stderr',''),
            'exception_type':(command_exception or {}).get('exception_type'),
            'error':error,'outcome':outcome})
        if outcome!='passed': raise RuntimeError(f'owned stop failed {name}: {error or (result.stderr.strip() if result else "unknown error")}')

        before_disconnect,disconnect_inspection,disconnect_error=self._inspect_owned_container_id(container_id)
        current_endpoint=self._lifecycle_endpoint(before_disconnect) if before_disconnect else None
        if disconnect_error or not before_disconnect or current_endpoint!=fresh_endpoint:
            message=disconnect_error or 'owned container identity/endpoint changed before disconnect'
            self._audit_lifecycle_rejection(name,container_id,'disconnect',message,inspection=disconnect_inspection,
                before=after,endpoint=fresh_endpoint,observed_after=before_disconnect,endpoint_after=current_endpoint)
            raise RuntimeError(message)
        if current_endpoint is None:
            self._append_lifecycle_audit({'schema':'container-lifecycle-v1','utc':utc(),'action':'disconnect',
                'requested_name':name,'container_id':container_id,'ownership_inspection':disconnect_inspection,
                'endpoint_before':None,'endpoint_after':None,'status_before':self._lifecycle_status(before_disconnect),
                'status_after':self._lifecycle_status(before_disconnect),'command':None,'docker_args':None,'returncode':None,
                'stdout':'','stderr':'','error':None,'outcome':'already-detached'})
            return
        if current_endpoint.get('IPAddress')=='172.18.0.5' or current_endpoint.get('NetworkID')!=NETWORK_ID:
            message='refusing disconnect of protected peer or unexpected network endpoint'
            self._audit_lifecycle_rejection(name,container_id,'disconnect',message,inspection=disconnect_inspection,
                before=before_disconnect,endpoint=current_endpoint)
            raise RuntimeError(message)
        network_id=current_endpoint['NetworkID']
        args=['network','disconnect',network_id,container_id]
        result=None; command_exception=None
        try: result=docker(args,30)
        except Exception as exc: command_exception=self._docker_exception_evidence(args,exc)
        after,after_inspection,after_error=self._inspect_owned_container_id(container_id)
        after_endpoint=self._lifecycle_endpoint(after) if after else None
        outcome='passed' if result and result.returncode==0 and not after_error and after and after_endpoint is None else 'failed'
        errors=[]
        if command_exception: errors.append(command_exception['error'])
        elif result and result.returncode: errors.append(f'docker network disconnect rc={result.returncode}: {result.stderr.strip() or result.stdout.strip()}')
        if after_error: errors.append(after_error)
        if outcome=='failed' and not errors:
            if after_endpoint is None: errors.append('disconnect command did not return success')
            elif isinstance(after_endpoint,dict) and after_endpoint.get('identity_error'):
                errors.append(f'campaign network endpoint status unknown after disconnect: {after_endpoint["identity_error"]}')
            else: errors.append('campaign network endpoint remains attached after disconnect')
        error='; '.join(errors) or None
        self._append_lifecycle_audit({'schema':'container-lifecycle-v1','utc':utc(),'action':'disconnect',
            'requested_name':name,'container_id':container_id,'ownership_inspection':disconnect_inspection,
            'after_inspection':after_inspection,'endpoint_before':current_endpoint,'endpoint_after':after_endpoint,
            'status_before':self._lifecycle_status(before_disconnect),'status_after':self._lifecycle_status(after) if after else None,
            'command':self._docker_argv(args),'docker_args':args,
            'returncode':result.returncode if result else (command_exception or {}).get('returncode'),
            'stdout':result.stdout if result else (command_exception or {}).get('stdout',''),
            'stderr':result.stderr if result else (command_exception or {}).get('stderr',''),
            'exception_type':(command_exception or {}).get('exception_type'),
            'error':error,'outcome':outcome})
        if outcome!='passed': raise RuntimeError(f'owned network disconnect failed {name}: {error or (result.stderr.strip() if result else "unknown error")}')

    def start_app(self,name,raw,restore):
        pidfile='/run/raw/'+raw.name+('/restore.pid' if restore else '/checkpoint.pid')
        log=raw/('restore.log' if restore else 'checkpoint.log')
        cmd=f"cd /state && echo $$ > {pidfile}; exec /runtime/iwasm --dir=/state --map-dir=/observer::/run/raw/observer --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 {'--restore ' if restore else ''}/artifact/{self.args.app.name}"
        observer=self.raw/'observer'/'trace-observer.log'
        offset=observer.stat().st_size if observer.exists() else 0
        inode=observer.stat().st_ino if observer.exists() else None
        proc=self.launch(name,cmd,log,'wasm')
        pid,args=self.wait_pid(name,raw/('restore.pid' if restore else 'checkpoint.pid'),proc,restore)
        identity=docker(['exec',name,'sh','-c',f'cat /proc/{pid}/stat'])
        stat_tail=identity.stdout.rsplit(')',1)[-1].split()
        if identity.returncode or len(stat_tail)<20: raise RuntimeError('runtime process start identity unavailable')
        start_ticks=stat_tail[19]
        window={'window_id':f'{"restore" if restore else "checkpoint"}-{len(self.observer_windows)+1}-pid{pid}',
            'role':'restore' if restore else 'checkpoint','pid':pid,'pid_start_ticks':start_ticks,
            'lineage_id':self.sid,'phase':raw.name,'container':name,'process_args':args,
            'app_hash':self.hashes['app'],'file':str(observer.resolve()),
            'inode_at_start':inode,'start_offset':offset,'start_utc':utc(),
            'expected_image_baseline':self.pending_restore_baseline if restore else None}
        self.pending_restore_baseline=None
        self.observer_windows.append(window); self.observer_windows_by_proc[id(proc)]=window
        write(self.raw/'observer-windows.json',json.dumps(self.observer_windows,indent=2)+'\\n')
        write(raw/('restore.identity.txt' if restore else 'checkpoint.identity.txt'),f'pid={pid}\\nargs={args}\\nstart_ticks={start_ticks}\\n')
        return proc,pid

    def finish_app_window(self,proc):
        window=self.observer_windows_by_proc.pop(id(proc),None)
        if not window: return
        observer=Path(window['file'])
        window['end_offset']=observer.stat().st_size if observer.exists() else window['start_offset']
        window['inode_at_end']=observer.stat().st_ino if observer.exists() else None
        window['end_utc']=utc()
        write(self.raw/'observer-windows.json',json.dumps(self.observer_windows,indent=2)+'\\n')

    def stop_app_process(self,name,pid,restore):
        r=docker(['exec',name,'sh','-c',f'ps -p {pid} -o args='])
        args=r.stdout.strip()
        if not args or '/runtime/iwasm' not in args or ('--restore' in args)!=restore:
            if not args: return
            raise RuntimeError('refusing to signal unexpected iwasm process')
        docker(['exec',name,'kill','-TERM',str(pid)],15)

    def persist_checkpoint_archive_record(self,record):
        write(record['record_path'],json.dumps(record,indent=2)+'\n')

    def archive_checkpoint_state(self,state,raw,phase):
        source=Path(state).resolve()
        archive_root=(self.root/'checkpoint-images').resolve()
        archive_dir=archive_root/f'phase-{phase:02d}'
        try:
            source.relative_to(self.states.resolve())
            archive_dir.relative_to(archive_root)
        except ValueError as exc:
            raise RuntimeError('checkpoint archive source/destination escaped session-owned roots') from exc
        if archive_dir == source or source in archive_dir.parents or archive_dir in source.parents:
            raise RuntimeError('checkpoint archive must be outside mutable working state')
        if archive_dir.exists():
            raise RuntimeError(f'checkpoint archive path already exists: {archive_dir}')
        expected=[]
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise RuntimeError(f'checkpoint archive refuses symlink: {path}')
            if path.is_file():
                stat=path.stat()
                expected.append({'path':path.relative_to(source).as_posix(),'size':stat.st_size,
                    'sha256':digest(path),'source_device':stat.st_dev,'source_inode':stat.st_ino})
        record={'phase':phase,'source_dir':str(source),'archive_dir':str(archive_dir),
            'expected_files':expected,'files':[],'complete':False,'state_manifest_path':None,
            'state_manifest_sha256':None,'record_path':str((raw/'checkpoint-archive.json').resolve())}
        self.checkpoint_archives.append(record)
        self.persist_checkpoint_archive_record(record)
        try:
            archive_dir.mkdir(parents=True,exist_ok=False)
            for item in expected:
                source_file=source/item['path']; archive_file=archive_dir/item['path']
                archive_file.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source_file,archive_file)
                archived=archive_file.stat()
                if (archived.st_size!=item['size'] or digest(archive_file)!=item['sha256'] or
                    (archived.st_dev==item['source_device'] and archived.st_ino==item['source_inode'])):
                    raise RuntimeError(f'checkpoint archive copy verification failed: {item["path"]}')
                if source_file.stat().st_size!=item['size'] or digest(source_file)!=item['sha256']:
                    raise RuntimeError(f'mutable checkpoint source changed during archive copy: {item["path"]}')
                record['files'].append({**item,'archive_device':archived.st_dev,'archive_inode':archived.st_ino})
                self.persist_checkpoint_archive_record(record)
            if len(record['files'])!=len(expected) or not expected:
                raise RuntimeError('checkpoint archive copy incomplete')
            record['complete']=True
            self.persist_checkpoint_archive_record(record)
            return record
        except Exception as exc:
            record['complete']=False; record['error']=f'{type(exc).__name__}: {exc}'
            self.persist_checkpoint_archive_record(record)
            raise RuntimeError(f'checkpoint archive failed; partial evidence retained: {exc}') from exc

    def validate_checkpoint_archives(self,expected_count):
        reasons=[]; snapshots=[]
        if len(self.checkpoint_archives)!=expected_count:
            reasons.append(f'expected {expected_count} checkpoint archives, found {len(self.checkpoint_archives)}')
        for record in self.checkpoint_archives:
            archive=Path(record['archive_dir']).resolve()
            source=Path(record['source_dir']).resolve()
            archive_root=(self.root/'checkpoint-images').resolve()
            try: archive.relative_to(archive_root)
            except ValueError: reasons.append(f'phase {record.get("phase")} archive escaped archive root')
            if archive==source or source in archive.parents or archive in source.parents:
                reasons.append(f'phase {record.get("phase")} archive overlaps mutable source')
            if not record.get('complete'):
                reasons.append(f'phase {record.get("phase")} archive copy incomplete')
            try:
                durable=json.loads(Path(record['record_path']).read_text())
                if durable.get('complete')!=record.get('complete') or durable.get('files')!=record.get('files'):
                    reasons.append(f'phase {record.get("phase")} archive record changed')
            except Exception:
                reasons.append(f'phase {record.get("phase")} archive record missing/malformed')
            expected=record.get('expected_files',[]); copied=record.get('files',[])
            if not expected or len(expected)!=len(copied) or {x.get('path') for x in expected}!={x.get('path') for x in copied}:
                reasons.append(f'phase {record.get("phase")} archive file inventory incomplete')
            verified=[]
            for item in expected:
                path=archive/item['path']
                try:
                    stat=path.stat()
                    actual_hash=digest(path)
                    ok=(path.is_file() and not path.is_symlink() and stat.st_size==item['size'] and
                        actual_hash==item['sha256'])
                except OSError:
                    stat=None; actual_hash=None; ok=False
                if not ok:
                    reasons.append(f'phase {record.get("phase")} archived file missing/mutated: {item["path"]}')
                archived=next((x for x in copied if x.get('path')==item['path']),None)
                if (archived is None or (stat is not None and
                    (stat.st_dev!=archived.get('archive_device') or stat.st_ino!=archived.get('archive_inode'))) or
                    (archived is not None and item['source_device']==archived.get('archive_device') and
                     item['source_inode']==archived.get('archive_inode'))):
                    reasons.append(f'phase {record.get("phase")} archive is not an independent copied inode: {item["path"]}')
                verified.append({'path':item['path'],'size':item['size'],'sha256':actual_hash,'valid':ok})
            try:
                actual_paths={p.relative_to(archive).as_posix() for p in archive.rglob('*') if p.is_file()}
                expected_paths={x['path'] for x in expected}
                if actual_paths!=expected_paths:
                    reasons.append(f'phase {record.get("phase")} archived tree has missing or extra files')
                if any(p.is_symlink() for p in archive.rglob('*')):
                    reasons.append(f'phase {record.get("phase")} archived tree contains symlinks')
            except OSError:
                reasons.append(f'phase {record.get("phase")} archived tree unavailable')
            manifest_path=Path(record.get('state_manifest_path') or '')
            try:
                manifest=json.loads(manifest_path.read_text())
                manifest_hash=digest(manifest_path)
            except Exception:
                manifest={}; manifest_hash=None
            if not manifest or manifest.get('state_dir')!=str(archive) or manifest_hash!=record.get('state_manifest_sha256'):
                reasons.append(f'phase {record.get("phase")} state manifest missing/mutated or points outside archive')
            else:
                mfiles=manifest.get('files',[])
                mf={x.get('path'):(x.get('size'),x.get('sha256')) for x in mfiles}
                ef={x.get('path'):(x.get('size'),x.get('sha256')) for x in expected}
                if mf!=ef: reasons.append(f'phase {record.get("phase")} state manifest/file inventory mismatch')
                guest=manifest.get('guest_state',{})
                counters=manifest.get('trace_counter_image_baseline',{})
                if ('main-memory.img' in ef and (manifest.get('memory_size')!=MEMORY_BYTES or
                    not manifest.get('socket_size') or guest.get('matches_checkpoint_image') is not True or
                    counters.get('observed_snapshot_matches_image') is not True)):
                    reasons.append(f'phase {record.get("phase")} fixed memory/socket or saved guest/counter byte assertions missing')
            snapshots.append({'phase':record.get('phase'),'archive_dir':str(archive),
                'state_manifest_path':str(manifest_path),'files':verified,'valid':not any(f'phase {record.get("phase")} ' in x for x in reasons)})
        return {'valid':not reasons,'expected_checkpoint_count':expected_count,
            'archive_count':len(self.checkpoint_archives),'reasons':reasons,'snapshots':snapshots}

    def write_checkpoint_archive_integrity(self,raw,label,expected_count):
        report=self.validate_checkpoint_archives(expected_count)
        write(raw/f'checkpoint-archive-{label}.json',json.dumps(report,indent=2)+'\n')
        if not report['valid']:
            raise RuntimeError('checkpoint archive integrity failed before successor operation: '+report['reasons'][0])
        return report

    def state_manifest(self,state,raw,observation_log=None,archive_record=None,expected_ip=None):
        memory=state/'main-memory.img'; sock=state/'main-socket.img'
        if not memory.is_file() or memory.stat().st_size!=MEMORY_BYTES or not sock.is_file() or not sock.stat().st_size:
            raise RuntimeError('checkpoint is not exact fixed 1 GiB memory plus nonempty socket image')
        files=[]
        for p in sorted(state.rglob('*')):
            if p.is_symlink(): raise RuntimeError(f'checkpoint state contains symlink: {p}')
            if p.is_file(): files.append({'path':p.relative_to(state).as_posix(),'size':p.stat().st_size,'sha256':digest(p)})
        manifest={'state_dir':str(state.resolve()),'files':files,'memory_size':memory.stat().st_size,'socket_size':sock.stat().st_size}
        write(raw/'state-manifest.json',json.dumps(manifest,indent=2)+'\n')
        snap=self.guest_state(raw,observation_log=observation_log,state=state,expected_ip=expected_ip)
        manifest['guest_state']=snap
        baseline=self.trace_counter_image_baseline(state)
        manifest['trace_counter_image_baseline']=baseline
        if self.observer_windows:
            window=self.observer_windows[-1]
            baseline['window_id']=window['window_id']
            window['image_trace_baseline']=baseline
            write(self.raw/'observer-windows.json',json.dumps(self.observer_windows,indent=2)+'\\n')
        write(raw/'state-manifest.json',json.dumps(manifest,indent=2)+'\n')
        if archive_record is not None:
            archive_record['state_manifest_path']=str((raw/'state-manifest.json').resolve())
            archive_record['state_manifest_sha256']=digest(raw/'state-manifest.json')
            self.persist_checkpoint_archive_record(archive_record)
        return manifest

    def trace_counter_image_baseline(self,state):
        log=self.raw/'observer'/'trace-observer.log'
        if not log.is_file(): raise RuntimeError('trace observer channel missing at checkpoint image audit')
        parsed=parse_observer_channel(log.read_bytes())
        if parsed['errors']: raise RuntimeError('malformed trace observer channel: '+parsed['errors'][0])
        candidates=[values for kind,values in parsed['records'] if kind=='window_start']
        candidates.extend(metric for batch in parsed['batches'] for metric in batch['metrics'])
        needed=('read','next','attempts','winners','busy','failed','outcomes','probe_completions',
                'active','max_active','lost','output_failures','lockfree')
        candidate=next((row for row in reversed(candidates)
            if all(isinstance(row.get('addr_'+key),int) for key in needed)),None)
        if candidate is None: raise RuntimeError('no actual observer counter addresses emitted before checkpoint')
        memory=state/'main-memory.img'; image_size=memory.stat().st_size
        values={}; addresses={}; image_bytes={}
        with memory.open('rb') as stream:
            for key in needed:
                address=candidate['addr_'+key]
                if address<0 or address+4>image_size: raise RuntimeError(f'trace observer {key} address outside saved WASM memory')
                stream.seek(address); raw=stream.read(4)
                if len(raw)!=4: raise RuntimeError(f'trace observer {key} image read incomplete')
                values[key]=struct.unpack('<I',raw)[0]
                addresses[key]=f'0x{address:08x}'; image_bytes[key]=raw.hex()
        return {'schema':'trace-counter-image-v1','addresses':addresses,'values':values,
            'image_bytes_le':image_bytes,'source_addresses_emitted_by_guest':True,
            'observed_snapshot_values':{key:candidate.get(key) for key in needed},
            'observed_snapshot_matches_image':all(candidate.get(key)==values[key] for key in needed),
            'memory_image':str(memory.resolve()),'memory_size':image_size}

    def guest_state(self,raw,observation_log=None,state=None,expected_ip=None):
        log=self.raw/'observer'/'trace-observer.log'
        lines=log.read_text(errors='replace').splitlines() if log.exists() else []
        records=[]
        for line in lines:
            if not line.startswith('{'): continue
            try: record=json.loads(line)
            except (json.JSONDecodeError, TypeError):
                raise RuntimeError('malformed actual guest-state observer record; state retained')
            records.append(record)
        if not records:
            raise RuntimeError('checkpoint log has no current guest-state observer records; state retained')
        c_records=[r for r in records if r.get('part')=='c']
        cpp_records=[r for r in records if r.get('part')=='cpp']
        if not c_records or not cpp_records:
            raise RuntimeError('checkpoint lacks actual C netif or C++ projection observer record; state retained')
        c,cpp=c_records[-1],cpp_records[-1]
        if c.get('schema')!=GUEST_STATE_SCHEMA or cpp.get('schema')!=GUEST_STATE_SCHEMA:
            raise RuntimeError('guest-state observer schema/endianness mismatch; state retained')
        memory=(state or self.states/'phase-01')/'main-memory.img'
        if not memory.is_file() or memory.stat().st_size!=MEMORY_BYTES:
            raise RuntimeError('guest-state image is not the exact 1 GiB checkpoint; state retained')
        image_size=memory.stat().st_size
        def address(value, name, width):
            if not isinstance(value,str) or not re.fullmatch(r'0x[0-9a-fA-F]+',value):
                raise RuntimeError(f'{name} is not an emitted hexadecimal guest address; state retained')
            result=int(value,16)
            if result<0 or result+width>image_size:
                raise RuntimeError(f'{name} falls outside saved guest memory; state retained')
            return result
        def hex_value(value,name):
            if not isinstance(value,str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,8}',value):
                raise RuntimeError(f'{name} is not an emitted u32 value; state retained')
            return int(value,16)
        fields=(('ip_field_addr','ip_value'),('netmask_field_addr','netmask_value'))
        parsed={}
        default_ptr=hex_value(c.get('default_ptr'),'default_ptr')
        if default_ptr==0: raise RuntimeError('actual netif_default pointer is null; state retained')
        default_ptr_addr=address(c.get('default_ptr_field_addr'),'default_ptr_field_addr',4)
        with memory.open('rb') as stream:
            stream.seek(default_ptr_addr); pointer_image=stream.read(4)
            if len(pointer_image)!=4 or struct.unpack('<I',pointer_image)[0]!=default_ptr:
                raise RuntimeError('netif_default pointer value does not match checkpoint bytes; state retained')
            for addr_key,value_key in fields:
                offset=address(c.get(addr_key),addr_key,4)
                expected=hex_value(c.get(value_key),value_key)
                stream.seek(offset); saved=stream.read(4)
                if len(saved)!=4 or struct.unpack('<I',saved)[0]!=expected:
                    raise RuntimeError(f'{value_key} does not match checkpoint image little-endian bytes; state retained')
                parsed[value_key]={'address':c[addr_key],'value':c[value_key],'image_bytes_le':saved.hex()}
        applied_addr=address(cpp.get('applied_field_addr'),'applied_field_addr',4)
        applied=hex_value(cpp.get('applied_value'),'applied_value')
        with memory.open('rb') as stream:
            stream.seek(applied_addr); saved=stream.read(4)
        if len(saved)!=4 or struct.unpack('<I',saved)[0]!=applied:
            raise RuntimeError('applied IP copied value does not match checkpoint bytes; state retained')
        ip=hex_value(c.get('ip_value'),'ip_value')
        if expected_ip is not None:
            try: planned_ip=int.from_bytes(ipaddress.IPv4Address(expected_ip).packed,'little')
            except (ValueError,TypeError): raise RuntimeError('planned phase IP is not a valid IPv4 address; state retained')
            if ip!=planned_ip:
                observed_ip=ipaddress.IPv4Address(ip.to_bytes(4,'little'))
                raise RuntimeError(f'copied guest/image IPv4 {observed_ip} differs from planned phase IP {expected_ip}; state retained')
        if applied!=ip or hex_value(cpp.get('current_ip_value'),'current_ip_value')!=ip:
            raise RuntimeError('current/applied IP observations do not match actual netif IP; state retained')
        guid_addr=address(cpp.get('guid_prefix_addr'),'guid_prefix_addr',12)
        if not isinstance(cpp.get('guid_prefix'),str) or not re.fullmatch(r'[0-9a-fA-F]{24}',cpp['guid_prefix']):
            raise RuntimeError('actual immutable participant GUID prefix bytes missing; state retained')
        with memory.open('rb') as stream:
            stream.seek(guid_addr); guid_bytes=stream.read(12)
        if guid_bytes.hex()!=cpp['guid_prefix'].lower():
            raise RuntimeError('participant GUID prefix does not match saved checkpoint bytes; state retained')
        locator=cpp.get('selected_locator')
        if cpp.get('selection_absent') is True:
            if locator is not None: raise RuntimeError('absent endpoint selection also supplied a locator; state retained')
            if int(cpp.get('user_writer_count',0))+int(cpp.get('user_reader_count',0))>0:
                raise RuntimeError('user endpoints exist but observer selection is absent; state retained')
            raise RuntimeError('echo app checkpoint lacks expected user endpoint locator; state retained')
        else:
            if not isinstance(locator,dict) or locator.get('role') not in ('writer','reader'):
                raise RuntimeError('selected user endpoint locator observation missing; state retained')
            loc_addr=address(locator.get('address_field_addr'),'locator.address_field_addr',16)
            port_addr=address(locator.get('port_field_addr'),'locator.port_field_addr',4)
            kind_addr=address(locator.get('kind_field_addr'),'locator.kind_field_addr',4)
            endpoint_guid_addr=address(locator.get('endpoint_guid_addr'),'locator.endpoint_guid_addr',16)
            if not isinstance(locator.get('address_bytes'),str) or not re.fullmatch(r'[0-9a-fA-F]{32}',locator['address_bytes']):
                raise RuntimeError('selected locator actual address bytes missing; state retained')
            if not isinstance(locator.get('endpoint_guid'),str) or not re.fullmatch(r'[0-9a-fA-F]{32}',locator['endpoint_guid']):
                raise RuntimeError('selected user endpoint full GUID/key observation missing; state retained')
            with memory.open('rb') as stream:
                stream.seek(loc_addr); loc_image=stream.read(16)
                stream.seek(port_addr); port_image=stream.read(4)
                stream.seek(kind_addr); kind_image=stream.read(4)
                stream.seek(endpoint_guid_addr); endpoint_guid_image=stream.read(16)
            if (loc_image.hex()!=locator['address_bytes'].lower() or
                struct.unpack('<I',port_image)[0]!=hex_value(locator.get('port_value'),'locator.port_value') or
                struct.unpack('<i',kind_image)[0]!=locator.get('kind_value') or
                endpoint_guid_image.hex()!=locator['endpoint_guid'].lower()):
                raise RuntimeError('selected live locator/GUID copied values do not match checkpoint image; state retained')
            if loc_image[12:16]!=struct.pack('<I',ip):
                raise RuntimeError('selected locator IPv4 bytes do not match current network-order IP; state retained')
        return {'schema':GUEST_STATE_SCHEMA,'source':'actual C/C++ observer addresses and copied values verified against main-memory.img',
            'default_ptr':c['default_ptr'],'default_ptr_field_addr':c['default_ptr_field_addr'],'ip':parsed['ip_value'],
            'netmask':parsed['netmask_value'],'applied_ip':{'address':cpp['applied_field_addr'],'value':cpp['applied_value'],'image_bytes_le':saved.hex()},
            'participant_guid_prefix':{'address':cpp['guid_prefix_addr'],'bytes':cpp['guid_prefix'].lower()},
            'selection_absent':cpp.get('selection_absent') is True,'selected_locator':locator,
            'expected_phase_ip':expected_ip,'matches_checkpoint_image':True}

    def wait_guest_state_observation(self, raw, roundtrip_ids, *, log_path=None, stage='pre-checkpoint', timeout=30, expected_ip=None):
        """Require fresh post-gate C/C++ value observations before SIGUSR2.

        Collector monotonic timestamps establish ordering only; they are not a
        guest-clock or latency measurement. The checkpoint image remains the
        value oracle.
        """
        log=self.raw/'observer'/'trace-observer.log'
        gate_events=[]
        wanted=set(roundtrip_ids)
        with self.lock:
            for event in self.events:
                if len(event)>=4 and event[0]=='callback' and event[1] in wanted and event[3]=='wasm':
                    gate_events.append((event[1],event[2]))
        if {mid for mid,_ in gate_events}!=wanted:
            raise RuntimeError('cannot establish guest-state collector gate from all pre-checkpoint callbacks')
        gate_mono=max(t for _,t in gate_events)
        watermark=log.stat().st_size if log.exists() else 0
        watermark_inode=log.stat().st_ino if log.exists() else None
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            observations=[]
            if log.exists():
                if watermark_inode is not None and log.stat().st_ino!=watermark_inode:
                    raise RuntimeError('dedicated observer file inode changed after roundtrip watermark')
                with log.open('rb') as stream:
                    stream.seek(watermark)
                    while True:
                        offset=stream.tell(); rawline=stream.readline()
                        if not rawline: break
                        line=rawline.decode('utf-8',errors='replace')
                        if not line.startswith('{'): continue
                        try: value=json.loads(line)
                        except json.JSONDecodeError:
                            raise RuntimeError('malformed dedicated guest-state observer record')
                        observations.append({'offset':offset,'host_mono_ns':None,'record':value})
            c=next((x for x in reversed(observations) if x['record'].get('part')=='c'),None)
            cpp=next((x for x in reversed(observations) if x['record'].get('part')=='cpp'),None)
            if c and cpp:
                cv,sv=c['record'],cpp['record']
                if cv.get('schema')!=GUEST_STATE_SCHEMA or sv.get('schema')!=GUEST_STATE_SCHEMA:
                    raise RuntimeError('fresh guest-state observation has unsupported schema')
                try:
                    current=int(cv['ip_value'],16); applied=int(sv['applied_value'],16)
                    cpp_current=int(sv['current_ip_value'],16)
                    locator=sv['selected_locator']
                    locator_bytes=bytes.fromhex(locator['address_bytes'])
                    loc_ip=locator_bytes[12:16]
                except (KeyError,TypeError,ValueError):
                    raise RuntimeError('fresh guest-state observation is incomplete')
                if current!=applied or current!=cpp_current or loc_ip!=struct.pack('<I',current):
                    raise RuntimeError('fresh current/applied/selected-locator IP values disagree')
                if expected_ip is not None:
                    try: planned_ip=int.from_bytes(ipaddress.IPv4Address(expected_ip).packed,'little')
                    except (ValueError,TypeError): raise RuntimeError('planned phase IP is not a valid IPv4 address')
                    if current!=planned_ip:
                        observed_ip=ipaddress.IPv4Address(current.to_bytes(4,'little'))
                        raise RuntimeError(f'copied guest IPv4 {observed_ip} differs from planned phase IP {expected_ip}')
                if sv.get('selection_absent') is True or int(sv.get('user_writer_count',0))+int(sv.get('user_reader_count',0))<1:
                    raise RuntimeError('expected echo app user endpoint selection is absent')
                report={'schema':GUEST_STATE_SCHEMA,'fresh_after_roundtrip_gate':True,'planned_ip':expected_ip,
                    'precheckpoint_roundtrip_ids':list(roundtrip_ids),'collector_gate_mono_ns':gate_mono,
                    'observer_file_path':str(log.resolve()),'observer_file_inode_before_gate':watermark_inode,
                    'observer_file_inode_after_gate':log.stat().st_ino,'consumed_log_byte_watermark':watermark,
                    'observer_file_end_offset':log.stat().st_size,'c_record_offset':c['offset'],'c_record_mono_ns':None,
                    'cpp_record_offset':cpp['offset'],'cpp_record_mono_ns':None,
                    'ordering_claim':'dedicated observer file-byte ordering only; not guest-clock precision',
                    'current_ip_value':cv['ip_value'],'applied_ip_value':sv['applied_value'],
                    'selected_locator_role':locator.get('role'),'user_writer_count':sv.get('user_writer_count'),
                    'user_reader_count':sv.get('user_reader_count')}
                write(raw/f'guest-state-{stage}.json',json.dumps(report,indent=2)+'\n')
                return report
            time.sleep(.05)
        raise RuntimeError('no fresh complete C/C++ guest-state observer pair after pre-checkpoint roundtrip gate')

    def verify_manifest(self,state,raw):
        m=json.loads((raw/'state-manifest.json').read_text())
        state=Path(state).resolve()
        if Path(m['state_dir']).resolve()!=state: raise RuntimeError('state ownership path assertion failed')
        allowed_roots=(self.states.resolve(),(self.root/'checkpoint-images').resolve())
        if not any(state==root or root in state.parents for root in allowed_roots):
            raise RuntimeError('state manifest path is outside mutable and immutable session-owned roots')
        for item in m['files']:
            rel=Path(item['path'])
            if rel.is_absolute() or '..' in rel.parts: raise RuntimeError('unsafe state manifest path')
            p=state/rel
            if p.is_symlink() or not p.is_file() or p.stat().st_size!=item['size'] or digest(p)!=item['sha256']: raise RuntimeError('state manifest hash mismatch: '+item['path'])
        if not m.get('guest_state') or not all(m['guest_state'].get('values',{}).values()): raise RuntimeError('guest-state assertion missing')
        return m

    def persist_checkpoint_preflight(self, raw):
        free=shutil.disk_usage(self.root.parent).free
        # Reserve one GiB for the WAMR dump and one GiB for its independent archive,
        # plus a MiB margin for socket/thread metadata, while retaining the 3-GiB floor.
        dump_reserve=MEMORY_BYTES
        archive_reserve=MEMORY_BYTES+1024**2
        required=FREE_MIN+dump_reserve+archive_reserve
        record={'utc':utc(),'free_bytes':free,'minimum_free_bytes':FREE_MIN,
                'checkpoint_dump_reserve_bytes':dump_reserve,'archive_copy_reserve_bytes':archive_reserve,
                'required_free_bytes':required,'ready':free>=required}
        write(raw/'checkpoint-preflight.json',json.dumps(record,indent=2)+'\n')
        if free<required:
            raise RuntimeError(f'checkpoint preflight free {free} below dump+archive+3GiB reserve {required}')
        return record

    def phase(self,index,ip,after=None):
        raw=self.raw/f'phase-{index:02d}'; raw.mkdir(parents=True,exist_ok=False)
        preflight=self.preflight()
        write(raw/'preflight.json',json.dumps(preflight,indent=2)+'\n')
        name,state_raw,state=self.create_app_container(ip,f'phase-{index:02d}')
        proc,pid=self.start_app(name,state_raw,False)
        pre=self.ready_roundtrips(after=after)
        write(raw/'pre-roundtrips.json',json.dumps({'ids':pre,'fully_correlated':True,'body_match':True},indent=2)+'\n')
        guest_observation=self.wait_guest_state_observation(state_raw,pre,expected_ip=ip)
        # Persist the exact dump+archive+3-GiB reserve immediately before the checkpoint signal.
        self.persist_checkpoint_preflight(raw)
        # Recheck app and container ownership immediately before SIGUSR2.
        if not self.inspect_owned(name): raise RuntimeError('app container ownership vanished')
        r=docker(['exec',name,'kill','-USR2',str(pid)],15)
        if r.returncode: raise RuntimeError('SIGUSR2 checkpoint failed: '+r.stderr.strip())
        proc.wait(timeout=600)
        self.finish_app_window(proc)
        if proc.returncode!=0: raise RuntimeError(f'checkpoint iwasm exit status {proc.returncode}; raw payload retained')
        archive_record=self.archive_checkpoint_state(state,state_raw,index)
        archive_state=Path(archive_record['archive_dir'])
        manifest=self.state_manifest(archive_state,state_raw,archive_record=archive_record,expected_ip=ip)
        self.pending_restore_baseline=manifest['trace_counter_image_baseline']
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
        post_guest_observation=self.wait_guest_state_observation(raw,post,log_path=restore_raw/'restore.log',stage='post-restore',expected_ip=dest_ip)
        self.verify_manifest(archive_state,state_raw)
        original_ip=guest_observation['current_ip_value']; restored_ip=post_guest_observation['current_ip_value']
        same_ip=(dest_ip==ip and original_ip==restored_ip)
        if self.args.mode=='same' and not same_ip:
            raise RuntimeError(f'SAME case original/restored IP mismatch: {original_ip} != {restored_ip}; payload retained')
        assertions={'mode':self.args.mode,'phase':index,'same_lineage_state_restored':True,'pre_ids':pre,'post_ids':post,'unique_ids_after_checkpoint':min(post)>boundary,'guest_state_asserted':True,'checkpoint_memory_bytes':manifest['memory_size'],'checkpoint_ip':original_ip,'restore_ip':restored_ip,'same_ip_asserted':same_ip,'application_hashes':self.hashes,'peer_container':self.peer_name,'peer_not_restarted':True}
        write(raw/'assertions.json',json.dumps(assertions,indent=2)+'\n')
        self.pass_states.append({'state':str(state.resolve()),'archive_state':str(archive_state.resolve()),
            'raw':str(state_raw.resolve()),'manifest':str((state_raw/'state-manifest.json').resolve()),
            'assertions':str((state_raw/'assertions.json').resolve()),'manifest_sha256':digest(state_raw/'state-manifest.json'),
            'assertions_sha256':digest(state_raw/'assertions.json')})
        return restore_proc,restore_pid,name,dest_ip,max(post)

    def trace_report(self):
        observer=self.raw/'observer'/'trace-observer.log'
        reasons=[]; windows=[]; all_events=[]; branch_events={}; replays=[]; seen={}
        if not observer.is_file(): reasons.append('dedicated observer file missing')
        for window in self.observer_windows:
            if 'end_offset' not in window:
                reasons.append(f"{window['window_id']} lacks closed process byte boundary"); continue
            try:
                with observer.open('rb') as stream:
                    stream.seek(window['start_offset']); data=stream.read(window['end_offset']-window['start_offset'])
            except OSError as exc:
                reasons.append(f"{window['window_id']} observer read failed: {exc}"); continue
            parsed=parse_observer_channel(data)
            reasons.extend(f"{window['window_id']}: {error}" for error in parsed['errors'])
            starts=[value for kind,value in parsed['records'] if kind=='window_start']
            if len(starts)!=1: reasons.append(f"{window['window_id']} has {len(starts)} start snapshots")
            start=starts[0] if starts else None
            snapshot_keys=('read','next','attempts','winners','busy','failed','outcomes','probe_completions','active','max_active','lost','output_failures','lockfree')
            if start and not all(isinstance(start.get('addr_'+key),int) for key in snapshot_keys): reasons.append(f"{window['window_id']} start counter addresses are incomplete")
            if start and start.get('stable')!=1: reasons.append(f"{window['window_id']} start snapshot was unstable")
            metrics=[row for batch in parsed['batches'] for row in batch['metrics']]
            final_rows=[row for row in metrics if row.get('edge')=='after']
            final=final_rows[-1] if final_rows else None
            if final is None: reasons.append(f"{window['window_id']} lacks final metrics snapshot")
            elif not all(isinstance(final.get('addr_'+key),int) for key in snapshot_keys): reasons.append(f"{window['window_id']} final counter addresses are incomplete")
            elif final.get('stable')!=1 and not window.get('image_trace_baseline'):
                reasons.append(f"{window['window_id']} final scalar snapshot was unstable")
            expected=window.get('expected_image_baseline')
            if expected and start:
                for key,value in expected.get('values',{}).items():
                    if start.get(key)!=value: reasons.append(f"{window['window_id']} restore baseline {key} differs from saved image")
                for key,address in expected.get('addresses',{}).items():
                    if start.get('addr_'+key)!=int(address,16): reasons.append(f"{window['window_id']} restore address {key} differs from saved image")
            image=window.get('image_trace_baseline')
            initial=(expected or {}).get('values') if expected else ({k:start.get(k) for k in ('read','next','attempts','winners','busy','failed','outcomes','probe_completions','active','max_active','lost','output_failures','lockfree')} if start else {})
            terminal=image.get('values') if image else ({k:final.get(k) for k in ('read','next','attempts','winners','busy','failed','outcomes','probe_completions','active','max_active','lost','output_failures','lockfree')} if final else {})
            if not start: reasons.append(f"{window['window_id']} lacks actual baseline")
            events=[event for batch in parsed['batches'] for event in batch['events']]
            all_events.extend(events); branch_events[window['window_id']]=[]
            pending=set(); owner=(expected or {}).get('window_id')
            if expected:
                read=expected['values'].get('read',0); next_seq=expected['values'].get('next',0)
                outstanding=(next_seq-read)&0xffffffff
                if outstanding>256: reasons.append(f"{window['window_id']} restored queue length exceeds capacity")
                else: pending={(read+i)&0xffffffff for i in range(outstanding)}
            expected_seq=initial.get('next') if initial else None
            local_replays=[]
            for event in events:
                signature=tuple(event[k] for k in ('seq','kind','result','current_ip','applied_ip','detail','aux','thread_id'))
                prior=seen.get(event['seq'])
                if event['seq'] in pending:
                    if prior and prior!=signature: reasons.append(f"{window['window_id']} replay event {event['seq']} differs from prior bytes")
                    if owner in branch_events: branch_events[owner].append(event)
                    else: reasons.append(f"{window['window_id']} pending event {event['seq']} has no image owner")
                    local_replays.append({'seq':event['seq'],'kind':'checkpoint-pending-tail','owner':owner}); replays.append(local_replays[-1]); continue
                if prior is not None:
                    if prior!=signature: reasons.append(f"{window['window_id']} duplicate seq {event['seq']} differs")
                    else:
                        local_replays.append({'seq':event['seq'],'kind':'exact-replay','owner':'prior-process-window'}); replays.append(local_replays[-1]); continue
                if expected_seq is not None and event['seq']!=expected_seq:
                    reasons.append(f"{window['window_id']} sequence gap: expected {expected_seq}, got {event['seq']}")
                expected_seq=(event['seq']+1)&0xffffffff; seen[event['seq']]=signature
                branch_events[window['window_id']].append(event)
            if image:
                read=image['values'].get('read',0); next_seq=image['values'].get('next',0)
                outstanding=(next_seq-read)&0xffffffff
                if outstanding>256: reasons.append(f"{window['window_id']} image ring queue exceeds capacity")
                window_pending=[(read+i)&0xffffffff for i in range(min(outstanding,256))]
            else:
                outstanding=((terminal.get('next',0)-terminal.get('read',0))&0xffffffff) if terminal else 0
                window_pending=[]
                if outstanding: reasons.append(f"{window['window_id']} ended with {outstanding} undrained ring events")
            deltas={k:((terminal[k]-initial[k])&0xffffffff) for k in ('attempts','winners','busy','failed','outcomes','probe_completions','lost','output_failures') if k in terminal and k in initial}
            windows.append({'window_id':window['window_id'],'lineage_id':window.get('lineage_id'),'role':window['role'],
                'phase':window.get('phase'),'container':window.get('container'),'app_hash':window.get('app_hash'),
                'pid':window['pid'],'pid_start_ticks':window['pid_start_ticks'],
                'process_args':window.get('process_args'),'byte_offsets':[window['start_offset'],window['end_offset']],
                'initial_snapshot':initial,'final_snapshot':terminal,'counter_deltas':deltas,
                'raw_events':len(events),'replays':local_replays,'pending_sequences':window_pending,
                'pending_count':outstanding,'batches':len(parsed['batches']),
                'initial_addresses':(expected or {}).get('addresses') or ({k:f"0x{start.get('addr_'+k,0):08x}" for k in ('read','next','attempts','winners','busy','failed','outcomes','probe_completions','active','max_active','lost','output_failures','lockfree')} if start else {}),
                'final_addresses':(image or {}).get('addresses') or ({k:f"0x{final.get('addr_'+k,0):08x}" for k in ('read','next','attempts','winners','busy','failed','outcomes','probe_completions','active','max_active','lost','output_failures','lockfree')} if final else {}),
                'pending_batch_ids':[b['begin'].get('batch') for b in parsed['batches'] if b.get('counter_state')=='pending'],
                'pending_batch_resolution':'pending','image_baseline':image})
        for window in windows:
            events=branch_events.get(window['window_id'],[]); delta=window['counter_deltas']; final=window['final_snapshot']
            kinds=defaultdict(int)
            for event in events: kinds[event['kind']]+=1
            checks={'attempts':kinds[2],'outcomes':kinds[3],
                'winners':sum(e['kind']==3 and e['result'] not in (1,2) for e in events),
                'busy':sum(e['kind']==3 and e['result']==1 for e in events),
                'failed':sum(e['kind']==3 and e['result']==2 for e in events),
                'probe_completions':kinds[5]}
            consistent=True
            for key,value in checks.items():
                if delta.get(key)!=value:
                    consistent=False; reasons.append(f"{window['window_id']} {key} counter delta {delta.get(key)} != attributed events {value}")
            if consistent and window['pending_count']==0:
                window['pending_batch_resolution']='closed by actual process/image initial/final scalar deltas'
            elif consistent and window['image_baseline']:
                window['pending_batch_resolution']='checkpoint counter delta exact; saved-image ring tail attributed on restore'
            else: window['pending_batch_resolution']='unresolved; telemetry NOT PASS'
            if kinds[4]!=kinds[5]: reasons.append(f"{window['window_id']} probe entry/exit imbalance")
            if delta.get('outcomes')!=delta.get('winners',0)+delta.get('busy',0)+delta.get('failed',0): reasons.append(f"{window['window_id']} outcome counter partition mismatch")
            if delta.get('lost',0)!=0 or delta.get('output_failures',0)!=0: reasons.append(f"{window['window_id']} loss or observer write failure")
            if final.get('lockfree')!=1: reasons.append(f"{window['window_id']} atomics not lockfree")
            if final.get('max_active',0)>1: reasons.append(f"{window['window_id']} measured overlap exceeds one")
            if final.get('active')!=0: reasons.append(f"{window['window_id']} has active probe at end")
        unique=[event for events in branch_events.values() for event in events]
        counts=defaultdict(int)
        for event in unique:
            counts[f"kind_{TRACE_KINDS.get(event['kind'],'unknown')}"]+=1
            counts[f"result_{TRACE_RESULTS.get(event['result'],'unknown')}"]+=1
        eintr=sum(event['kind']==1 for event in unique)
        if any(event['kind']==9 or (event['kind']==3 and event['result']==2) for event in unique):
            reasons.append('projection preparation/refresh failure observed')
        if eintr==0: reasons.append('missing EINTR event telemetry')
        if len(unique)<10: reasons.append('trace event count below required smoke coverage')
        if not windows: reasons.append('no complete process telemetry windows')
        applied=next((event for event in reversed(unique) if event['kind']==11),None)
        convergence=bool(applied and applied['current_ip']==applied['applied_ip'])
        if not convergence: reasons.append('no final current/applied convergence event')
        reasons=list(dict.fromkeys(reasons))
        return {'schema':TRACE_SCHEMA,'observer_file':str(observer.resolve()),'output_channel':'validated append-only shared observer FD','stdout_trace_fallback':False,
            'event_count':len(unique),'raw_event_count':len(all_events),'counts':dict(counts),'eintr_count':eintr,
            'replay_count':len(replays),'replays':replays,'windows':windows,'sequence_gap':any('sequence gap' in r for r in reasons),
            'overflow':sum(w['counter_deltas'].get('lost',0) for w in windows),
            'guest_state_output_failures':sum(w['counter_deltas'].get('output_failures',0) for w in windows),
            'final_applied_convergence':None if applied is None else {'current_ip':applied['current_ip'],'applied_ip':applied['applied_ip'],'converged':convergence},
            'telemetry_status':'READY' if not reasons else 'NOT PASS','not_pass_reasons':reasons,'records':unique}

    def persist_trace_report(self):
        report=self.trace_report()
        write(self.root/'trace-report.json',json.dumps(report,indent=2)+'\n')
        return report

    def run(self):
        self.root.mkdir(parents=True,exist_ok=False); self.raw.mkdir(); self.states.mkdir()
        (self.raw/'observer').mkdir(parents=True,exist_ok=True)
        write(self.root/'inputs.json',json.dumps({'session_id':self.sid,'mode':self.args.mode,'app':str(self.args.app),'runtime':str(self.args.runtime),'peer':str(self.args.peer),'hashes':self.hashes,'trace_app':str(self.args.trace_app.resolve()) if self.args.trace_app else None,'trace_manifest':str(self.args.trace_manifest.resolve()) if self.args.trace_manifest else None,'normal_build_manifest':str(self.args.normal_build_manifest.resolve()) if self.args.normal_build_manifest else None,'trace_schema':TRACE_SCHEMA if self.args.trace_app else None,'trace_observer_file':str((self.raw/'observer'/'trace-observer.log').resolve()) if self.args.trace_app else None,'telemetry_status':'awaiting runtime events and zero-loss/max_active readiness; NOT PASS' if self.args.trace_app else 'not instrumented; normal no-C/R control only'},indent=2)+'\n')
        setup=self.preflight()
        setup.update({'artifacts':{'app':str(self.args.app.resolve()),'runtime':str(self.args.runtime.resolve()),
            'peer':str(self.args.peer.resolve()),'trace_manifest':str(self.args.trace_manifest.resolve()) if self.args.trace_manifest else None,
            'normal_build_manifest':str(self.args.normal_build_manifest.resolve()) if self.args.normal_build_manifest else None},
            'artifact_hashes':self.hashes,'trace_schema':TRACE_SCHEMA,
            'commands':{'runtime':['/runtime/iwasm','--addr-pool=0.0.0.0/0','--max-threads=32','-v=5'],
                'peer':['/native-peer'],'observer_dump':'/observer/trace-observer.log validated shared append FD; stdout is never a telemetry source'},
            'disk_readiness':{'free_bytes':setup['free_bytes'],'minimum_per_checkpoint_bytes':FREE_MIN,
                'ready':setup['free_bytes'] >= FREE_MIN}})
        write(self.root/'setup.json',json.dumps(setup,indent=2)+'\n')
        self.create_peer()
        if self.args.mode=='no-cr':
            name,raw,_state=self.create_app_container(self.args.no_cr_ip,'no-cr')
            proc,pid=self.start_app(name,raw,False)
            ids=self.ready_roundtrips()
            write(raw/'roundtrips.json',json.dumps({'ids':ids,'fully_correlated':True,'body_match':True},indent=2)+'\n')
            self.stop_app_process(name,pid,False)
            proc.wait(timeout=30); self.finish_app_window(proc)
            trace_report=self.persist_trace_report() if self.args.trace_app else None
            write(self.root/'result.json',json.dumps({'status':'NO-CR communication smoke only','checkpoint_count':0,'ids':ids,'fully_correlated':len(ids)>=10,'body_match':len(ids)>=10,'controlCasePassed':bool(self.args.normal_no_cr_control and len(ids)>=10),'actualCasePassed':False,'normal_app_control':bool(self.args.normal_no_cr_control),'telemetry':trace_report['telemetry_status'] if trace_report else 'not instrumented (normal control)'},indent=2)+'\n')
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
            active_log=self.raw/'phase-01'/'restore.log'
            self.wait_guest_state_observation(raw,pre,log_path=active_log,expected_ip=ip)
            self.write_checkpoint_archive_integrity(raw,'before-successor-checkpoint',count-1)
            self.persist_checkpoint_preflight(raw)
            r=docker(['exec',app,'kill','-USR2',str(pid)],15)
            if r.returncode: raise RuntimeError('repeat SIGUSR2 failed: '+r.stderr.strip())
            proc.wait(timeout=600); self.finish_app_window(proc)
            # Keep the mutable /state mount for WAMR restore, but archive this dump
            # outside it before any future checkpoint can overwrite those files.
            state=self.states/'phase-01'; state_raw=raw
            archive_record=self.archive_checkpoint_state(state,raw,count)
            archive_state=Path(archive_record['archive_dir'])
            manifest=self.state_manifest(archive_state,raw,observation_log=active_log,archive_record=archive_record,expected_ip=ip)
            self.pending_restore_baseline=manifest['trace_counter_image_baseline']
            restore_proc,restore_pid=self.start_app(app,raw,True)
            post=self.ready_roundtrips(after=max(pre))
            self.wait_guest_state_observation(raw,post,log_path=active_log,stage='post-restore',expected_ip=ip)
            self.verify_manifest(archive_state,raw)
            self.write_checkpoint_archive_integrity(raw,'after-successor-restore',count)
            assertions={'same_restored_lineage':True,'phase':count,'pre_ids':pre,'post_ids':post,'guest_state_asserted':True,'peer_not_restarted':True}
            write(raw/'assertions.json',json.dumps(assertions,indent=2)+'\n')
            self.pass_states.append({'state':str(state.resolve()),'archive_state':str(archive_state.resolve()),
                'raw':str(raw.resolve()),'manifest':str((raw/'state-manifest.json').resolve()),
                'assertions':str((raw/'assertions.json').resolve()),'manifest_sha256':digest(raw/'state-manifest.json'),
                'assertions_sha256':digest(raw/'assertions.json')})
            proc,pid=restore_proc,restore_pid; boundary=max(post)
        # Retain a running restored app only until all assertions complete; terminate only owned process/container.
        self.stop_app_process(app,pid,True)
        proc.wait(timeout=30); self.finish_app_window(proc)
        trace_report=self.persist_trace_report()
        expected_count=2 if self.args.mode=='repeated' else 1
        assertions_persisted=(len(self.pass_states)>=expected_count and all(
            Path(item['manifest']).is_file() and Path(item['assertions']).is_file() and
            digest(Path(item['manifest']))==item['manifest_sha256'] and
            digest(Path(item['assertions']))==item['assertions_sha256'] for item in self.pass_states[-expected_count:]))
        same_ip_asserted=(self.args.mode!='same' or all(
            json.loads(Path(item['assertions']).read_text()).get('same_ip_asserted') is True and
            json.loads(Path(item['assertions']).read_text()).get('checkpoint_ip')==json.loads(Path(item['assertions']).read_text()).get('restore_ip')
            for item in self.pass_states[-expected_count:]))
        self.finalize_campaign_verdict(trace_report,count,expected_count,assertions_persisted,same_ip_asserted)

    def finalize_campaign_verdict(self,trace_report,count,expected_count,assertions_persisted,same_ip_asserted):
        retention=self.validate_checkpoint_archives(expected_count)
        write(self.root/'checkpoint-retention.json',json.dumps(retention,indent=2)+'\n')
        gates=(trace_report['telemetry_status']=='READY' and count==expected_count and assertions_persisted
               and same_ip_asserted and retention['valid'])
        self.final_pass=bool(gates)
        reasons=list(retention['reasons'])
        if trace_report['telemetry_status']!='READY': reasons.append('telemetry is not READY')
        if count!=expected_count: reasons.append(f'checkpoint count {count} != required {expected_count}')
        if not assertions_persisted: reasons.append('phase assertions/manifests are not persisted and hash-stable')
        if not same_ip_asserted: reasons.append('same-IP invariant failed')
        campaign_status='PASS' if self.final_pass else 'T12 NOT PASS; '+('; '.join(reasons) or trace_report['telemetry_status'])
        mode=self.args.mode
        result={'status':campaign_status,'runner_assertions':'PASS; named mode only',
            'actualCasePassed':bool(mode in ('same','changed','repeated') and self.final_pass),
            'controlCasePassed':False,'mode':mode,'checkpoint_count':count,'peer_restarts':0,
            'telemetry':trace_report['telemetry_status'],'all_phase_assertions_persisted':assertions_persisted,
            'checkpoint_retention':retention,'pass_states':self.pass_states,'application_hashes':self.hashes}
        self.persist_campaign_verdict(result)
        return result

    def persist_campaign_verdict(self,result):
        write(self.root/'result.json',json.dumps(result,indent=2)+'\n')
        if not self.final_pass:
            trace=json.loads((self.root/'trace-report.json').read_text()) if (self.root/'trace-report.json').is_file() else {}
            write(self.root/'failure.json',json.dumps({'status':result.get('status'),'reason':'campaign verdict did not pass every gate',
                'telemetry_status':trace.get('telemetry_status'),'telemetry_not_pass_reasons':trace.get('not_pass_reasons',[]),
                'payloads_retained':True,'pass_assertions_so_far':self.pass_states},indent=2)+'\n')
        self.cleanup_pass_state_files()

    def cleanup_pass_state_files(self):
        if not getattr(self.args,'cleanup_pass_state',False) or not self.final_pass: return
        result_path=self.root/'result.json'; trace_path=self.root/'trace-report.json'
        if not result_path.is_file() or not trace_path.is_file(): return
        result=json.loads(result_path.read_text()); trace=json.loads(trace_path.read_text())
        if result.get('status')!='PASS' or trace.get('telemetry_status')!='READY': return
        items=[]
        item_paths=set()
        cleanup_dirs=set()
        for item in self.pass_states:
            state=Path(item['state']).resolve(); archive_value=item.get('archive_state')
            archive=Path(archive_value if archive_value else state).resolve()
            manifest=Path(item['manifest']).resolve(); assertions=Path(item['assertions']).resolve()
            if state.parent!=self.states.resolve() or not state.is_dir(): raise RuntimeError('refusing cleanup outside session-owned state path')
            archive_root=(self.root/'checkpoint-images').resolve()
            if archive_value and (archive_root not in archive.parents or not archive.is_dir()):
                raise RuntimeError('refusing cleanup outside immutable checkpoint archive root')
            if not archive_value and archive!=state:
                raise RuntimeError('legacy cleanup state/archive mismatch')
            if digest(manifest)!=item['manifest_sha256'] or digest(assertions)!=item['assertions_sha256']:
                raise RuntimeError('assertion/manifest changed before pass cleanup')
            self.verify_manifest(archive,Path(item['raw']))
            cleanup_dirs.update((state,archive))
            for directory in (state,archive):
                for path in sorted(directory.rglob('*')):
                    if path.is_symlink(): raise RuntimeError('refusing cleanup of symlinked state path')
                    resolved=str(path.resolve())
                    if path.is_file() and resolved not in item_paths:
                        items.append({'path':resolved,'sha256':digest(path),'size':path.stat().st_size})
                        item_paths.add(resolved)
        cleanup_manifest={'campaign_result_sha256':digest(result_path),'trace_report_sha256':digest(trace_path),
            'assertions_and_manifests':[{'assertions':x['assertions'],'assertions_sha256':x['assertions_sha256'],
                'manifest':x['manifest'],'manifest_sha256':x['manifest_sha256']} for x in self.pass_states],
            'owned_paths':items}
        manifest_path=self.root/'pass-cleanup-manifest.json'
        write(manifest_path,json.dumps(cleanup_manifest,indent=2)+'\n')
        for path in (result_path,trace_path):
            if digest(path)!=cleanup_manifest['campaign_result_sha256' if path==result_path else 'trace_report_sha256']:
                raise RuntimeError('verdict artifacts changed after cleanup manifest persistence')
        for item in items:
            path=Path(item['path'])
            if not path.is_file() or digest(path)!=item['sha256']: raise RuntimeError('owned state changed before cleanup')
        for item in items: Path(item['path']).unlink()
        for state in sorted(cleanup_dirs,reverse=True):
            if state.exists():
                for directory in sorted((p for p in state.rglob('*') if p.is_dir()),reverse=True): directory.rmdir()
                state.rmdir()
        write(self.root/'pass-state-cleanup.json',json.dumps({'manifest':str(manifest_path),'manifest_sha256':digest(manifest_path),'removed_paths':items},indent=2)+'\n')

    def cleanup(self,keep_state):
        for proc in self.tail_procs:
            if proc.poll() is None: proc.terminate()
        if keep_state or not self.final_pass or not getattr(self.args,'cleanup_owned_containers',False):
            if keep_state or not self.final_pass:
                write(self.root/'state-kept.txt','NOT PASS or interrupted; checkpoint payloads and owned containers preserved for artifact capture.\n')
            return
        for name in reversed(self.names):
            if self.args.keep_peer and name==self.peer_name: continue
            try: self.stop_owned(name)
            except Exception as e: write(self.root/'cleanup-error.txt',f'{name}: {e}\n')


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,default=APP_DEFAULT); p.add_argument('--runtime',type=Path,default=RUNTIME_DEFAULT); p.add_argument('--peer',type=Path,default=PEER_DEFAULT)
    p.add_argument('--mode',choices=('same','changed','repeated','no-cr'),default='same')
    p.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'runs')
    p.add_argument('--trace-app',type=Path); p.add_argument('--trace-manifest',type=Path)
    p.add_argument('--normal-no-cr-control',action='store_true',help='allow an uninstrumented normal-app no-C/R control only')
    p.add_argument('--normal-build-manifest',type=Path,help='explicit source/artifact provenance for a clean normal build control')
    p.add_argument('--no-cr-ip',choices=('172.18.0.3','172.18.0.6'),default='172.18.0.6',help='owned address for the no-C/R control; same/changed campaign addresses are fixed separately')
    p.add_argument('--keep-peer',action='store_true',help='keep the owned native peer container and publish a reusable session record')
    p.add_argument('--cleanup-pass-state',action='store_true',help='remove owned checkpoint files only after persisted full campaign PASS and assertion/path hash manifest')
    p.add_argument('--cleanup-owned-containers',action='store_true',help='remove session-owned containers only after persisted full campaign PASS')
    p.add_argument('--peer-session-file',type=Path,help='write reusable peer identity/log metadata at this path')
    p.add_argument('--reuse-peer-session',type=Path,help='reuse a live peer from a prior --peer-session-file record')
    p.add_argument('--dry-run',action='store_true',help='validate artifact identity and print exact campaign plan; no Docker calls')
    return p.parse_args(argv)

def main(argv=None):
    args=parse_args(argv)
    paths={'app':args.app,'runtime':args.runtime,'peer':args.peer}
    missing=[f'{k}={v}' for k,v in paths.items() if not v.is_file()]
    if missing: raise SystemExit('missing artifact(s): '+', '.join(missing))
    actual={k:digest(v) for k,v in paths.items()}
    pinned={k:actual[k] for k in ('app','runtime','peer')}
    normal_control=args.mode=='no-cr' and args.normal_no_cr_control
    if args.normal_no_cr_control and args.mode!='no-cr':
        raise SystemExit('--normal-no-cr-control is valid only with --mode no-cr')
    if args.normal_build_manifest:
        if not normal_control: raise SystemExit('--normal-build-manifest is valid only for a normal no-C/R control')
        try: normal_provenance=validate_normal_build_manifest(args.normal_build_manifest,args.app,args.runtime,args.peer)
        except ValueError as exc: raise SystemExit(str(exc))
        if pinned['runtime']!=HASHES['runtime'] or pinned['peer']!=HASHES['peer']:
            raise SystemExit('normal-control runtime/peer hash mismatch against fixed pins')
    else:
        normal_provenance=None
    if normal_control and normal_provenance is None:
        raise SystemExit('normal no-C/R control requires --normal-build-manifest; old T11 app hash is not waived')
    wrong={k:(pinned[k],HASHES[k]) for k in pinned if pinned[k]!=HASHES[k] and not (normal_control and k=='app' and normal_provenance)}
    if wrong: raise SystemExit(f'artifact hash mismatch against T11 default pins: {wrong}')
    trace_status='normal app, new runtime, no-C/R communication control; trace instrumentation not applicable' if normal_control else ''
    if not normal_control and (not args.trace_app or not args.trace_manifest or not args.trace_app.is_file() or not args.trace_manifest.is_file()):
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
        if (telemetry.get('schema')!='traceoverlay_event-v2' or telemetry.get('thread_id_printed') is not True or
            'max_active' not in telemetry.get('metrics_printed',[]) or 'lost' not in telemetry.get('metrics_printed',[]) or
            telemetry.get('output_channel')!='/observer/trace-observer.log' or telemetry.get('stdout_fallback') is not False or
            telemetry.get('batch_schema')!='explicit begin/end; actual counter snapshots and addresses'):
            raise SystemExit('trace derivative does not attest bounded shared observer telemetry')
        observer=tm.get('guest_state_observer',{})
        if (observer.get('schema')!='guest-state-v1' or '/observer/trace-observer.log' not in observer.get('capture','') or
            'shared output mutex' not in observer.get('capture','') or 'write errors counted' not in observer.get('capture','')):
            raise SystemExit('trace derivative does not attest shared guest/trace observer output')
        paths['app']=args.trace_app
        args.app=args.trace_app
        trace_status='private derivative manifest/path/hash validated; telemetry still must satisfy runtime readiness'
    plan={'mode':args.mode,'no_cr_ip':args.no_cr_ip if args.mode=='no-cr' else None,'artifacts':sha_record(paths),'trace_status':trace_status,'checkpoint_count':0 if args.mode=='no-cr' else (2 if args.mode=='repeated' else 1),'peer_policy':'one owned peer container; no restart across campaign phases','disk_preflight':'>=3 GiB before every checkpoint','roundtrip_gate':'>=10 contiguous fully ID/body-correlated peer receive/echo + Wasm publish/callback tuples before and after each checkpoint','telemetry':'observer metrics/loss/overlap parser required; runtime telemetry unobserved; NOT T12 PASS'}
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
