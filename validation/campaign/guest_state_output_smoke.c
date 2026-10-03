#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define RECORDS 1000
static int observer_fd = -1;
static pthread_mutex_t observer_mutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned observer_failures;

typedef struct { const char *kind; } writer_arg;

static void *observer_writer(void *raw_arg) {
  const char *kind = ((writer_arg *)raw_arg)->kind;
  for (unsigned i = 0; i < RECORDS; ++i) {
    char record[768]; int length;
    if (strcmp(kind, "cpp") == 0 || strcmp(kind, "c") == 0)
      length = snprintf(record, sizeof(record), "{\"part\":\"%s\",\"id\":%u}\n", kind, i);
    else if (strcmp(kind, "event") == 0)
      length = snprintf(record, sizeof(record),
          "RTPS_TRACE seq=%u kind=1 result=4 current=0 applied=0 detail=4 aux=9 thread=1234\n", i);
    else
      length = snprintf(record, sizeof(record),
          "RTPS_TRACE_METRICS batch=%u edge=after read=%u next=%u attempts=%u winners=%u busy=0 failed=0 outcomes=%u probe_completions=%u active=0 max_active=1 lost=0 output_failures=0 lockfree=1 addr_read=0x00000001 addr_next=0x00000002 addr_attempts=0x00000003 addr_winners=0x00000004 addr_busy=0x00000005 addr_failed=0x00000006 addr_outcomes=0x00000007 addr_probe_completions=0x00000008 addr_active=0x00000009 addr_max_active=0x0000000a addr_lost=0x0000000b addr_output_failures=0x0000000c addr_lockfree=0x0000000d\n",
          i, i, i, i, i, i, i);
    if (length <= 0 || (size_t)length >= sizeof(record)) return (void *)1;
    if (pthread_mutex_lock(&observer_mutex) != 0) return (void *)1;
    ssize_t written = write(observer_fd, record, (size_t)length);
    if (written != length) ++observer_failures;
    pthread_mutex_unlock(&observer_mutex);
    if (written != length) return (void *)1;
  }
  return NULL;
}

static void *ordinary_logger(void *unused) {
  (void)unused;
  for (unsigned i = 0; i < RECORDS; ++i) {
    /* Ordinary application stdout stays independent from the observer channel. */
    printf("[MROS2LIB] message get id=%u", i);
    printf(" callback_handler\n");
  }
  return NULL;
}

int main(int argc, char **argv) {
  if (argc != 2) return 1;
  observer_fd = open(argv[1], O_WRONLY | O_CREAT | O_APPEND, 0600);
  if (observer_fd < 0) return 2;
  pthread_t threads[5]; writer_arg args[4] = {{"cpp"}, {"c"}, {"event"}, {"metrics"}};
  for (unsigned i = 0; i < 4; ++i)
    if (pthread_create(&threads[i], NULL, observer_writer, &args[i]) != 0) return 3;
  if (pthread_create(&threads[4], NULL, ordinary_logger, NULL) != 0) return 3;
  for (unsigned i = 0; i < 5; ++i) {
    void *result = NULL;
    if (pthread_join(threads[i], &result) != 0 || result != NULL) return 4;
  }
  close(observer_fd);
  return observer_failures ? 5 : 0;
}
