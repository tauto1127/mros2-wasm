# Scoped cleanup plan

Only individual compiler object and compiler dependency files (`.o`, `.obj`, `.d`) beneath the owned `bootstrap/build/{cmsis,lwip}` generated CMake trees are candidates. Their exact pathname, byte count, and SHA-256 were recorded in `cleanup-execution.json` before removal. Static libraries, WASM executables, build caches, logs, source, maps, validation run artifacts, submodules, and failed payloads are retained. No unrelated data will be deleted to target 3 GiB free.
