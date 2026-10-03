#include "traceoverlay.h"

#include <stdatomic.h>
#include <stddef.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

_Static_assert(ATOMIC_INT_LOCK_FREE == 2,
               "traceoverlay requires always-lock-free 32-bit atomics");

#define TRACE_CAPACITY 256u
#define TRACE_MASK (TRACE_CAPACITY - 1u)
#define TRACE_RESERVATION_MAX_ATTEMPTS 8u

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
static _Atomic uint32_t observer_output_failures;
static pthread_mutex_t observer_output_mutex = PTHREAD_MUTEX_INITIALIZER;
static int observer_fd = -1;
static const char observer_path[] = "/observer/trace-observer.log";

#ifdef TRACEOVERLAY_TEST_RESERVATION_HOOK
extern void traceoverlay_test_before_reservation_cas(void);
#endif

static int observer_ensure_fd_locked(int *opened)
{
  struct stat expected, actual;
  int flags = observer_fd >= 0 ? fcntl(observer_fd, F_GETFL) : -1;
  int valid_fd = observer_fd >= 0 && flags >= 0 &&
      stat(observer_path, &expected) == 0 && fstat(observer_fd, &actual) == 0 &&
      expected.st_dev == actual.st_dev && expected.st_ino == actual.st_ino &&
      (flags & O_ACCMODE) == O_WRONLY && (flags & O_APPEND) != 0;
  *opened = !valid_fd;
  if (!valid_fd) observer_fd = open(observer_path, O_WRONLY | O_CREAT | O_APPEND, 0600);
  return observer_fd >= 0 ? 0 : -1;
}

static int observer_write_locked(const char *record, uint32_t length)
{
  if (observer_fd < 0 || record == NULL || length == 0u) return -1;
  ssize_t written = write(observer_fd, record, length);
  return written == (ssize_t)length ? 0 : -1;
}

void traceoverlay_note_output_failure(void)
{
  atomic_fetch_add_explicit(&observer_output_failures, 1u, memory_order_relaxed);
}

int traceoverlay_write_record(const char *record, uint32_t length)
{
  int saved_errno = errno;
  if (record == NULL || length == 0u || pthread_mutex_lock(&observer_output_mutex) != 0) {
    traceoverlay_note_output_failure(); errno = saved_errno; return -1;
  }
  int opened = 0;
  int result = observer_ensure_fd_locked(&opened);
  if (result == 0) result = observer_write_locked(record, length);
  pthread_mutex_unlock(&observer_output_mutex);
  if (result != 0) traceoverlay_note_output_failure();
  errno = saved_errno;
  return result;
}

int traceoverlay_begin_process_window(void)
{
  int saved_errno = errno;
  if (pthread_mutex_lock(&observer_output_mutex) != 0) {
    traceoverlay_note_output_failure(); errno = saved_errno; return -1;
  }
  int opened = 0;
  int result = observer_ensure_fd_locked(&opened);
  if (result == 0 && opened) {
    traceoverlay_counter_snapshot first, second;
    traceoverlay_snapshot(&first); traceoverlay_snapshot(&second);
    int stable = first.next_sequence == second.next_sequence && first.read_sequence == second.read_sequence &&
      first.attempts == second.attempts && first.winners == second.winners && first.busy == second.busy &&
      first.failed == second.failed && first.outcomes == second.outcomes &&
      first.probe_completions == second.probe_completions && first.active_probes == second.active_probes &&
      first.max_active_probes == second.max_active_probes && first.lost_events == second.lost_events &&
      first.output_failures == second.output_failures && first.lockfree == second.lockfree;
    char line[1200];
    int n = snprintf(line, sizeof(line),
      "RTPS_TRACE_WINDOW_START stable=%u next=%u read=%u attempts=%u winners=%u busy=%u failed=%u outcomes=%u probe_completions=%u active=%u max_active=%u lost=%u output_failures=%u lockfree=%u addr_next=0x%08x addr_read=0x%08x addr_attempts=0x%08x addr_winners=0x%08x addr_busy=0x%08x addr_failed=0x%08x addr_outcomes=0x%08x addr_probe_completions=0x%08x addr_active=0x%08x addr_max_active=0x%08x addr_lost=0x%08x addr_output_failures=0x%08x addr_lockfree=0x%08x\\n",
      stable, second.next_sequence, second.read_sequence, second.attempts, second.winners, second.busy,
      second.failed, second.outcomes, second.probe_completions, second.active_probes,
      second.max_active_probes, second.lost_events, second.output_failures, second.lockfree,
      second.next_sequence_address, second.read_sequence_address, second.attempts_address,
      second.winners_address, second.busy_address, second.failed_address, second.outcomes_address,
      second.probe_completions_address, second.active_probes_address, second.max_active_probes_address,
      second.lost_events_address, second.output_failures_address, second.lockfree_address);
    if (n <= 0 || (size_t)n >= sizeof(line) || observer_write_locked(line, (uint32_t)n) != 0)
      result = -1;
  }
  pthread_mutex_unlock(&observer_output_mutex);
  if (result != 0) traceoverlay_note_output_failure();
  errno = saved_errno;
  return result;
}

