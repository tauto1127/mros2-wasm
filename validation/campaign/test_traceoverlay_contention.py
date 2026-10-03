"""Deterministically contend the actual observer reservation CAS path."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from validation.campaign import run


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "traceoverlay.c"
HEADER = HERE / "traceoverlay.h"
HARNESS = r'''#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include "traceoverlay.h"

static pthread_barrier_t reservation_pair;
static _Atomic uint32_t hook_calls;

void traceoverlay_test_before_reservation_cas(void) {
  uint32_t call = atomic_fetch_add_explicit(&hook_calls, 1u, memory_order_relaxed);
  if (call < 2u) pthread_barrier_wait(&reservation_pair);
}

static void *record_attempt(void *unused) {
  (void)unused;
  traceoverlay_record(TRACE_TRYLOCK_ATTEMPT, TRACE_RESULT_UNAVAILABLE,
                      0, 0, 0, 0, (uint64_t)(uintptr_t)pthread_self());
  return NULL;
}

static int collide_pair(void) {
  atomic_store_explicit(&hook_calls, 0u, memory_order_relaxed);
  pthread_t a, b;
  if (pthread_create(&a, NULL, record_attempt, NULL) != 0) return 10;
  if (pthread_create(&b, NULL, record_attempt, NULL) != 0) return 11;
  if (pthread_join(a, NULL) != 0 || pthread_join(b, NULL) != 0) return 12;
  return 0;
}

int main(void) {
  if (pthread_barrier_init(&reservation_pair, NULL, 2) != 0) return 1;
  if (!traceoverlay_init() || !traceoverlay_lockfree()) return 2;
  if (collide_pair() != 0 || collide_pair() != 0) return 3;

  traceoverlay_event events[8];
  uint32_t n = traceoverlay_drain(events, 8);
  traceoverlay_counter_snapshot s;
  traceoverlay_snapshot(&s);
  printf("attempts=%u events=%u lost=%u read=%u next=%u output_failures=%u\n",
         s.attempts, n, s.lost_events, s.read_sequence, s.next_sequence,
         s.output_failures);
  int ok = s.attempts == 4u && n == 4u && s.lost_events == 0u &&
           s.read_sequence == s.next_sequence && s.next_sequence == 4u &&
           s.output_failures == 0u;
  pthread_barrier_destroy(&reservation_pair);
  return ok ? 0 : 20;
}
'''


class TraceoverlayContentionTest(unittest.TestCase):
    def test_real_ring_preserves_two_forced_attempt_cas_collisions(self):
        with tempfile.TemporaryDirectory(prefix="traceoverlay-cas-contention-") as tmp:
            tmp = Path(tmp)
            harness = tmp / "harness.c"
            binary = tmp / "harness"
            harness.write_text(HARNESS)
            subprocess.run([
                os.environ.get("CC", "cc"), "-std=c11", "-D_XOPEN_SOURCE=700",
                "-DTRACEOVERLAY_TEST_RESERVATION_HOOK", "-pthread", "-I", str(HERE),
                str(harness), str(SOURCE), "-o", str(binary),
            ], check=True)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(run.parse_trace_line(
                "RTPS_TRACE_METRICS " + result.stdout.strip())[0], "trace_metrics")
            fields = run.parse_trace_line(
                "RTPS_TRACE_METRICS " + result.stdout.strip())[1]
            self.assertEqual(fields["attempts"], 4)
            self.assertEqual(fields["events"], 4)
            self.assertEqual(fields["lost"], 0)
            self.assertEqual(fields["read"], fields["next"])
            self.assertEqual(fields["next"], 4)


if __name__ == "__main__":
    unittest.main()
