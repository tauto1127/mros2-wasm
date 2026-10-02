#ifndef MROS2_TRACEOVERLAY_H
#define MROS2_TRACEOVERLAY_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum traceoverlay_kind {
  TRACE_EINTR = 1,
  TRACE_TRYLOCK_ATTEMPT = 2,
  TRACE_TRYLOCK_OUTCOME = 3,
  TRACE_PROBE_ENTER = 4,
  TRACE_PROBE_EXIT = 5,
  TRACE_IP_CURRENT = 6,
  TRACE_IP_APPLIED = 7,
  TRACE_PREP_BEGIN = 8,
  TRACE_PREP_FAIL = 9,
  TRACE_PROJECTION_COMMIT = 10,
  TRACE_APPLIED_LAST = 11,
  TRACE_IP_EQUAL = 12,
  TRACE_IP_RETRY = 13
};

enum traceoverlay_result {
  TRACE_RESULT_UNAVAILABLE = 0,
  TRACE_RESULT_BUSY = 1,
  TRACE_RESULT_FAILED = 2,
  TRACE_RESULT_UNCHANGED = 3,
  TRACE_RESULT_CHANGED = 4
};

/* Fixed-width guest event: timestamps are collector-side only. For EINTR,
 * detail=original errno and aux=fd; for trylock events detail=pthread result,
 * aux=snapshot-valid. IP fields are zero when no winner-owned snapshot exists. */
typedef struct traceoverlay_event {
  uint32_t sequence;
  uint16_t kind;
  uint16_t result;
  uint32_t current_ip;
  uint32_t applied_ip;
  uint32_t detail;
  uint32_t aux;
  uint64_t thread_id;
} traceoverlay_event;

/* Calls are bounded, allocation-free, and safe inside instrumented sections.
 * A successful drain is performed only outside production locks. */
int traceoverlay_init(void);
void traceoverlay_record(uint16_t kind, uint16_t result, uint32_t current_ip,
                         uint32_t applied_ip, uint32_t detail, uint32_t aux,
                         uint64_t thread_id);
uint32_t traceoverlay_drain(traceoverlay_event *out, uint32_t capacity);
uint32_t traceoverlay_lost(void);
uint32_t traceoverlay_lockfree(void);
void traceoverlay_metrics(uint32_t *attempts, uint32_t *winners, uint32_t *busy,
                          uint32_t *failed, uint32_t *outcomes,
                          uint32_t *probe_completions, uint32_t *active,
                          uint32_t *max_active);

#ifdef __cplusplus
}
#endif
#endif