int traceoverlay_batch_begin(void)
{
  int saved_errno = errno;
  if (pthread_mutex_lock(&observer_output_mutex) != 0) {
    traceoverlay_note_output_failure(); errno = saved_errno; return -1;
  }
  int opened = 0;
  if (observer_ensure_fd_locked(&opened) != 0) {
    pthread_mutex_unlock(&observer_output_mutex);
    traceoverlay_note_output_failure(); errno = saved_errno; return -1;
  }
  errno = saved_errno;
  return 0;
}

int traceoverlay_batch_end(const char *record, uint32_t length)
{
  int saved_errno = errno;
  int result = observer_write_locked(record, length);
  pthread_mutex_unlock(&observer_output_mutex);
  if (result != 0) traceoverlay_note_output_failure();
  errno = saved_errno;
  return result;
}

uint32_t traceoverlay_output_failures(void)
{
  int saved_errno = errno;
  uint32_t value = atomic_load_explicit(&observer_output_failures, memory_order_relaxed);
  errno = saved_errno;
  return value;
}

void traceoverlay_snapshot(traceoverlay_counter_snapshot *out)
{
  int saved_errno = errno;
  if (out != NULL) {
    out->next_sequence = atomic_load_explicit(&next_sequence, memory_order_relaxed);
    out->read_sequence = atomic_load_explicit(&read_sequence, memory_order_relaxed);
    out->attempts = atomic_load_explicit(&attempts, memory_order_relaxed);
    out->winners = atomic_load_explicit(&winners, memory_order_relaxed);
    out->busy = atomic_load_explicit(&busy_count, memory_order_relaxed);
    out->failed = atomic_load_explicit(&failed_count, memory_order_relaxed);
    out->outcomes = atomic_load_explicit(&outcomes, memory_order_relaxed);
    out->probe_completions = atomic_load_explicit(&probe_completions, memory_order_relaxed);
    out->active_probes = atomic_load_explicit(&active_probes, memory_order_relaxed);
    out->max_active_probes = atomic_load_explicit(&max_active_probes, memory_order_relaxed);
    out->lost_events = atomic_load_explicit(&lost_events, memory_order_relaxed);
    out->output_failures = atomic_load_explicit(&observer_output_failures, memory_order_relaxed);
    out->lockfree = atomic_load_explicit(&atomics_ok, memory_order_relaxed);
    out->next_sequence_address = (uint32_t)(uintptr_t)&next_sequence;
    out->read_sequence_address = (uint32_t)(uintptr_t)&read_sequence;
    out->attempts_address = (uint32_t)(uintptr_t)&attempts;
    out->winners_address = (uint32_t)(uintptr_t)&winners;
    out->busy_address = (uint32_t)(uintptr_t)&busy_count;
    out->failed_address = (uint32_t)(uintptr_t)&failed_count;
    out->outcomes_address = (uint32_t)(uintptr_t)&outcomes;
    out->probe_completions_address = (uint32_t)(uintptr_t)&probe_completions;
    out->active_probes_address = (uint32_t)(uintptr_t)&active_probes;
    out->max_active_probes_address = (uint32_t)(uintptr_t)&max_active_probes;
    out->lost_events_address = (uint32_t)(uintptr_t)&lost_events;
    out->output_failures_address = (uint32_t)(uintptr_t)&observer_output_failures;
    out->lockfree_address = (uint32_t)(uintptr_t)&atomics_ok;
  }
  errno = saved_errno;
}

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
  /* Retry only a small fixed number of times: this stays bounded inside
   * instrumented sections while allowing concurrent producers to reserve
   * distinct sequences. Exhaustion remains explicit observer loss. */
  uint32_t sequence = 0u;
  uint32_t reserved = 0u;
  for (uint32_t retry = 0u; retry < TRACE_RESERVATION_MAX_ATTEMPTS; ++retry) {
    sequence = atomic_load_explicit(&next_sequence, memory_order_relaxed);
    uint32_t consumed = atomic_load_explicit(&read_sequence, memory_order_acquire);
    if ((uint32_t)(sequence - consumed) >= TRACE_CAPACITY) {
      atomic_fetch_add_explicit(&lost_events, 1u, memory_order_relaxed);
      errno = saved_errno;
      return;
    }
    uint32_t next = sequence + 1u;
#ifdef TRACEOVERLAY_TEST_RESERVATION_HOOK
    traceoverlay_test_before_reservation_cas();
#endif
    if (atomic_compare_exchange_strong_explicit(&next_sequence, &sequence, next,
                                                 memory_order_relaxed,
                                                 memory_order_relaxed)) {
      reserved = 1u;
      break;
    }
  }
  if (reserved == 0u) {
    /* Bounded reservation contention remains explicit observer loss. */
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
