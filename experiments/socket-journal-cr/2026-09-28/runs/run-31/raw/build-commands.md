# run-31 build commands

All build commands ran against `/tmp/mros2-wasm-sedp-race-20260928-run31/source` and the independent output directory `/tmp/mros2-wasm-sedp-race-20260928-run31/build`.

```sh
rtk bash Third_Party/download.bash
```

Run once in the temporary `cmsis-wasm` source directory and once in the temporary `lwip-wasm` source directory to fetch the dependency files pinned by each project's script.

```sh
rtk cmake -S /tmp/mros2-wasm-sedp-race-20260928-run31/source -B /tmp/mros2-wasm-sedp-race-20260928-run31/build -DCMAKE_APPNAME=echoback_string -DCMAKE_TOOLCHAIN_FILE=/opt/wasi-sdk-21/share/cmake/wasi-sdk-pthread.cmake -DWASI_SDK_PREFIX=/opt/wasi-sdk-21 -DCMAKE_SYSROOT=/home/osslab/wasi-sysroot -DCMAKE_CXX_FLAGS=-I/tmp/mros2-wasm-sedp-race-20260928-run31/build/experiment-includes -DZLIB_LIBRARY=/home/osslab/mros2-wasm-service-communication-socket-journal/cmake_build/zlib-wasi/libz.a
rtk cmake --build /tmp/mros2-wasm-sedp-race-20260928-run31/build --target MODULE_echoback_string --parallel 4
rtk cp /tmp/mros2-wasm-sedp-race-20260928-run31/build/echoback_string.wasm /tmp/mros2-wasm-sedp-race-20260928-run31/app/echoback_string.wasm
```

The first CMake argument set was retried after restoring ignored public package directories in the source copy and downloading the source files required by CMake. The build then exposed the `LWIP_PROVIDE_ERRNO` issue; the temporary `cc.h` was adjusted using the same `sed` command present in the repository's `build.bash`. The successful build used the command above. The referenced root `ZLIB_LIBRARY` path was absent and unused by the `echoback_string` target.
