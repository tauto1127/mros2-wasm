#include "traceoverlay.h"

#include <stdatomic.h>
#include <stddef.h>
#include <errno.h>

_Static_assert(ATOMIC_INT_LOCK_FREE == 2,
               "traceoverlay requires always-lock-free 32-bit atomics");

#define TRACE_CAPACITY 256u
#define TRACE_MASK (TRACE_CAPACITY - 1u)

typedef struct trace_slot {
  _Atomic uint32_t published;
  traceoverlay_event event;
} trace_slot;

static trace_slot ring[TRACE_CAPACITY];
static _Atomic uint32_t next_sequence;
static _Atomic uint32_t lost_events;
static _Atomic uint32_t read_sequence;
static _Atomic uint32_t atomics_ok = ATOMIC_VAR_INIT(1u);
static _Atomic uint32_t attempts, winners, busy_count, failed_count, outcomes;
static _Atomic uint32_t probe_completions, active_probes, max_active_probes;

int traceoverlay_init(void)
{
  int saved_errno = errno;
  int ok = atomic_is_lock_free(&next_sequence) &&
           atomic_is_lock_free(&lost_events) &&
           atomic_is_lock_free(&ring[0].published) &&
           atomic_is_lock_free(&active_probes) &&
           atomic_is_lock_free(&max_active_probes);
  atomic_store_explicit(&atomics_ok, ok ? 1u : 0u, memory_order_relaxed);
  errno = saved_errno;
  return ok;
}

void traceoverlay_record(uint16_t kind, uint16_t result, uint32_t current_ip,
                         uint32_t applied_ip, uint32_t detail, uint32_t aux,
                         uint64_t thread_id)
{
  int saved_errno = errno;
  if (kind == TRACE_TRYLOCK_ATTEMPT) atomic_fetch_add_explicit(&attempts, 1u, memory_order_relaxed);
  if (kind == TRACE_TRYLOCK_OUTCOME) {
    atomic_fetch_add_explicit(&outcomes, 1u, memory_order_relaxed);
    if (result == TRACE_RESULT_BUSY) atomic_fetch_add_explicit(&busy_count, 1u, memory_order_relaxed);
    else if (result == TRACE_RESULT_FAILED) atomic_fetch_add_explicit(&failed_count, 1u, memory_order_relaxed);
    else atomic_fetch_add_explicit(&winners, 1u, memory_order_relaxed);
  }
  if (kind == TRACE_PROBE_ENTER) {
    uint32_t active = atomic_fetch_add_explicit(&active_probes, 1u, memory_order_relaxed) + 1u;
    uint32_t maximum = atomic_load_explicit(&max_active_probes, memory_order_relaxed);
    if (active > maximum && !atomic_compare_exchange_strong_explicit(&max_active_probes,
        &maximum, active, memory_order_relaxed, memory_order_relaxed))
      atomic_fetch_add_explicit(&lost_events, 1u, memory_order_relaxed);
  } else if (kind == TRACE_PROBE_EXIT) {
    atomic_fetch_sub_explicit(&active_probes, 1u, memory_order_relaxed);
    atomic_fetch_add_explicit(&probe_completions, 1u, memory_order_relaxed);
  }
  if (atomic_load_explicit(&atomics_ok, memory_order_relaxed) == 0u) {
    errno = saved_errno;
    return;
  }
  uint32_t sequence = atomic_load_explicit(&next_sequence, memory_order_relaxed);
  uint32_t consumed = atomic_load_explicit(&read_sequence, memory_order_acquire);
  if ((uint32_t)(sequence - consumed) >= TRACE_CAPACITY) {
    atomic_fetch_add_explicit(&lost_events, 1u, memory_order_relaxed);
    errno = saved_errno;
    return;
  }
  uint32_t next = sequence + 1u;
  /* One CAS attempt only: contention is recorded as loss, never retried while
   * a caller may be under a production lock. Failed CAS reserves no slot. */
  if (!atomic_compare_exchange_strong_explicit(&next_sequence, &sequence, next,
                                                memory_order_relaxed,
                                                memory_order_relaxed)) {
    atomic_fetch_add_explicit(&lost_events, 1u, memory_order_relaxed);
    errno = saved_errno;
    return;
  }
  trace_slot *slot = &ring[sequence & TRACE_MASK];
  slot->event.sequence = sequence;
  slot->event.kind = kind;
  slot->event.result = result;
  slot->event.current_ip = current_ip;
  slot->event.applied_ip = applied_ip;
  slot->event.detail = detail;
  slot->event.aux = aux;
  slot->event.thread_id = thread_id;
  /* Per-slot release publication means consumers never observe partial POD. */
  atomic_store_explicit(&slot->published, sequence + 1u, memory_order_release);
  errno = saved_errno;
}

uint32_t traceoverlay_drain(traceoverlay_event *out, uint32_t capacity)
{
  int saved_errno = errno;
  if (out == NULL || capacity == 0u) {
    errno = saved_errno;
    return 0u;
  }
  uint32_t read = atomic_load_explicit(&read_sequence, memory_order_relaxed);
  uint32_t count = 0;
  while (count < capacity) {
    uint32_t end = atomic_load_explicit(&next_sequence, memory_order_acquire);
    if (read == end) break;
    trace_slot *slot = &ring[read & TRACE_MASK];
    if (atomic_load_explicit(&slot->published, memory_order_acquire) != read + 1u)
      break;
    out[count++] = slot->event;
    ++read;
    atomic_store_explicit(&read_sequence, read, memory_order_release);
  }
  errno = saved_errno;
  return count;
}

uint32_t traceoverlay_lost(void)
{
  int saved_errno = errno;
  uint32_t value = atomic_load_explicit(&lost_events, memory_order_relaxed);
  errno = saved_errno;
  return value;
}

uint32_t traceoverlay_lockfree(void)
{
  int saved_errno = errno;
  uint32_t value = atomic_load_explicit(&atomics_ok, memory_order_relaxed);
  errno = saved_errno;
  return value;
}

void traceoverlay_metrics(uint32_t *attempts_out, uint32_t *winners_out,
                          uint32_t *busy_out, uint32_t *failed_out,
                          uint32_t *outcomes_out, uint32_t *completions_out,
                          uint32_t *active_out, uint32_t *max_active_out)
{
  int saved_errno = errno;
  if (attempts_out) *attempts_out = atomic_load_explicit(&attempts, memory_order_relaxed);
  if (winners_out) *winners_out = atomic_load_explicit(&winners, memory_order_relaxed);
  if (busy_out) *busy_out = atomic_load_explicit(&busy_count, memory_order_relaxed);
  if (failed_out) *failed_out = atomic_load_explicit(&failed_count, memory_order_relaxed);
  if (outcomes_out) *outcomes_out = atomic_load_explicit(&outcomes, memory_order_relaxed);
  if (completions_out) *completions_out = atomic_load_explicit(&probe_completions, memory_order_relaxed);
  if (active_out) *active_out = atomic_load_explicit(&active_probes, memory_order_relaxed);
  if (max_active_out) *max_active_out = atomic_load_explicit(&max_active_probes, memory_order_relaxed);
  errno = saved_errno;
}
