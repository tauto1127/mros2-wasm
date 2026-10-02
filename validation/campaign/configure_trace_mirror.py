#!/usr/bin/env python3
"""Create/configure a minimal private T12 source mirror; never builds/installs."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NORMAL_BUILD = Path('/tmp/locks-native-T11-20261002/build-echoback_string')
APP = 'echoback_string'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()

def copy_tree(src: Path, dst: Path, manifest: dict, relroot: str):
    for p in sorted(src.rglob('*')):
        rel = p.relative_to(src)
        if any(part in {'.git', 'cmake_build', 'build', '__pycache__'} for part in rel.parts):
            continue
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        elif p.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            manifest[f'{relroot}/{rel.as_posix()}'] = {'source': str(p.resolve()), 'sha256': sha(p), 'mirror': str(out)}

def run():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--sdk', type=Path, default=Path('/opt/wasi-sdk-21'))
    ap.add_argument('--sysroot', type=Path, default=Path('/home/osslab/wasi-sysroot'))
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists(): raise SystemExit(f'refusing existing output: {out}')
    cmdfile = NORMAL_BUILD / 'commands.txt'
    if not cmdfile.is_file(): raise SystemExit(f'missing T11 command provenance: {cmdfile}')
    command = cmdfile.read_text().strip()
    expected = f'-DCMAKE_APPNAME={APP}'
    if expected not in command: raise SystemExit('T11 command does not select echoback_string')
    free_before = shutil.disk_usage(out.parent).free
    if free_before < 3 * 1024**3: raise SystemExit(f'free space {free_before} below 3GiB; no mirror created')

    manifest = {'task': 'T12a2b-private-mirror-configure-only', 'canonical_root': str(ROOT),
                't11_command_file': str(cmdfile), 't11_command_sha256': sha(cmdfile),
                't11_command': command, 'source_mapping': {}, 'read_only_inputs': {},
                'overlay_configuration': {'cache_variable': 'TRACE_CPP_OVERLAY_DIR',
                  'expected_files': ['SPDPAgent.cpp', 'SEDPAgent.cpp'],
                  'effect': 'mirror mros2 CMake selects overlay source only when file exists'},
                'private_lwip_archive': str(out/'private/lwip/liblwip-trace.a'),
                'normal_artifacts_mutated': False}
    # Copy only app-facing CMake/config/include and the app itself.
    for rel in ('CMakeLists.txt', 'include', 'workspace/echoback_string', 'workspace/custom_msgs', 'mros2'):
        src, dst = ROOT/rel, out/rel
        if src.is_dir(): copy_tree(src, dst, manifest['source_mapping'], rel)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
            manifest['source_mapping'][rel] = {'source': str(src.resolve()), 'sha256': sha(src), 'mirror': str(dst)}

    # Mirror-only mros2 source selection seam. No canonical source changes.
    mc = out/'mros2/CMakeLists.txt'
    text = mc.read_text()
    for source in ('SPDPAgent.cpp', 'SEDPAgent.cpp'):
        old = '${PROJECT_SOURCE_DIR}/embeddedRTPS/src/discovery/' + source
        new = f'${{TRACE_CPP_OVERLAY_DIR}}/{source}'
        text = text.replace(old, f'${{_trace_{source.replace(".", "_")}}}')
    marker = 'target_sources(mros2\n'
    prelude = '''set(TRACE_CPP_OVERLAY_DIR "" CACHE PATH "Optional private SPDP/SEDP source overlay")\nforeach(_trace_name SPDPAgent.cpp SEDPAgent.cpp)\n  set(_trace_source "${PROJECT_SOURCE_DIR}/embeddedRTPS/src/discovery/${_trace_name}")\n  if(TRACE_CPP_OVERLAY_DIR AND EXISTS "${TRACE_CPP_OVERLAY_DIR}/${_trace_name}")\n    set(_trace_source "${TRACE_CPP_OVERLAY_DIR}/${_trace_name}")\n  endif()\n  string(REPLACE "." "_" _trace_var "${_trace_name}")\n  set("_trace_${_trace_var}" "${_trace_source}")\nendforeach()\n'''
    if marker not in text: raise SystemExit('unexpected mirror mros2 CMake seam')
    mc.write_text(text.replace(marker, prelude+marker, 1))

    # Use the canonical installed CMSIS package read-only, and the per-run private
    # archive location for lwIP. The archive is an empty placeholder until a later
    # explicitly scoped archive-build step; this task only configures the path.
    private_archive = out/'private/lwip/liblwip-trace.a'
    private_archive.parent.mkdir(parents=True)
    private_archive.write_bytes(b'!<arch>\n')
    root_cmake = out/'CMakeLists.txt'
    cm = root_cmake.read_text()
    cm = cm.replace('add_subdirectory(cmsis-wasm)', '')
    cm = cm.replace('add_subdirectory(lwip-wasm)', '')
    cm = cm.replace('set(cmsis_DIR "${PROJECT_SOURCE_DIR}/cmsis-wasm/public")',
                    f'set(cmsis_DIR "{ROOT}/cmsis-wasm/public")')
    cm = cm.replace('set(lwip_DIR "${PROJECT_SOURCE_DIR}/lwip-wasm/public")',
                    f'set(lwip_DIR "{ROOT}/lwip-wasm/public")')
    cm = cm.replace('find_package(lwip REQUIRED)',
                    'find_package(lwip REQUIRED)\nset_target_properties(lwip PROPERTIES IMPORTED_LOCATION_NOCONFIG "${TRACE_PRIVATE_LWIP_ARCHIVE}")')
    root_cmake.write_text(cm)
    manifest['read_only_inputs'] = {
      'cmsis_package': str(ROOT/'cmsis-wasm/public'),
      'lwip_headers_package': str(ROOT/'lwip-wasm/public'),
      'wasi_sdk': str(a.sdk.resolve()), 'wasi_sysroot': str(a.sysroot.resolve()),
      'wamr': str(ROOT/'third_party/wamr'), 'cartographer': str(ROOT/'third_party/cartographer'),
      'cartographer_libraries': str(ROOT/'third_party/cartographer-library'),
      'zlib': str(ROOT/'cmake_build/zlib-wasi/libz.a')}
    args = ['cmake', '-S', str(out), '-B', str(out/'build'),
       f'-DCMAKE_APPNAME={APP}', f'-DWASI_SDK_PREFIX={a.sdk}',
       f'-DCMAKE_TOOLCHAIN_FILE={a.sdk}/share/cmake/wasi-sdk-pthread.cmake',
       f'-DCMAKE_SYSROOT={a.sysroot}', f'-DWAMR_ROOT={ROOT}/third_party/wamr',
       f'-DCARTOGRAPHER_ROOT={ROOT}/third_party/cartographer',
       f'-DCARTOGRAPHER_LIBRARY_ROOT={ROOT}/third_party/cartographer-library',
       f'-DZLIB_LIBRARY={ROOT}/cmake_build/zlib-wasi/libz.a',
       f'-DTRACE_PRIVATE_LWIP_ARCHIVE={private_archive}', '-DTRACE_CPP_OVERLAY_DIR=']
    log = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out/'configure.log').write_text(log.stdout)
    manifest['configure_command'] = args
    manifest['configure_exit'] = log.returncode
    manifest['configure_log_sha256'] = sha(out/'configure.log')
    manifest['mirror_bytes'] = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    manifest['free_bytes_before'] = free_before
    manifest['free_bytes_after'] = shutil.disk_usage(out.parent).free
    manifest['status'] = 'configured-only' if log.returncode == 0 else 'configure-failed; mirror and logs retained'
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2))
    return log.returncode

if __name__ == '__main__':
    raise SystemExit(run())
