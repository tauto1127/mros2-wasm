#!/usr/bin/env python3
"""Build the actual trace-enabled echoback_string target in a private mirror.

The installed sysroot and all T11 normal artifacts are read-only inputs.  The
current T11 lwIP archive is copied into the mirror and only its two named
members are replaced by the generated observer overlay objects.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_MEMBERS = {"udp.c.obj": "udp.o", "netif_wasm.c.obj": "netif_wasm.o"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def call(cmd, *, cwd, log):
    r = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.write_text("$ " + shlex.join(map(str, cmd)) + f"\n[exit {r.returncode}]\n" + r.stdout)
    return r.returncode

def correct_trace_dump(source: str) -> str:
    """Keep one consuming/printing drain and initialize before recording."""
    init_seam = "  ~ProjectionTraceBatch() {\n"
    discard_seam = "    traceoverlay_event out[16]; uint32_t n=traceoverlay_drain(out,16);\n    traceoverlay_init();\n"
    if source.count(init_seam) != 1 or source.count(discard_seam) != 1:
        raise SystemExit('unexpected legacy ProjectionTraceBatch dump seam')
    source = source.replace(init_seam, init_seam + "    traceoverlay_init();\n", 1)
    source = source.replace(discard_seam, "", 1)
    if source.count('traceoverlay_drain(') != 1:
        raise SystemExit('trace dump must have exactly one consuming loop')
    return source

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mirror', type=Path, required=True)
    ap.add_argument('--source-archive', type=Path, required=True)
    ap.add_argument('--c-overlay-build', type=Path, required=True)
    ap.add_argument('--cpp-overlay', type=Path, required=True)
    ap.add_argument('--tag', default='trace-v2', help='unique suffix for private build/archive/log paths')
    ap.add_argument('--sdk', type=Path, default=Path('/opt/wasi-sdk-21'))
    a = ap.parse_args()
    mirror, source = a.mirror.resolve(), a.source_archive.resolve()
    cpp, cbuild = a.cpp_overlay.resolve(), a.c_overlay_build.resolve()
    if not a.tag or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in a.tag):
        raise SystemExit('tag must be a simple filename component')
    build = mirror/f'build-{a.tag}'; private_dir=mirror/f'private/lwip-{a.tag}'
    if not mirror.is_dir() or not source.is_file(): raise SystemExit('missing mirror or source archive')
    if build.exists() or private_dir.exists(): raise SystemExit('refusing existing build outputs; preserve prior run')
    for p in (cpp/'SPDPAgent.cpp', cpp/'SEDPAgent.cpp', cpp/'traceoverlay.c', cpp/'traceoverlay.h',
              cbuild/'udp.o', cbuild/'netif_wasm.o', cbuild/'traceoverlay.o'):
        if not p.is_file(): raise SystemExit(f'missing approved overlay input: {p}')
    private_dir.mkdir(parents=True)
    private_archive=private_dir/'liblwip-trace.a'
    shutil.copy2(source, private_archive)
    sdk_ar=a.sdk/'bin/llvm-ar'
    sdk_ranlib=a.sdk/'bin/llvm-ranlib'
    work=private_dir/'members'; work.mkdir()
    # Preserve hashes of the original archive members before mutation.
    original_members={name:subprocess.run([str(sdk_ar),'p',str(source),name],check=True,stdout=subprocess.PIPE).stdout for name in ARCHIVE_MEMBERS}
    if any(not b for b in original_members.values()): raise SystemExit('expected lwIP archive member missing/empty')
    replacements={}
    for name,obj in ARCHIVE_MEMBERS.items():
        dest=work/name; shutil.copy2(cbuild/obj,dest); replacements[name]=dest
    for name in ARCHIVE_MEMBERS:
        subprocess.run([str(sdk_ar),'d',str(private_archive),name],check=True)
    subprocess.run([str(sdk_ar),'r',str(private_archive),*[str(replacements[n]) for n in ARCHIVE_MEMBERS]],check=True)
    subprocess.run([str(sdk_ranlib),str(private_archive)],check=True)
    # Install observer once as a target source, and point the mirror's C++ source
    # selection at the approved overlay. These edits exist only in the mirror.
    cm=mirror/'CMakeLists.txt'; text=cm.read_text()
    marker='\tadd_executable(${MAIN_TARGET_NAME} ${SOURCE_FILE} ${ARGN})'
    hook='    if(TRACE_CPP_OVERLAY_DIR AND EXISTS "${TRACE_CPP_OVERLAY_DIR}/traceoverlay.c")'
    if text.count(marker)==1:
        text=text.replace(marker, marker+'\n'+hook+'\n      target_sources(${MAIN_TARGET_NAME} PRIVATE "${TRACE_CPP_OVERLAY_DIR}/traceoverlay.c")\n      target_include_directories(${MAIN_TARGET_NAME} PRIVATE "${TRACE_CPP_OVERLAY_DIR}")\n      target_link_options(${MAIN_TARGET_NAME} PRIVATE "-Wl,-Map=${CMAKE_BINARY_DIR}/${MAIN_TARGET_NAME}.map")\n    endif()',1)
    elif text.count(hook)!=1:
        raise SystemExit('unexpected mirror application target seam')
    cm.write_text(text)
    (mirror/'overlay').mkdir(exist_ok=True)
    for name in ('SPDPAgent.cpp','SEDPAgent.cpp','traceoverlay.c','traceoverlay.h'):
        dst=mirror/'overlay'/name
        if cpp/name != dst.resolve(): shutil.copy2(cpp/name,dst)
    sedp=mirror/'overlay/SEDPAgent.cpp'
    st=sedp.read_text()
    st=st.replace('#include <cstdio>', '#include <cstdio>\\n#include <pthread.h>')
    st=st.replace('const uint64_t tid = 0;', 'const uint64_t tid = (uint64_t)(uintptr_t)pthread_self();')
    old='''for(uint32_t i=0;i<n;++i) std::printf("RTPS_TRACE seq=%u kind=%u result=%u current=%u applied=%u detail=%u aux=%u\\n",
      out[i].sequence,out[i].kind,out[i].result,out[i].current_ip,out[i].applied_ip,out[i].detail,out[i].aux);'''
    new='''traceoverlay_init();
    for (uint32_t batch=0; batch<16; ++batch) {
      traceoverlay_event out[16];
      uint32_t n=traceoverlay_drain(out,16);
      if (n==0) break;
      for(uint32_t i=0;i<n;++i) std::printf("RTPS_TRACE seq=%u kind=%u result=%u current=%u applied=%u detail=%u aux=%u thread=%llu\\n",
        out[i].sequence,out[i].kind,out[i].result,out[i].current_ip,out[i].applied_ip,out[i].detail,out[i].aux,
        (unsigned long long)out[i].thread_id);
    }
    uint32_t attempts=0,winners=0,busy=0,failed=0,outcomes=0,completed=0,active=0,max_active=0;
    traceoverlay_metrics(&attempts,&winners,&busy,&failed,&outcomes,&completed,&active,&max_active);
    std::printf("RTPS_TRACE_METRICS attempts=%u winners=%u busy=%u failed=%u outcomes=%u probe_completions=%u active=%u max_active=%u lost=%u lockfree=%u\\n",
      attempts,winners,busy,failed,outcomes,completed,active,max_active,traceoverlay_lost(),traceoverlay_lockfree());'''
    if st.count(old)!=1: raise SystemExit('unexpected mirror SEDP trace dump seam')
    st = correct_trace_dump(st.replace(old,new,1))
    sedp.write_text(st)
    # Preserve original mirror build/configuration. Configure a distinct build tree.
    old=mirror/'build/CMakeCache.txt'
    cache={}
    if old.exists():
        for line in old.read_text().splitlines():
            if ':' in line and '=' in line:
                k,v=line.split('=',1); cache[k.split(':',1)[0]]=v
    required=('CMAKE_APPNAME','WASI_SDK_PREFIX','CMAKE_TOOLCHAIN_FILE','CMAKE_SYSROOT','WAMR_ROOT','CARTOGRAPHER_ROOT','CARTOGRAPHER_LIBRARY_ROOT','ZLIB_LIBRARY')
    missing=[k for k in required if not cache.get(k)]
    if missing: raise SystemExit('configured mirror lacks cache inputs: '+','.join(missing))
    args=['cmake','-S',str(mirror),'-B',str(build),*[f'-D{k}={cache[k]}' for k in required],
          f'-DTRACE_PRIVATE_LWIP_ARCHIVE={private_archive}',f'-DTRACE_CPP_OVERLAY_DIR={mirror}/overlay']
    logs=mirror/f'{a.tag}-logs'; logs.mkdir()
    manifest={'status':'building','archive_source':str(source),'archive_source_sha256':sha(source),
      'private_archive':str(private_archive),'private_archive_initial_sha256':sha(private_archive),
      'original_archive_member_sha256':{n:hashlib.sha256(data).hexdigest() for n,data in original_members.items()},
      'replacement_object_sha256':{n:sha(p) for n,p in replacements.items()},
      'archive_members':subprocess.run([str(sdk_ar),'t',str(private_archive)],check=True,text=True,stdout=subprocess.PIPE).stdout.splitlines(),
      'cpp_overlay_sha256':{n:sha(mirror/'overlay'/n) for n in ('SPDPAgent.cpp','SEDPAgent.cpp','traceoverlay.c','traceoverlay.h')},
      'trace_telemetry':{'schema':'traceoverlay_event-v2','thread_id_printed':True,
        'metrics_printed':['attempts','winners','busy','failed','outcomes','probe_completions','active','max_active','lost','lockfree'],
        'probe_boundaries':'actual probe_local_ip call entry/exit in C overlay'},
      'c_overlay_manifest_sha256':sha(cbuild/'manifest.json'),'configure_command':args,
      'source_archive_unchanged':sha(source)==sha(source),'sysroot_mutated':False,'normal_artifacts_mutated':False}
    if call(args,cwd=mirror,log=logs/'configure.log'):
        manifest['status']='configure failed; raw log retained'
        (logs/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n'); return 1
    cmd=['cmake','--build',str(build),'--target','MODULE_echoback_string','--verbose']
    manifest['build_command']=cmd
    if call(cmd,cwd=mirror,log=logs/'build.log'):
        manifest['status']='build failed; raw logs and private archive retained'
        (logs/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n'); return 1
    wasm=build/'echoback_string.wasm'
    link_text=(build/'CMakeFiles/MODULE_echoback_string.dir/link.txt').read_text()
    link_map=build/'MODULE_echoback_string.map'
    observer_link_occurrences=link_text.count('traceoverlay.c.obj')
    manifest.update(status='actual MODULE_echoback_string build passed',
      link_log_sha256=sha(logs/'build.log'),configure_log_sha256=sha(logs/'configure.log'),
      wasm_path=str(wasm),wasm_sha256=sha(wasm),private_archive_sha256=sha(private_archive),
      original_archive_unchanged=sha(source)==manifest['archive_source_sha256'],
      observer_link_occurrences=observer_link_occurrences,observer_linked_once=observer_link_occurrences==1,
      link_map_path=str(link_map),link_map_sha256=sha(link_map) if link_map.is_file() else None)
    if not manifest['observer_linked_once'] or not link_map.is_file():
        manifest['status']='build passed but link evidence incomplete; retain outputs'
        (logs/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\\n')
        return 2
    (logs/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
