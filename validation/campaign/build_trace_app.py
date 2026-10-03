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

def instrument_cpp_guest_state(source: str) -> str:
    """Add actual field-address/value observations to the private SEDP mirror."""
    seam = """bool SEDPAgent::projectLocalIp(uint32_t networkOrderIp)
{
  if (networkOrderIp == 0 || m_part == nullptr) return false;
"""
    replacement = seam + '''  // Current-app-only observer: read under SEDP -> brief Participant snapshot,
  // copy scalars/bytes, and print only after both guards have been released.
  {
    uint32_t appliedValue = 0, writerCount = 0, readerCount = 0;
    uintptr_t appliedAddress = 0, guidAddress = 0;
    std::array<uint8_t, 12> guidBytes{};
    bool selected = false;
    const char *role = "absent";
    uintptr_t locatorKindAddress = 0, locatorPortAddress = 0, locatorAddressAddress = 0;
    int32_t locatorKind = -1;
    uint32_t locatorPort = 0;
    std::array<uint8_t, 16> locatorAddress{};
    uintptr_t endpointGuidAddress = 0;
    std::array<uint8_t, 16> endpointGuid{};
    {
      Lock observerLock{m_mutex};
      auto &spdp = m_part->m_spdpAgent;
      appliedValue = spdp.m_lastAppliedIp;
      appliedAddress = reinterpret_cast<uintptr_t>(&spdp.m_lastAppliedIp);
      guidAddress = reinterpret_cast<uintptr_t>(m_part->m_guidPrefix.id.data());
      guidBytes = m_part->m_guidPrefix.id;
      const auto endpoints = m_part->snapshotEndpoints();
      for (uint8_t i = 0; i < endpoints.numWriters; ++i) {
        Writer *writer = endpoints.writers[i];
        if (!writer || !writer->isInitialized()) continue;
        const auto kind = writer->m_attributes.endpointGuid.entityId.entityKind;
        if (kind != EntityKind_t::USER_DEFINED_WRITER_WITH_KEY &&
            kind != EntityKind_t::USER_DEFINED_WRITER_WITHOUT_KEY) continue;
        ++writerCount;
        if (selected) continue;
        selected = true; role = "writer";
        auto &attr = writer->m_attributes;
        locatorKindAddress = reinterpret_cast<uintptr_t>(&attr.unicastLocator.kind);
        locatorPortAddress = reinterpret_cast<uintptr_t>(&attr.unicastLocator.port);
        locatorAddressAddress = reinterpret_cast<uintptr_t>(attr.unicastLocator.address.data());
        locatorKind = static_cast<int32_t>(attr.unicastLocator.kind);
        locatorPort = attr.unicastLocator.port;
        locatorAddress = attr.unicastLocator.address;
        endpointGuidAddress = reinterpret_cast<uintptr_t>(&attr.endpointGuid);
        for (size_t j = 0; j < 12; ++j) endpointGuid[j] = attr.endpointGuid.prefix.id[j];
        for (size_t j = 0; j < 3; ++j) endpointGuid[12+j] = attr.endpointGuid.entityId.entityKey[j];
        endpointGuid[15] = static_cast<uint8_t>(attr.endpointGuid.entityId.entityKind);
      }
      for (uint8_t i = 0; i < endpoints.numReaders; ++i) {
        Reader *reader = endpoints.readers[i];
        if (!reader || !reader->isInitialized()) continue;
        const auto kind = reader->m_attributes.endpointGuid.entityId.entityKind;
        if (kind != EntityKind_t::USER_DEFINED_READER_WITH_KEY &&
            kind != EntityKind_t::USER_DEFINED_READER_WITHOUT_KEY) continue;
        ++readerCount;
        if (selected) continue;
        selected = true; role = "reader";
        auto &attr = reader->m_attributes;
        locatorKindAddress = reinterpret_cast<uintptr_t>(&attr.unicastLocator.kind);
        locatorPortAddress = reinterpret_cast<uintptr_t>(&attr.unicastLocator.port);
        locatorAddressAddress = reinterpret_cast<uintptr_t>(attr.unicastLocator.address.data());
        locatorKind = static_cast<int32_t>(attr.unicastLocator.kind);
        locatorPort = attr.unicastLocator.port;
        locatorAddress = attr.unicastLocator.address;
        endpointGuidAddress = reinterpret_cast<uintptr_t>(&attr.endpointGuid);
        for (size_t j = 0; j < 12; ++j) endpointGuid[j] = attr.endpointGuid.prefix.id[j];
        for (size_t j = 0; j < 3; ++j) endpointGuid[12+j] = attr.endpointGuid.entityId.entityKey[j];
        endpointGuid[15] = static_cast<uint8_t>(attr.endpointGuid.entityId.entityKind);
      }
    }
    char guidHex[25], endpointHex[33], locatorHex[33];
    for (size_t i=0; i<guidBytes.size(); ++i) std::snprintf(guidHex+2*i,3,"%02x",guidBytes[i]);
    for (size_t i=0; i<endpointGuid.size(); ++i) std::snprintf(endpointHex+2*i,3,"%02x",endpointGuid[i]);
    for (size_t i=0; i<locatorAddress.size(); ++i) std::snprintf(locatorHex+2*i,3,"%02x",locatorAddress[i]);
    char locatorJson[512] = "null";
    if (selected) std::snprintf(locatorJson,sizeof(locatorJson),
      "{\\"role\\":\\"%s\\",\\"kind_field_addr\\":\\"0x%08x\\",\\"kind_value\\":%d,\\"port_field_addr\\":\\"0x%08x\\",\\"port_value\\":\\"0x%08x\\",\\"address_field_addr\\":\\"0x%08x\\",\\"address_bytes\\":\\"%s\\",\\"endpoint_guid_addr\\":\\"0x%08x\\",\\"endpoint_guid\\":\\"%s\\"}",
      role,(unsigned)locatorKindAddress,locatorKind,(unsigned)locatorPortAddress,locatorPort,
      (unsigned)locatorAddressAddress,locatorHex,(unsigned)endpointGuidAddress,endpointHex);
    char guestStateRecord[1024];
    const int guestStateLength = std::snprintf(guestStateRecord, sizeof(guestStateRecord),
      "{\\"schema\\":\\"guest-state-v1;actual wasm32 addresses + copied values;raw memory little-endian;IPv4 semantic bytes network-order\\",\\"part\\":\\"cpp\\",\\"current_ip_value\\":\\"0x%08x\\",\\"applied_field_addr\\":\\"0x%08x\\",\\"applied_value\\":\\"0x%08x\\",\\"guid_prefix_addr\\":\\"0x%08x\\",\\"guid_prefix\\":\\"%s\\",\\"user_writer_count\\":%u,\\"user_reader_count\\":%u,\\"selection_absent\\":%s,\\"selected_locator\\":%s}\\n",
      networkOrderIp, (unsigned)appliedAddress, appliedValue, (unsigned)guidAddress, guidHex,
      writerCount, readerCount, selected ? "false" : "true", locatorJson);
    if (guestStateLength > 0 && (size_t)guestStateLength < sizeof(guestStateRecord))
      traceoverlay_write_record(guestStateRecord, (uint32_t)guestStateLength);
  }
'''
    if source.count(seam) != 1:
        raise SystemExit('unexpected live SEDP projectLocalIp observer seam')
    source=source.replace(seam,replacement,1)
    # The JSON record contains the copied selected-locator snapshot directly.
    return source


