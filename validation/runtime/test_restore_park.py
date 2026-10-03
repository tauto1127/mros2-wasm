#!/usr/bin/env python3
"""Compile exact production park/continue functions with real POSIX locks.
Deterministically delay a restored waiter until after the first resume attempt.
This isolates the resume-before-park race; it is not an application C/R test.
"""
import pathlib,re,subprocess,tempfile,sys
root=pathlib.Path(__file__).resolve().parents[2]
src=(root/'third_party/wamr/core/iwasm/libraries/thread-mgr/thread_manager.c').read_text()
def function(name):
    m=re.search(r'(?:inline static bool|inline void|bool|void)\n'+name+r'\([^)]*\)\n\{',src)
    if not m: raise RuntimeError('production function absent: '+name)
    pos=m.end(); depth=1
    while depth:
        depth += (src[pos]=='{')-(src[pos]=='}'); pos+=1
    return src[m.start():pos]
fixed='--legacy' not in sys.argv and 'wasm_cluster_thread_continue_if_stopped(' in src
if fixed:
    interp=(root/'third_party/wamr/core/iwasm/interpreter/wasm_interp_classic.c').read_text()
    assert 'while (!wasm_cluster_thread_continue_if_stopped(target_env))' in interp
prefix=r'''
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <unistd.h>
#include <assert.h>
#define STATUS_RUNNING 0
#define STATUS_STOP 1
#define STATUS_STEP 3
typedef struct { unsigned short running_status; int signal_flag; } WASMCurrentEnvStatus;
typedef struct { pthread_mutex_t wait_lock; pthread_cond_t wait_cond; WASMCurrentEnvStatus *current_status; } WASMExecEnv;
static atomic_int release_child, parked, finished;
static void os_mutex_lock(pthread_mutex_t *m) { assert(!pthread_mutex_lock(m)); }
static void os_mutex_unlock(pthread_mutex_t *m) { assert(!pthread_mutex_unlock(m)); }
static void os_cond_signal(pthread_cond_t *c) { assert(!pthread_cond_signal(c)); }
static void os_cond_wait(pthread_cond_t *c,pthread_mutex_t *m) { atomic_store(&parked,1); assert(!pthread_cond_wait(c,m)); }
static void notify_debug_instance(WASMExecEnv *e) { (void)e; }
'''
code=prefix+'\n'.join(function(n) for n in ['wasm_cluster_thread_is_running','wasm_cluster_clear_thread_signal','wasm_cluster_thread_waiting_run','wasm_cluster_thread_continue'])
if fixed:code+='\n#define HAS_SAFE_CONTINUE\n'+function('wasm_cluster_thread_continue_if_stopped')
code+=r'''
static void *child(void *p) {
 WASMExecEnv *e=p;
 while(!atomic_load(&release_child)) usleep(100);
 os_mutex_lock(&e->wait_lock);
 wasm_cluster_thread_waiting_run(e);
 os_mutex_unlock(&e->wait_lock);
 atomic_store(&finished,1); return NULL;
}
int main(void) {
 for(int run=0;run<50;run++) {
  WASMCurrentEnvStatus st={STATUS_RUNNING,17};
  WASMExecEnv e={PTHREAD_MUTEX_INITIALIZER,PTHREAD_COND_INITIALIZER,&st};
  atomic_store(&release_child,0); atomic_store(&parked,0); atomic_store(&finished,0);
  pthread_t t; assert(!pthread_create(&t,NULL,child,&e));
#ifdef HAS_SAFE_CONTINUE
  assert(!wasm_cluster_thread_continue_if_stopped(&e));
  assert(st.running_status==STATUS_RUNNING && st.signal_flag==17);
#else
  wasm_cluster_thread_continue(&e);
#endif
  atomic_store(&release_child,1);
  for(int i=0;i<10000 && !atomic_load(&parked);i++) usleep(100);
  assert(atomic_load(&parked));
#ifdef HAS_SAFE_CONTINUE
  assert(wasm_cluster_thread_continue_if_stopped(&e));
  assert(st.running_status==STATUS_RUNNING && st.signal_flag==0);
  assert(!wasm_cluster_thread_continue_if_stopped(&e));
#endif
  for(int i=0;i<1000 && !atomic_load(&finished);i++) usleep(100);
  int ok=atomic_load(&finished);
  if(!ok) wasm_cluster_thread_continue(&e); /* rescue only for test teardown */
  assert(!pthread_join(t,NULL));
  assert(!pthread_mutex_destroy(&e.wait_lock)); assert(!pthread_cond_destroy(&e.wait_cond));
  if(!ok) { puts("RED: early resume lost; restored child stays STOP"); return 1; }
 }
 puts("GREEN: 50 delayed restore parks resumed without lost wakeups");
}
'''
with tempfile.TemporaryDirectory(prefix='wamr-park-regression-') as d:
 p=pathlib.Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-D_DEFAULT_SOURCE','-O2','-pthread',str(p/'test.c'),'-o',str(p/'test')],check=True)
 result=subprocess.run([str(p/'test')],timeout=15)
 raise SystemExit(result.returncode)
