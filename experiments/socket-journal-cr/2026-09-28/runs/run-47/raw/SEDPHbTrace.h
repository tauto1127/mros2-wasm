#pragma once

#include "rtps/common/types.h"

#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <ctime>

namespace rtps
{

inline const char *sedpHbWriterName(const EntityId_t &entityId)
{
  if (entityId == ENTITYID_SEDP_BUILTIN_PUBLICATIONS_WRITER)
  {
    return "sedp_publications";
  }
  if (entityId == ENTITYID_SEDP_BUILTIN_SUBSCRIPTIONS_WRITER)
  {
    return "sedp_subscriptions";
  }
  return nullptr;
}

inline void sedpHbTrace(const char *event, const char *format, ...)
{
  static std::atomic<std::uint64_t> sequence{0};
  const std::uint64_t traceSequence =
      sequence.fetch_add(1, std::memory_order_relaxed) + 1;
  struct timespec monotonicTime
  {
  };
  unsigned long long monotonicNs = 0;
  if (::clock_gettime(CLOCK_MONOTONIC, &monotonicTime) == 0)
  {
    monotonicNs =
        static_cast<unsigned long long>(monotonicTime.tv_sec) * 1000000000ULL +
        static_cast<unsigned long long>(monotonicTime.tv_nsec);
  }

  char details[512];
  va_list arguments;
  va_start(arguments, format);
  ::vsnprintf(details, sizeof(details), format, arguments);
  va_end(arguments);
  ::printf("[SEDP-HB] seq=%llu mono_ns=%llu event=%s %s\n",
           static_cast<unsigned long long>(traceSequence), monotonicNs, event,
           details);
  ::fflush(stdout);
}

} // namespace rtps
