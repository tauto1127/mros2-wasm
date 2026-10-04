#include <stddef.h>
#include <stdint.h>

#include "wasm_export.h"

static uint32_t host_probe = 0;

static uint32_t
cr_host_probe_get_wrapper(wasm_exec_env_t exec_env)
{
    (void)exec_env;
    return host_probe;
}

static void
cr_host_probe_set_wrapper(wasm_exec_env_t exec_env, uint32_t value)
{
    (void)exec_env;
    host_probe = value;
}

#define REG_NATIVE_FUNC(func_name, signature) \
    { #func_name, func_name##_wrapper, signature, NULL }

static NativeSymbol native_symbols[] = {
    REG_NATIVE_FUNC(cr_host_probe_get, "()i"),
    REG_NATIVE_FUNC(cr_host_probe_set, "(i)")
};

uint32_t
get_native_lib(char **p_module_name, NativeSymbol **p_native_symbols)
{
    *p_module_name = "env";
    *p_native_symbols = native_symbols;
    return sizeof(native_symbols) / sizeof(NativeSymbol);
}
