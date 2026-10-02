#include "traceoverlay.h"

#include <stdint.h>
#include <stdio.h>
#include <errno.h>

int main(void)
{
  traceoverlay_event events[4];
  if (!traceoverlay_init() || !traceoverlay_lockfree()) return 1;
  errno = EDOM;
  traceoverlay_record(TRACE_TRYLOCK_OUTCOME, TRACE_RESULT_BUSY, 0, 0, 17, 0, 23);
  if (errno != EDOM) return 6;
  if (traceoverlay_drain(events, 4) != 1) return 2;
  if (events[0].kind != TRACE_TRYLOCK_OUTCOME ||
      events[0].result != TRACE_RESULT_BUSY || events[0].detail != 17 ||
      events[0].thread_id != 23) return 3;
  traceoverlay_record(TRACE_PROBE_ENTER, TRACE_RESULT_UNAVAILABLE, 0, 0, 0, 1, 23);
  traceoverlay_record(TRACE_PROBE_ENTER, TRACE_RESULT_UNAVAILABLE, 0, 0, 0, 1, 24);
  traceoverlay_record(TRACE_PROBE_EXIT, TRACE_RESULT_UNAVAILABLE, 0, 0, 0, 1, 24);
  traceoverlay_record(TRACE_PROBE_EXIT, TRACE_RESULT_UNAVAILABLE, 0, 0, 0, 1, 23);
  uint32_t attempts, winners, busy, failed, outcomes, completed, active, maximum;
  traceoverlay_metrics(&attempts,&winners,&busy,&failed,&outcomes,&completed,&active,&maximum);
  if (maximum != 2 || completed != 2 || active != 0) return 7;
  if (traceoverlay_drain(events, 4) != 4) return 8;
  for (uint32_t i = 0; i < 300; ++i)
    traceoverlay_record(TRACE_EINTR, TRACE_RESULT_UNAVAILABLE, 0, 0, i, 0, 1);
  if (traceoverlay_lost() != 44) return 4;
  if (traceoverlay_drain(events, 4) != 4) return 5;
  printf("RTPS_TRACE seq=%u kind=%u result=%u current=%u applied=%u detail=%u aux=%u thread=%llu\n",
    events[0].sequence,events[0].kind,events[0].result,events[0].current_ip,events[0].applied_ip,
    events[0].detail,events[0].aux,(unsigned long long)events[0].thread_id);
  printf("RTPS_TRACE_METRICS attempts=%u winners=%u busy=%u failed=%u outcomes=%u probe_completions=%u active=%u max_active=%u lost=%u lockfree=%u\n",
    attempts,winners,busy,failed,outcomes,completed,active,maximum,traceoverlay_lost(),traceoverlay_lockfree());
  puts("TRACEOVERLAY_SMOKE_PASS");
  return 0;
}