def correct_trace_dump(source: str) -> str:
    """Initialize before records and keep exactly one bounded consuming drain."""
    init_seam = "  ~ProjectionTraceBatch() {\n"
    if source.count(init_seam) != 1:
        raise SystemExit('unexpected ProjectionTraceBatch destructor seam')
    destructor=source.index(init_seam)+len(init_seam)
    close=source.index('\n  }',destructor)
    body=source[destructor:close]
    if 'traceoverlay_init();' not in body:
        source=source[:destructor]+"    traceoverlay_init();\n"+source[destructor:]
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
    for name in ('SPDPAgent.cpp','SEDPAgent.cpp'):
        dst=mirror/'overlay'/name
        if cpp/name != dst.resolve(): shutil.copy2(cpp/name,dst)
    shutil.copy2(cbuild/'overlay/traceoverlay.c',mirror/'overlay/traceoverlay.c')
    shutil.copy2(ROOT/'validation/campaign/traceoverlay.h',mirror/'overlay/traceoverlay.h')
    sedp=mirror/'overlay/SEDPAgent.cpp'
    st=instrument_cpp_guest_state(sedp.read_text())
    st=st.replace('#include <cstdio>', '#include <cstdio>\n#include <cstdint>\n#include <pthread.h>\n#include <atomic>')
    st=st.replace('const uint64_t tid = 0;', 'const uint64_t tid = (uint64_t)(uintptr_t)pthread_self();')
    old='''traceoverlay_event out[16]; uint32_t n=traceoverlay_drain(out,16);
    for(uint32_t i=0;i<n;++i) std::printf("RTPS_TRACE seq=%u kind=%u result=%u current=%u applied=%u detail=%u aux=%u\\n",
      out[i].sequence,out[i].kind,out[i].result,out[i].current_ip,out[i].applied_ip,out[i].detail,out[i].aux);'''
    helpers='''static bool traceSnapshotEqual(const traceoverlay_counter_snapshot &a, const traceoverlay_counter_snapshot &b) {
  return a.next_sequence==b.next_sequence && a.read_sequence==b.read_sequence && a.attempts==b.attempts &&
    a.winners==b.winners && a.busy==b.busy && a.failed==b.failed && a.outcomes==b.outcomes &&
    a.probe_completions==b.probe_completions && a.active_probes==b.active_probes &&
    a.max_active_probes==b.max_active_probes && a.lost_events==b.lost_events &&
    a.output_failures==b.output_failures && a.lockfree==b.lockfree;
}
static bool traceAppendSnapshot(char *buffer, size_t capacity, size_t *used,
    uint32_t batch, const char *edge, uint32_t stable, const traceoverlay_counter_snapshot &s) {
  int n=std::snprintf(buffer+*used,capacity-*used,
    "RTPS_TRACE_METRICS batch=%u edge=%s stable=%u read=%u next=%u attempts=%u winners=%u busy=%u failed=%u outcomes=%u probe_completions=%u active=%u max_active=%u lost=%u output_failures=%u lockfree=%u addr_read=0x%08x addr_next=0x%08x addr_attempts=0x%08x addr_winners=0x%08x addr_busy=0x%08x addr_failed=0x%08x addr_outcomes=0x%08x addr_probe_completions=0x%08x addr_active=0x%08x addr_max_active=0x%08x addr_lost=0x%08x addr_output_failures=0x%08x addr_lockfree=0x%08x\\n",
    batch,edge,stable,s.read_sequence,s.next_sequence,s.attempts,s.winners,s.busy,s.failed,s.outcomes,
    s.probe_completions,s.active_probes,s.max_active_probes,s.lost_events,s.output_failures,s.lockfree,
    s.read_sequence_address,s.next_sequence_address,s.attempts_address,s.winners_address,s.busy_address,
    s.failed_address,s.outcomes_address,s.probe_completions_address,s.active_probes_address,
    s.max_active_probes_address,s.lost_events_address,s.output_failures_address,s.lockfree_address);
  if(n<=0 || (size_t)n>=capacity-*used) return false; *used+=(size_t)n; return true;
}
static bool traceAppendEvent(char *buffer, size_t capacity, size_t *used, const traceoverlay_event &e) {
  int n=std::snprintf(buffer+*used,capacity-*used,
    "RTPS_TRACE seq=%u kind=%u result=%u current=%u applied=%u detail=%u aux=%u thread=%llu\\n",
    e.sequence,e.kind,e.result,e.current_ip,e.applied_ip,e.detail,e.aux,(unsigned long long)e.thread_id);
  if(n<=0 || (size_t)n>=capacity-*used) return false; *used+=(size_t)n; return true;
}
'''
    if st.count('struct ProjectionTraceBatch {')!=1: raise SystemExit('unexpected ProjectionTraceBatch definition')
    st=st.replace('struct ProjectionTraceBatch {',helpers+'\nstruct ProjectionTraceBatch {',1)
    new='''traceoverlay_init();
    static std::atomic<uint32_t> batchCounter{0};
    uint32_t batch=batchCounter.fetch_add(1,std::memory_order_relaxed)+1;
    char output[8192]; size_t used=0;
    if(traceoverlay_batch_begin()!=0) return;
    traceoverlay_counter_snapshot before{},beforeCheck{},after{},afterCheck{};
    traceoverlay_snapshot(&before); traceoverlay_snapshot(&beforeCheck);
    uint32_t stableBefore=traceSnapshotEqual(before,beforeCheck); before=beforeCheck;
    traceoverlay_event out[16]; uint32_t n=traceoverlay_drain(out,16);
    int beginLength=std::snprintf(output,sizeof(output),"RTPS_TRACE_BATCH_BEGIN batch=%u read=%u next=%u\\n",batch,before.read_sequence,before.next_sequence);
    bool complete=beginLength>0 && (size_t)beginLength<sizeof(output);
    if(complete) used=(size_t)beginLength;
    if(complete) complete=traceAppendSnapshot(output,sizeof(output),&used,batch,"before",stableBefore,before);
    for(uint32_t i=0;complete && i<n;++i) complete=traceAppendEvent(output,sizeof(output),&used,out[i]);
    traceoverlay_snapshot(&after); traceoverlay_snapshot(&afterCheck);
    uint32_t stableAfter=traceSnapshotEqual(after,afterCheck); after=afterCheck;
    if(complete) complete=traceAppendSnapshot(output,sizeof(output),&used,batch,"after",stableAfter,after);
    if(complete) {
      int endLength=std::snprintf(output+used,sizeof(output)-used,
        "RTPS_TRACE_BATCH_END batch=%u events=%u first=%u last=%u read=%u next=%u\\n",
        batch,n,n?out[0].sequence:0,n?out[n-1].sequence:0,after.read_sequence,after.next_sequence);
      if(endLength>0 && (size_t)endLength<sizeof(output)-used) used+=(size_t)endLength; else complete=false;
    }
    if(complete) traceoverlay_batch_end(output,(uint32_t)used);
    else { traceoverlay_note_output_failure(); traceoverlay_batch_end(nullptr,0); }'''
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
        'metrics_printed':['attempts','winners','busy','failed','outcomes','probe_completions','active','max_active','lost','lockfree','output_failures','read','next'],
        'output_channel':'/observer/trace-observer.log','stdout_fallback':False,
        'batch_schema':'explicit begin/end; actual counter snapshots and addresses',
        'counter_image_oracle':'guest-emitted WASM32 counter addresses and endianness; restore baseline read-only from exact checkpoint image',
        'probe_boundaries':'actual probe_local_ip call entry/exit in C overlay'},
      'guest_state_observer':{'schema':'guest-state-v1','source':'current C/C++ source copied into private derived overlay',
        'C_fields':['&netif_default address/pointer value','actual ip_addr.addr address/network-order value','actual netmask.addr address/value'],
        'CXX_fields':['actual m_lastAppliedIp address/value','immutable local Participant GUID prefix address/bytes',
          'first initialized USER writer else USER reader selected under SEDP lock','actual selected locator kind/port/address field addresses/values','full selected endpoint GUID/key'],
        'capture':'/observer/trace-observer.log shared output mutex; RTPS_TRACE events, RTPS_TRACE_METRICS and guest-state JSON emitted in bounded append writes after production guards release; descriptor identity revalidated and reopened after restore; write errors counted',
        'checkpoint_freshness':'runner requires new complete observations after pre-roundtrip collector watermark; collector ordering only, not guest time',
        'saved_image_oracle':'WASM32 address bounds and exact checkpoint bytes; raw u32 little-endian, IPv4 semantic bytes network order'},
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
