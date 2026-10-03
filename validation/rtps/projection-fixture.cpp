#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <type_traits>
#include <cstdint>
#include <atomic>
#include <thread>
#include <chrono>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

#define RTPS_T10_TEST_ACCESS 1
#include "rtps/entities/Domain.h"
#include "rtps/entities/StatefulWriter.h"
extern "C" {
#include "cmsis_os.h"
#include "lwip/mem.h"
#include "lwip/memp.h"
#include "lwip/pbuf.h"
#include "lwip/sys.h"
#include "lwipopts.h"
#include "netif_wasm_add.h"
}

#define CHECK(expr) do { if (!(expr)) { std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #expr); std::abort(); } } while (0)

// Narrow test-only route-selection shim: netif_wasm_add and its publication
// path remain the real production functions. Only the probe's UDP connect /
// getsockname result is supplied; unrelated sockets delegate to libc.
static uint32_t fixture_ip = 0x0300000aU;
static bool fixture_ip_valid = true;
extern "C" int __wrap_netif_wasm_get_ip_snapshot(netif_wasm_ip_snapshot_t *snapshot) {
  if (snapshot == nullptr) return -1;
  snapshot->valid = fixture_ip_valid;
  snapshot->ip_addr = fixture_ip;
  snapshot->netmask = 0x00ffffffU;
  return 0;
}
static int probe_fd = -1;
static int fail_pbuf_alloc_at = 0, pbuf_alloc_calls = 0;
static int fail_sys_mutex_new_at = 0, sys_mutex_new_calls = 0;
static bool sys_mutex_injection_active = false, sys_mutex_failure_observed = false;
extern "C" err_t __real_sys_mutex_new(sys_mutex_t *mutex);
extern "C" err_t __wrap_sys_mutex_new(sys_mutex_t *mutex) {
  if (sys_mutex_injection_active) {
    ++sys_mutex_new_calls;
    if (sys_mutex_new_calls == fail_sys_mutex_new_at) {
      sys_mutex_failure_observed = true;
      return ERR_MEM;
    }
  }
  return __real_sys_mutex_new(mutex);
}
static std::atomic<bool> commit_audit_active{false};
static std::atomic<int> commit_pbuf_allocs{0}, commit_new_calls{0}, commit_audit_phases{0};
static std::atomic<bool> pause_projection_commit{false};
static std::atomic<bool> projection_commit_prepared{false};
static std::atomic<bool> release_projection_commit{false};
namespace rtps { void rtpsT10CommitAudit(int active) {
  if (active) {
    CHECK(!commit_audit_active.exchange(true)); ++commit_audit_phases;
    if (pause_projection_commit.load(std::memory_order_acquire)) {
      projection_commit_prepared.store(true, std::memory_order_release);
      while (!release_projection_commit.load(std::memory_order_acquire))
        std::this_thread::yield();
    }
  } else { CHECK(commit_audit_active.exchange(false)); ++commit_audit_phases; }
} }
extern "C" void *__real__Znwm(size_t);
extern "C" void *__wrap__Znwm(size_t size) {
  if (commit_audit_active) ++commit_new_calls;
  return __real__Znwm(size);
}
static int pbuf_allocated_nodes = 0, pbuf_free_calls = 0, pbuf_freed_nodes = 0, pbuf_ref_calls = 0;
static int fail_pbuf_take_at = 0, pbuf_take_calls = 0;
enum UcdrKind { U16, U32, I32, U8, ARRAY_U8, ARRAY_CHAR, UCDR_KIND_COUNT };
static int fail_ucdr_at[UCDR_KIND_COUNT]{};
static int ucdr_calls[UCDR_KIND_COUNT]{};
static bool injectUcdr(UcdrKind kind, ucdrBuffer *buffer) {
  if (++ucdr_calls[kind] != fail_ucdr_at[kind]) return false;
  buffer->error = true;
  return true;
}
extern "C" struct pbuf *__real_pbuf_alloc(pbuf_layer, u16_t, pbuf_type);
extern "C" struct pbuf *__wrap_pbuf_alloc(pbuf_layer layer, u16_t length, pbuf_type type) {
  if (++pbuf_alloc_calls == fail_pbuf_alloc_at) return nullptr;
  if (commit_audit_active) ++commit_pbuf_allocs;
  struct pbuf *head = __real_pbuf_alloc(layer, length, type);
  if (head != nullptr) pbuf_allocated_nodes += pbuf_clen(head);
  return head;
}
extern "C" u8_t __real_pbuf_free(struct pbuf *);
extern "C" u8_t __wrap_pbuf_free(struct pbuf *head) {
  ++pbuf_free_calls;
  for (struct pbuf *node = head; node != nullptr && node->ref == 1; node = node->next) ++pbuf_freed_nodes;
  return __real_pbuf_free(head);
}
extern "C" void __real_pbuf_ref(struct pbuf *);
extern "C" void __wrap_pbuf_ref(struct pbuf *p) { ++pbuf_ref_calls; __real_pbuf_ref(p); }
extern "C" err_t __real_pbuf_take_at(struct pbuf *, const void *, u16_t, u16_t);
extern "C" err_t __wrap_pbuf_take_at(struct pbuf *buffer, const void *data, u16_t length, u16_t offset) {
  if (++pbuf_take_calls == fail_pbuf_take_at) return ERR_MEM;
  return __real_pbuf_take_at(buffer, data, length, offset);
}
#define UCDR_WRAP_BASIC(type, suffix, kind) \
  extern "C" bool __real_ucdr_serialize_##suffix(ucdrBuffer *, type); \
  extern "C" bool __wrap_ucdr_serialize_##suffix(ucdrBuffer *buffer, type value) { \
    if (injectUcdr(kind, buffer)) return false; \
    return __real_ucdr_serialize_##suffix(buffer, value); \
  }
UCDR_WRAP_BASIC(uint16_t, uint16_t, U16)
UCDR_WRAP_BASIC(uint32_t, uint32_t, U32)
UCDR_WRAP_BASIC(int32_t, int32_t, I32)
UCDR_WRAP_BASIC(uint8_t, uint8_t, U8)
extern "C" bool __real_ucdr_serialize_array_uint8_t(ucdrBuffer *, const uint8_t *, uint32_t);
extern "C" bool __wrap_ucdr_serialize_array_uint8_t(ucdrBuffer *buffer, const uint8_t *data, uint32_t length) {
  if (injectUcdr(ARRAY_U8, buffer)) return false;
  return __real_ucdr_serialize_array_uint8_t(buffer, data, length);
}
extern "C" bool __real_ucdr_serialize_array_char(ucdrBuffer *, const char *, uint32_t);
extern "C" bool __wrap_ucdr_serialize_array_char(ucdrBuffer *buffer, const char *data, uint32_t length) {
  if (injectUcdr(ARRAY_CHAR, buffer)) return false;
  return __real_ucdr_serialize_array_char(buffer, data, length);
}
static void resetFailures() {
  fail_pbuf_alloc_at = fail_pbuf_take_at = 0;
  pbuf_alloc_calls = pbuf_take_calls = 0;
  pbuf_allocated_nodes = pbuf_free_calls = pbuf_freed_nodes = pbuf_ref_calls = 0;
  for (int i = 0; i < UCDR_KIND_COUNT; ++i) fail_ucdr_at[i] = ucdr_calls[i] = 0;
}
extern "C" int __real_connect(int, const struct sockaddr *, socklen_t);
extern "C" int __real_getsockname(int, struct sockaddr *, socklen_t *);
extern "C" int __wrap_connect(int fd, const struct sockaddr *address,
                               socklen_t length) {
  if (address != nullptr && length >= sizeof(sockaddr_in) &&
      address->sa_family == AF_INET) {
    const auto *ipv4 = reinterpret_cast<const sockaddr_in *>(address);
    if (ntohs(ipv4->sin_port) == 7400 &&
        ntohl(ipv4->sin_addr.s_addr) == 0xefff0001U) {
      probe_fd = fd;
      return 0;
    }
  }
  return __real_connect(fd, address, length);
}
extern "C" int __wrap_getsockname(int fd, struct sockaddr *address,
                                  socklen_t *length) {
  if (fd == probe_fd && address != nullptr && length != nullptr &&
      *length >= sizeof(sockaddr_in)) {
    auto *ipv4 = reinterpret_cast<sockaddr_in *>(address);
    std::memset(ipv4, 0, sizeof(*ipv4));
    ipv4->sin_family = AF_INET;
    ipv4->sin_addr.s_addr = htonl(0x0a000006U);
    *length = sizeof(*ipv4);
    return 0;
  }
  return __real_getsockname(fd, address, length);
}

namespace rtps {
struct T10aHarness {
  struct WriterView {
    SequenceNumber_t min{}, max{}, latestSn{}, cursor{};
    std::array<uint8_t, 600> latest{};
    uint16_t length = 0;
  };
  static bool initialized(const Participant &part) {
    return part.m_spdpAgent.initialized && part.m_sedpAgent.m_part == &part &&
           part.m_spdpAgent.m_buildInEndpoints.spdpWriter &&
           part.m_spdpAgent.m_buildInEndpoints.spdpWriter->isInitialized() &&
           part.m_spdpAgent.m_buildInEndpoints.spdpReader->isInitialized() &&
           part.m_sedpAgent.m_endpoints.sedpPubWriter->isInitialized() &&
           part.m_sedpAgent.m_endpoints.sedpPubReader->isInitialized() &&
           part.m_sedpAgent.m_endpoints.sedpSubWriter->isInitialized() &&
           part.m_sedpAgent.m_endpoints.sedpSubReader->isInitialized();
  }

  static bool project(Participant &part, uint32_t address) {
    return part.m_sedpAgent.projectLocalIp(address);
  }
  static bool refresh(Participant &part) { return part.m_spdpAgent.refreshLocalIp(); }
  static void injectThreeWriters(Participant &part, Writer *writer) {
    sys_mutex_lock(&part.m_mutex);
    part.m_writers[0] = writer; part.m_writers[1] = writer; part.m_writers[2] = writer;
    part.m_numWriters = 3;
    sys_mutex_unlock(&part.m_mutex);
  }

  static uint32_t applied(const Participant &part) {
    return part.m_spdpAgent.m_lastAppliedIp;
  }

  static const CacheChange *latestSpdp(const Participant &part) {
    const auto *writer = part.m_spdpAgent.m_buildInEndpoints.spdpWriter;
    const auto &history = writer->m_history;
    const SequenceNumber_t &max = history.getSeqNumMax();
    return history.getChangeBySN(max);
  }

  static SequenceNumber_t latestSpdpSequence(const Participant &part) {
    return part.m_spdpAgent.m_buildInEndpoints.spdpWriter->m_history.getSeqNumMax();
  }
  static std::array<uint8_t, 400> output(const Participant &part) {
    return part.m_spdpAgent.m_outputBuffer;
  }
  static bool payloadAt(const StatefulWriter &writer, SequenceNumber_t sn,
                        std::array<uint8_t, 600> &bytes, uint16_t &length) {
    const CacheChange *change = writer.m_history.getChangeBySN(sn);
    if (change == nullptr || !change->data.isValid()) return false;
    length = change->data.spaceUsed();
    if (length > bytes.size()) return false;
    return pbuf_copy_partial(change->data.firstElement, bytes.data(), length, 0) == length;
  }
  template <typename WriterType>
  static WriterView writerViewImpl(const WriterType &writer) {
    WriterView view{};
    view.min = writer.m_history.getSeqNumMin();
    view.max = writer.m_history.getSeqNumMax();
    view.cursor = writer.m_nextSequenceNumberToSend;
    const CacheChange *change = writer.m_history.getChangeBySN(view.max);
    if (change != nullptr && change->data.isValid()) {
      view.latestSn = change->sequenceNumber;
      view.length = change->data.spaceUsed();
      CHECK(view.length <= view.latest.size());
      CHECK(pbuf_copy_partial(change->data.firstElement, view.latest.data(), view.length, 0) == view.length);
    }
    return view;
  }
  static WriterView writerView(const StatefulWriter &writer) { return writerViewImpl(writer); }
  static WriterView writerView(const StatelessWriter &writer) { return writerViewImpl(writer); }
  static StatelessWriter &spdpWriter(Participant &part) { return *part.m_spdpAgent.m_buildInEndpoints.spdpWriter; }
  static StatefulWriter &sedpPubWriter(Participant &part) { return *part.m_sedpAgent.m_endpoints.sedpPubWriter; }
  static StatefulWriter &sedpSubWriter(Participant &part) { return *part.m_sedpAgent.m_endpoints.sedpSubWriter; }
  static std::array<uint8_t, 512> latestBytes(const Participant &part) {
    std::array<uint8_t, 512> bytes{};
    const auto *change = latestSpdp(part);
    CHECK(change != nullptr && change->data.isValid());
    CHECK(pbuf_copy_partial(change->data.firstElement, bytes.data(), change->data.spaceUsed(), 0) == change->data.spaceUsed());
    return bytes;
  }
  struct HistoryRefs { uintptr_t nodes[512]{}; uint16_t refs[512]{}; size_t count = 0; };
  template <typename WriterType>
  static void appendHistoryRefs(const WriterType &writer, HistoryRefs &result) {
    const auto &history = writer.m_history;
    SequenceNumber_t sn = history.getSeqNumMin();
    const SequenceNumber_t max = history.getSeqNumMax();
    if (sn == SEQUENCENUMBER_UNKNOWN) return;
    while (!(max < sn)) {
      const CacheChange *change = history.getChangeBySN(sn);
      CHECK(change != nullptr && change->data.isValid());
      for (const pbuf *node = change->data.firstElement; node != nullptr; node = node->next) {
        CHECK(result.count < 512);
        result.nodes[result.count] = reinterpret_cast<uintptr_t>(node);
        result.refs[result.count++] = node->ref;
      }
      ++sn;
    }
  }
  static HistoryRefs historyRefs(const Participant &part) {
    HistoryRefs refs{};
    appendHistoryRefs(*part.m_spdpAgent.m_buildInEndpoints.spdpWriter, refs);
    appendHistoryRefs(*part.m_sedpAgent.m_endpoints.sedpPubWriter, refs);
    appendHistoryRefs(*part.m_sedpAgent.m_endpoints.sedpSubWriter, refs);
    return refs;
  }
  static std::array<uint8_t, sizeof(FullLengthLocator)> locatorBytes(const FullLengthLocator &locator) {
    std::array<uint8_t, sizeof(FullLengthLocator)> bytes{};
    std::memcpy(bytes.data(), &locator, bytes.size());
    return bytes;
  }
  struct PbufPoolUse { u32_t pbuf = 0, pool = 0; };
  static PbufPoolUse pbufPoolUse() {
    return {MEMP_STATS_GET(used, MEMP_PBUF), MEMP_STATS_GET(used, MEMP_PBUF_POOL)};
  }
  static uint8_t writerCount(const Participant &part) { return part.m_numWriters; }
  static uint8_t readerCount(const Participant &part) { return part.m_numReaders; }
  static bool endpointSnapshotValid(const Participant &part) {
    const auto snapshot = part.snapshotEndpoints();
    if (snapshot.numWriters > snapshot.writers.size() ||
        snapshot.numReaders > snapshot.readers.size()) return false;
    for (uint8_t i = 0; i < snapshot.numWriters; ++i)
      if (snapshot.writers[i] == nullptr) return false;
    for (uint8_t i = 0; i < snapshot.numReaders; ++i)
      if (snapshot.readers[i] == nullptr) return false;
    return true;
  }
  static bool hasPublishedWriter(Participant &part, const Writer *writer) {
    const auto snapshot = part.snapshotEndpoints();
    for (uint8_t i = 0; i < snapshot.numWriters; ++i)
      if (snapshot.writers[i] == writer) return true;
    return false;
  }
  static auto writerPointers(const Participant &part) { return part.m_writers; }
  static auto readerPointers(const Participant &part) { return part.m_readers; }
  static uint8_t domainWriterCount(const Domain &d) { return d.m_numStatefulWriters; }
  static uint8_t domainReaderCount(const Domain &d) { return d.m_numStatefulReaders; }
  static uint8_t domainStatelessWriterCount(const Domain &d) { return d.m_numStatelessWriters; }
  static uint8_t domainStatelessReaderCount(const Domain &d) { return d.m_numStatelessReaders; }
  static Participant *participantSlot(Domain &d, size_t n) { return &d.m_participants[n]; }
  static uint8_t nextParticipantId(const Domain &d) { return d.m_nextParticipantId; }
  static sys_mutex_t &sedpMutex(Participant &part) { return part.m_sedpAgent.m_mutex; }
  static sys_mutex_t &participantMutex(Participant &part) { return part.m_mutex; }
  static bool hasBuiltin(const Participant &part) { return part.m_hasBuilInEndpoints; }
  static bool spdpRunning(const Participant &part) { return part.m_spdpAgent.m_running; }
  static bool spdpInitialized(const Participant &part) { return part.m_spdpAgent.initialized; }
  static bool spdpWriterInitialized(Domain &d, size_t n) { return d.m_statelessWriters[n].isInitialized(); }
  static bool spdpReaderInitialized(Domain &d, size_t n) { return d.m_statelessReaders[n].isInitialized(); }
  static bool statefulReaderInitialized(Domain &d, size_t n) { return d.m_statefulReaders[n].isInitialized(); }
  static bool statefulWriterInitialized(Domain &d, size_t n) { return d.m_statefulWriters[n].isInitialized(); }
};
}

static void fixture_init() {
  CHECK(osKernelStart() == osOK);
  sys_init();
  mem_init();
  memp_init();
  pbuf_init();
  // Exercise the real project netif publication path; no host network/probe is
  // needed. Domain and all endpoints still use production constructors/init.
  CHECK(netif_wasm_add("10.0.0.3", "255.255.255.0") == 0);
  fixture_ip = 0x0300000aU;
  fixture_ip_valid = true;
}

static bool sameSn(rtps::SequenceNumber_t left, rtps::SequenceNumber_t right);
static void test_t10b2_preparation_positions() {
  rtps::Domain domain;
  rtps::Participant *part = domain.createParticipant();
  CHECK(part != nullptr && rtps::T10aHarness::initialized(*part));
  auto *userWriter = domain.createWriter(*part, "t10b2-topic", "t10b2-type", true);
  auto *userReader = domain.createReader(*part, "t10b2-topic", "t10b2-type", true);
  CHECK(userWriter != nullptr && userReader != nullptr && userWriter->isInitialized() && userReader->isInitialized());
  ip4_addr_t ip3{}, ip6{};
  IP4_ADDR(&ip3, 10, 0, 0, 3);
  IP4_ADDR(&ip6, 10, 0, 0, 6);
  CHECK(rtps::T10aHarness::project(*part, ip3.addr));
  resetFailures();
  CHECK(rtps::T10aHarness::project(*part, ip6.addr));
  int counts[UCDR_KIND_COUNT]{};
  std::memcpy(counts, ucdr_calls, sizeof(counts));
  const int allocCount = pbuf_alloc_calls, takeCount = pbuf_take_calls;
  CHECK(allocCount > 0 && takeCount > 0);
  CHECK(rtps::T10aHarness::project(*part, ip3.addr));
  const auto baselineOutput = rtps::T10aHarness::output(*part);
  const auto baselineSpdp = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
  const auto baselinePub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
  const auto baselineSub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
  const auto locatorWriter = rtps::T10aHarness::locatorBytes(userWriter->m_attributes.unicastLocator);
  const auto locatorReader = rtps::T10aHarness::locatorBytes(userReader->m_attributes.unicastLocator);
  const auto baselineSpdpBytes = rtps::T10aHarness::latestBytes(*part);
  const auto baselinePoolUse = rtps::T10aHarness::pbufPoolUse();
  const auto baselineHistoryRefs = rtps::T10aHarness::historyRefs(*part);
  int cases = 0;
  const auto checkState = [&]() {
    CHECK(rtps::T10aHarness::applied(*part) == ip3.addr);
    CHECK(rtps::T10aHarness::locatorBytes(userWriter->m_attributes.unicastLocator) == locatorWriter);
    CHECK(rtps::T10aHarness::locatorBytes(userReader->m_attributes.unicastLocator) == locatorReader);
    CHECK(rtps::T10aHarness::output(*part) == baselineOutput);
    CHECK(rtps::T10aHarness::latestBytes(*part) == baselineSpdpBytes);
    const auto spdp = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
    const auto pub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
    const auto sub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
    CHECK(sameSn(spdp.min, baselineSpdp.min) && sameSn(spdp.max, baselineSpdp.max) && sameSn(spdp.cursor, baselineSpdp.cursor) && spdp.latest == baselineSpdp.latest && spdp.length == baselineSpdp.length);
    CHECK(sameSn(pub.min, baselinePub.min) && sameSn(pub.max, baselinePub.max) && sameSn(pub.cursor, baselinePub.cursor) && pub.latest == baselinePub.latest && pub.length == baselinePub.length);
    CHECK(sameSn(sub.min, baselineSub.min) && sameSn(sub.max, baselineSub.max) && sameSn(sub.cursor, baselineSub.cursor) && sub.latest == baselineSub.latest && sub.length == baselineSub.length);
    const auto poolUse = rtps::T10aHarness::pbufPoolUse();
    CHECK(poolUse.pbuf == baselinePoolUse.pbuf && poolUse.pool == baselinePoolUse.pool);
    const auto historyRefs = rtps::T10aHarness::historyRefs(*part);
    CHECK(historyRefs.count == baselineHistoryRefs.count);
    CHECK(std::memcmp(historyRefs.nodes, baselineHistoryRefs.nodes, historyRefs.count * sizeof(historyRefs.nodes[0])) == 0);
    CHECK(std::memcmp(historyRefs.refs, baselineHistoryRefs.refs, historyRefs.count * sizeof(historyRefs.refs[0])) == 0);
    CHECK(pbuf_allocated_nodes == pbuf_freed_nodes);
  };
  for (int kind = 0; kind < UCDR_KIND_COUNT; ++kind) {
    for (int n = 1; n <= counts[kind]; ++n) {
      resetFailures(); fail_ucdr_at[kind] = n;
      CHECK(!rtps::T10aHarness::project(*part, ip6.addr));
      checkState(); ++cases;
    }
  }
  for (int n = 1; n <= allocCount; ++n) {
    resetFailures(); fail_pbuf_alloc_at = n;
    CHECK(!rtps::T10aHarness::project(*part, ip6.addr)); checkState(); ++cases;
  }
  for (int n = 1; n <= takeCount; ++n) {
    resetFailures(); fail_pbuf_take_at = n;
    CHECK(!rtps::T10aHarness::project(*part, ip6.addr)); checkState(); ++cases;
  }
  resetFailures();
  CHECK(rtps::T10aHarness::project(*part, ip6.addr));
  std::printf("T10b2_MATRIX_PASS cases=%d pbuf_alloc=%d pbuf_take_at=%d ucdr_u16=%d ucdr_u32=%d ucdr_i32=%d ucdr_u8=%d ucdr_array_u8=%d ucdr_array_char=%d user_endpoints=1 atomic_state=1\\n", cases, allocCount, takeCount, counts[U16], counts[U32], counts[I32], counts[U8], counts[ARRAY_U8], counts[ARRAY_CHAR]);
}

static bool sameSn(rtps::SequenceNumber_t left, rtps::SequenceNumber_t right) {
  return left.high == right.high && left.low == right.low;
}
static bool snInRange(rtps::SequenceNumber_t value, rtps::SequenceNumber_t min,
                      rtps::SequenceNumber_t max) {
  return !(value < min) && !(max < value);
}

static void setFixtureIp(uint32_t hostOrder);

static void test_t10b3() {
  rtps::Domain domain;
  rtps::Participant *part = domain.createParticipant();
  CHECK(part != nullptr && rtps::T10aHarness::initialized(*part));
  auto *w1 = domain.createWriter(*part, "t10b3-one", "type", true);
  auto *r1 = domain.createReader(*part, "t10b3-one", "type", true);
  CHECK(w1 && r1);
  ip4_addr_t a{}, b{};
  IP4_ADDR(&a, 10, 0, 0, 3); IP4_ADDR(&b, 10, 0, 0, 6);
  const auto failFromZero = [&]() {
    resetFailures(); fail_pbuf_alloc_at = 1;
    const auto pool = rtps::T10aHarness::pbufPoolUse();
    CHECK(!rtps::T10aHarness::project(*part, b.addr));
    const auto afterPool = rtps::T10aHarness::pbufPoolUse();
    CHECK(pool.pbuf == afterPool.pbuf && pool.pool == afterPool.pool);
    CHECK(pbuf_allocated_nodes == pbuf_freed_nodes);
    CHECK(rtps::T10aHarness::applied(*part) == 0);
    CHECK(rtps::T10aHarness::project(*part, a.addr));
    CHECK(rtps::T10aHarness::applied(*part) == a.addr);
  };
  failFromZero();
  const auto outputA = rtps::T10aHarness::output(*part);
  const auto spdpA = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
  const auto pubA = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
  const auto subA = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
  std::array<uint8_t, 600> oldPayload{};
  uint16_t oldPayloadLength = 0;
  CHECK(rtps::T10aHarness::payloadAt(rtps::T10aHarness::sedpPubWriter(*part), pubA.max, oldPayload, oldPayloadLength));
  const auto locW = rtps::T10aHarness::locatorBytes(w1->m_attributes.unicastLocator);
  const auto locR = rtps::T10aHarness::locatorBytes(r1->m_attributes.unicastLocator);
  const auto refsA = rtps::T10aHarness::historyRefs(*part);
  const auto assertA = [&]() {
    CHECK(rtps::T10aHarness::applied(*part) == a.addr);
    CHECK(rtps::T10aHarness::output(*part) == outputA);
    CHECK(rtps::T10aHarness::locatorBytes(w1->m_attributes.unicastLocator) == locW);
    CHECK(rtps::T10aHarness::locatorBytes(r1->m_attributes.unicastLocator) == locR);
    const auto s = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
    const auto p = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
    const auto r = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
    CHECK(sameSn(s.min,spdpA.min)&&sameSn(s.max,spdpA.max)&&sameSn(s.cursor,spdpA.cursor)&&s.latest==spdpA.latest);
    CHECK(sameSn(p.min,pubA.min)&&sameSn(p.max,pubA.max)&&sameSn(p.cursor,pubA.cursor)&&p.latest==pubA.latest);
    CHECK(sameSn(r.min,subA.min)&&sameSn(r.max,subA.max)&&sameSn(r.cursor,subA.cursor)&&r.latest==subA.latest);
    const auto refs = rtps::T10aHarness::historyRefs(*part);
    CHECK(refs.count == refsA.count);
    CHECK(std::memcmp(refs.nodes, refsA.nodes, refs.count * sizeof(refs.nodes[0])) == 0);
    CHECK(std::memcmp(refs.refs, refsA.refs, refs.count * sizeof(refs.refs[0])) == 0);
  };
  resetFailures(); fail_pbuf_alloc_at = 1;
  const auto poolA = rtps::T10aHarness::pbufPoolUse();
  CHECK(!rtps::T10aHarness::project(*part, b.addr)); assertA();
  const auto poolFailedB = rtps::T10aHarness::pbufPoolUse();
  CHECK(poolA.pbuf == poolFailedB.pbuf && poolA.pool == poolFailedB.pool);
  CHECK(pbuf_allocated_nodes == pbuf_freed_nodes);
  CHECK(rtps::T10aHarness::project(*part, a.addr)); assertA(); // failure B, coordinator/current A => equal no-op

  // An unchanged refresh result still carries the real current B snapshot; a
  // previous failed transaction must retry and converge on that snapshot.
  setFixtureIp(0x0a000006U); // UNCHANGED probe must carry the live current B snapshot.
  resetFailures(); CHECK(rtps::T10aHarness::refresh(*part));
  CHECK(rtps::T10aHarness::applied(*part) == b.addr);
  auto spdpB = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
  CHECK(sameSn(spdpB.min, spdpB.max) && sameSn(spdpB.latestSn, spdpB.max));
  CHECK(sameSn(spdpB.cursor, spdpB.latestSn));
  const auto pubB = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
  const auto subB = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
  CHECK(pubA.max < pubB.max && subA.max < subB.max);
  std::array<uint8_t, 600> retainedOld{};
  uint16_t retainedOldLength = 0;
  CHECK(rtps::T10aHarness::payloadAt(rtps::T10aHarness::sedpPubWriter(*part), pubA.max, retainedOld, retainedOldLength));
  CHECK(retainedOldLength == oldPayloadLength && std::memcmp(retainedOld.data(), oldPayload.data(), oldPayloadLength) == 0);
  CHECK(pubB.max.low - pubB.min.low + 1 <= 2 && subB.max.low - subB.min.low + 1 <= 2);
  CHECK(rtps::T10aHarness::project(*part, b.addr));
  CHECK(rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part)).latest == spdpB.latest);
  CHECK(commit_audit_phases > 0 && (commit_audit_phases % 2) == 0 && !commit_audit_active);
  CHECK(commit_pbuf_allocs == 0 && commit_new_calls == 0);

  // Bypass normal registration only to exercise the defensive fixed-history
  // population bound: three actual initialized user writer entries exceed the
  // writer's supported history capacity of two.
  rtps::T10aHarness::injectThreeWriters(*part, w1);
  const auto before = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
  const auto beforeSub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
  const auto beforeSpdp = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
  const auto beforeOutput = rtps::T10aHarness::output(*part);
  const auto beforeLocator = rtps::T10aHarness::locatorBytes(w1->m_attributes.unicastLocator);
  const auto beforeRefs = rtps::T10aHarness::historyRefs(*part);
  const auto applied = rtps::T10aHarness::applied(*part);
  CHECK(!rtps::T10aHarness::project(*part, a.addr));
  const auto after = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
  const auto afterSub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
  const auto afterSpdp = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
  const auto afterRefs = rtps::T10aHarness::historyRefs(*part);
  CHECK(rtps::T10aHarness::applied(*part) == applied);
  CHECK(rtps::T10aHarness::output(*part) == beforeOutput);
  CHECK(rtps::T10aHarness::locatorBytes(w1->m_attributes.unicastLocator) == beforeLocator);
  CHECK(sameSn(before.min,after.min)&&sameSn(before.max,after.max)&&sameSn(before.cursor,after.cursor)&&before.latest==after.latest);
  CHECK(sameSn(beforeSub.min,afterSub.min)&&sameSn(beforeSub.max,afterSub.max)&&sameSn(beforeSub.cursor,afterSub.cursor)&&beforeSub.latest==afterSub.latest);
  CHECK(sameSn(beforeSpdp.min,afterSpdp.min)&&sameSn(beforeSpdp.max,afterSpdp.max)&&sameSn(beforeSpdp.cursor,afterSpdp.cursor)&&beforeSpdp.latest==afterSpdp.latest);
  CHECK(beforeRefs.count == afterRefs.count);
  CHECK(std::memcmp(beforeRefs.nodes, afterRefs.nodes, beforeRefs.count * sizeof(beforeRefs.nodes[0])) == 0);
  CHECK(std::memcmp(beforeRefs.refs, afterRefs.refs, beforeRefs.count * sizeof(beforeRefs.refs[0])) == 0);
  std::puts("T10b3_DISPATCH_PASS zero_to_A=1 failure_B_equal_A_noop=1 retry_unchanged_current_B=1 latest_SPDP=1 commit_noalloc=1 over_history_rejected=1");
}

static void test_t10b1_users() {
  rtps::Domain domain;
  rtps::Participant *part = domain.createParticipant();
  CHECK(part != nullptr && rtps::T10aHarness::initialized(*part));
  auto *userWriter = domain.createWriter(*part, "t10b1-topic", "t10b1-type", true);
  auto *userReader = domain.createReader(*part, "t10b1-topic", "t10b1-type", true);
  CHECK(userWriter != nullptr && userReader != nullptr);
  CHECK(userWriter->isInitialized() && userReader->isInitialized());

  ip4_addr_t ip3{}, ip6{};
  IP4_ADDR(&ip3, 10, 0, 0, 3);
  IP4_ADDR(&ip6, 10, 0, 0, 6);
  CHECK(rtps::T10aHarness::project(*part, ip3.addr));
  CHECK(rtps::T10aHarness::applied(*part) == ip3.addr);
  const auto locator3 = rtps::getUserUnicastLocator(part->m_participantId, {{10, 0, 0, 3}});
  CHECK(userWriter->m_attributes.unicastLocator.address == locator3.address);
  CHECK(userReader->m_attributes.unicastLocator.address == locator3.address);
  const auto spdp3 = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
  const auto pub3 = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
  const auto sub3 = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
  CHECK(spdp3.length > 0 && pub3.length > 0 && sub3.length > 0);
  CHECK(sameSn(spdp3.latestSn, spdp3.max) && sameSn(pub3.latestSn, pub3.max) && sameSn(sub3.latestSn, sub3.max));
  std::array<uint8_t, 600> retained{};
  uint16_t retainedLength = 0;
  CHECK(rtps::T10aHarness::payloadAt(rtps::T10aHarness::sedpPubWriter(*part), pub3.max, retained, retainedLength));
  CHECK(retainedLength == pub3.length && std::memcmp(retained.data(), pub3.latest.data(), retainedLength) == 0);
  CHECK(rtps::T10aHarness::payloadAt(rtps::T10aHarness::sedpSubWriter(*part), sub3.max, retained, retainedLength));
  CHECK(retainedLength == sub3.length && std::memcmp(retained.data(), sub3.latest.data(), retainedLength) == 0);

  CHECK(rtps::T10aHarness::project(*part, ip6.addr));
  CHECK(rtps::T10aHarness::applied(*part) == ip6.addr);
  const auto locator6 = rtps::getUserUnicastLocator(part->m_participantId, {{10, 0, 0, 6}});
  CHECK(userWriter->m_attributes.unicastLocator.address == locator6.address);
  CHECK(userReader->m_attributes.unicastLocator.address == locator6.address);
  const auto spdp6 = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
  const auto pub6 = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
  const auto sub6 = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
  CHECK(spdp6.length > 0 && pub6.length > 0 && sub6.length > 0);
  CHECK(sameSn(spdp6.latestSn, spdp6.max) && sameSn(pub6.latestSn, pub6.max) && sameSn(sub6.latestSn, sub6.max));
  CHECK(spdp3.max.low < spdp6.max.low && pub3.max.low < pub6.max.low && sub3.max.low < sub6.max.low);
  CHECK(sameSn(spdp6.min, spdp6.max)); // SPDP writer retains only latest announcement.
  CHECK(pub6.min.low >= pub3.min.low && sub6.min.low >= sub3.min.low);
  CHECK(snInRange(spdp3.cursor, spdp3.min, spdp3.max) && snInRange(pub3.cursor, pub3.min, pub3.max) && snInRange(sub3.cursor, sub3.min, sub3.max));
  CHECK(snInRange(spdp6.cursor, spdp6.min, spdp6.max) && snInRange(pub6.cursor, pub6.min, pub6.max) && snInRange(sub6.cursor, sub6.min, sub6.max));
  CHECK(spdp3.latest != spdp6.latest && pub3.latest != pub6.latest && sub3.latest != sub6.latest);
  CHECK(rtps::T10aHarness::payloadAt(rtps::T10aHarness::sedpPubWriter(*part), pub6.max, retained, retainedLength));
  CHECK(retainedLength == pub6.length && std::memcmp(retained.data(), pub6.latest.data(), retainedLength) == 0);
  CHECK(rtps::T10aHarness::payloadAt(rtps::T10aHarness::sedpSubWriter(*part), sub6.max, retained, retainedLength));
  CHECK(retainedLength == sub6.length && std::memcmp(retained.data(), sub6.latest.data(), retainedLength) == 0);
  std::puts("T10b1_USERS_PASS real_writer=1 real_reader=1 locators_3_to_6=1 sedp_pubsub_histories=1 spdp_history_applied_cursors=1 retained_owned_payload=1");
}

static void setFixtureIp(uint32_t hostOrder) {
  fixture_ip = htonl(hostOrder);
  fixture_ip_valid = hostOrder != 0;
}

static void test_t10c_startup_birth() {
  ip4_addr_t ip3{}, ip6{};
  IP4_ADDR(&ip3, 10, 0, 0, 3); IP4_ADDR(&ip6, 10, 0, 0, 6);
  // Empty user population and a zero applied IP are a valid projection input.
  {
    rtps::Domain domain;
    auto *part = domain.createParticipant();
    CHECK(part && rtps::T10aHarness::initialized(*part));
    CHECK(rtps::T10aHarness::writerCount(*part) == 3 && rtps::T10aHarness::readerCount(*part) == 3);
    CHECK(rtps::T10aHarness::applied(*part) == 0);
    CHECK(rtps::T10aHarness::project(*part, ip6.addr));
    CHECK(rtps::T10aHarness::applied(*part) == ip6.addr);
  }
  // Missing initial address publishes no builtins/readiness, and a failed
  // partially initialized fixed-pool slot is retired rather than reused.
  {
    rtps::Domain domain;
    setFixtureIp(0);
    CHECK(domain.createParticipant() == nullptr);
    CHECK(rtps::T10aHarness::domainWriterCount(domain) == 0);
    CHECK(rtps::T10aHarness::domainReaderCount(domain) == 0);
    CHECK(!rtps::T10aHarness::hasBuiltin(*rtps::T10aHarness::participantSlot(domain, 0)));
    CHECK(rtps::T10aHarness::nextParticipantId(domain) == 1);
    setFixtureIp(0x0a000003U);
    // The incremented creation id makes the failed fixed-pool slot ineligible
    // for reinitialization (this fixture configuration has one participant slot).
    CHECK(domain.createParticipant() == nullptr);
    CHECK(rtps::T10aHarness::nextParticipantId(domain) == 1);
  }
  setFixtureIp(0x0a000003U);
  {
    rtps::Domain domain;
    auto *part = domain.createParticipant();
    CHECK(part && rtps::T10aHarness::applied(*part) == 0);
    CHECK(rtps::T10aHarness::project(*part, ip3.addr));
    auto *before = domain.createWriter(*part, "birth-before", "type", true);
    CHECK(before && rtps::T10aHarness::writerCount(*part) == 4);
    CHECK(before->m_attributes.unicastLocator.address == rtps::getUserUnicastLocator(part->m_participantId, {{10,0,0,3}}).address);
    // Keep the transport at .3 while projection prepares and commits .6; the
    // birth must select the completed applied snapshot rather than current IP.
    // Pause the real projection after all fallible preparation and while it
    // owns the SEDP mutex. Registration must block on that active transaction,
    // not on a separately held/no-op mutex.
    CHECK(rtps::T10aHarness::applied(*part) == ip3.addr);
    const auto pubBeforeBirth = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
    pause_projection_commit.store(true, std::memory_order_release);
    std::atomic<bool> projectionDone{false};
    bool projectionResult = false;
    std::thread projection([&]() {
      projectionResult = rtps::T10aHarness::project(*part, ip6.addr);
      projectionDone.store(true, std::memory_order_release);
    });
    for (int i = 0; i < 1000000 && !projection_commit_prepared.load(std::memory_order_acquire); ++i)
      std::this_thread::yield();
    CHECK(projection_commit_prepared.load(std::memory_order_acquire));
    std::atomic<bool> birthStarted{false}, birthDone{false};
    rtps::Writer *after = nullptr;
    std::thread birth([&]() {
      birthStarted.store(true, std::memory_order_release);
      after = domain.createWriter(*part, "birth-after", "type", true);
      birthDone.store(true, std::memory_order_release);
    });
    for (int i = 0; i < 1000000 && !birthStarted.load(std::memory_order_acquire); ++i)
      std::this_thread::yield();
    CHECK(birthStarted.load(std::memory_order_acquire));
    for (int i = 0; i < 1000; ++i) std::this_thread::yield();
    CHECK(!projectionDone.load(std::memory_order_acquire));
    CHECK(!birthDone.load(std::memory_order_acquire));
    CHECK(rtps::T10aHarness::writerCount(*part) == 4);
    const auto pubStillBeforeBirth = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
    CHECK(sameSn(pubBeforeBirth.max, pubStillBeforeBirth.max));
    release_projection_commit.store(true, std::memory_order_release);
    projection.join();
    birth.join();
    pause_projection_commit.store(false, std::memory_order_release);
    CHECK(projectionDone.load(std::memory_order_acquire) && projectionResult);
    CHECK(birthDone.load(std::memory_order_acquire) && after);
    CHECK(rtps::T10aHarness::applied(*part) == ip6.addr);
    CHECK(rtps::T10aHarness::writerCount(*part) == 5);
    CHECK(rtps::T10aHarness::hasPublishedWriter(*part, after));
    CHECK(after->m_attributes.unicastLocator.address == rtps::getUserUnicastLocator(part->m_participantId, {{10,0,0,6}}).address);
    const auto pubAfterBirth = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
    CHECK(pubBeforeBirth.max < pubAfterBirth.max);
    std::array<uint8_t, 600> birthRecord{};
    uint16_t birthRecordLength = 0;
    CHECK(rtps::T10aHarness::payloadAt(rtps::T10aHarness::sedpPubWriter(*part), pubAfterBirth.max, birthRecord, birthRecordLength));
    CHECK(birthRecordLength > 0);
    ucdrBuffer birthBuffer;
    ucdr_init_buffer(&birthBuffer, birthRecord.data(), birthRecordLength);
    rtps::TopicData admittedBirth;
    CHECK(admittedBirth.readFromUcdrBuffer(birthBuffer));
    CHECK(std::strcmp(admittedBirth.topicName, "birth-after") == 0);
    CHECK(admittedBirth.unicastLocator.address == after->m_attributes.unicastLocator.address);

    // Third user writer is rejected before history/count publication.
    const auto pub = pubAfterBirth;
    const auto sub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
    const auto refs = rtps::T10aHarness::historyRefs(*part);
    CHECK(domain.createWriter(*part, "birth-third", "type", true) == nullptr);
    CHECK(rtps::T10aHarness::writerCount(*part) == 5);
    const auto pubAfter = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
    const auto subAfter = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
    const auto refsAfter = rtps::T10aHarness::historyRefs(*part);
    CHECK(sameSn(pub.max,pubAfter.max) && sameSn(pub.min,pubAfter.min) && pub.latest == pubAfter.latest);
    CHECK(sameSn(sub.max,subAfter.max) && sameSn(sub.min,subAfter.min) && sub.latest == subAfter.latest);
    CHECK(refs.count == refsAfter.count && std::memcmp(refs.nodes,refsAfter.nodes,refs.count*sizeof(refs.nodes[0])) == 0);
    CHECK(std::memcmp(refs.refs,refsAfter.refs,refs.count*sizeof(refs.refs[0])) == 0);
  }
  std::puts("T10c_STARTUP_BIRTH_PASS empty_projection=1 zero_initial_rejected=1 failed_slot_nonreuse=1 birth_before_after_projection=1 sedp_mutex=1 third_writer_rejected=1");
}

static void test_t10c1_runtime_birth_failures() {
  setFixtureIp(0x0a000003U);
  int ucdrPositions[2][UCDR_KIND_COUNT]{};
  int allocPositions[2]{}, takePositions[2]{};
  rtps::T10aHarness::PbufPoolUse successfulInitPoolDelta[2]{};
  // Measure fallible preparation points separately on real writer and reader
  // birth, then inject each point in a fresh Domain/Participant.
  for (int endpoint = 0; endpoint < 2; ++endpoint) {
    rtps::Domain domain;
    auto *part = domain.createParticipant();
    CHECK(part && rtps::T10aHarness::initialized(*part));
    const auto poolBeforeBirth = rtps::T10aHarness::pbufPoolUse();
    resetFailures();
    auto *created = endpoint == 0
        ? static_cast<void *>(domain.createWriter(*part, "birth-measure-w", "type", true))
        : static_cast<void *>(domain.createReader(*part, "birth-measure-r", "type", true));
    CHECK(created != nullptr);
    std::memcpy(ucdrPositions[endpoint], ucdr_calls, sizeof(ucdr_calls));
    allocPositions[endpoint] = pbuf_alloc_calls;
    takePositions[endpoint] = pbuf_take_calls;
    const auto poolAfterBirth = rtps::T10aHarness::pbufPoolUse();
    successfulInitPoolDelta[endpoint] = {poolAfterBirth.pbuf - poolBeforeBirth.pbuf,
                                         poolAfterBirth.pool - poolBeforeBirth.pool};
  }

  int cases = 0;
  for (int endpoint = 0; endpoint < 2; ++endpoint) {
    for (int kind = 0; kind < UCDR_KIND_COUNT; ++kind) {
      for (int n = 1; n <= ucdrPositions[endpoint][kind]; ++n) {
        rtps::Domain domain;
        auto *part = domain.createParticipant();
        CHECK(part && rtps::T10aHarness::initialized(*part));
        const auto writers = rtps::T10aHarness::writerCount(*part);
        const auto readers = rtps::T10aHarness::readerCount(*part);
        const auto domainWriters = rtps::T10aHarness::domainWriterCount(domain);
        const auto domainReaders = rtps::T10aHarness::domainReaderCount(domain);
        const auto pub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
        const auto sub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
        const auto refs = rtps::T10aHarness::historyRefs(*part);
        const auto applied = rtps::T10aHarness::applied(*part);
        const auto writerPointers = rtps::T10aHarness::writerPointers(*part);
        const auto readerPointers = rtps::T10aHarness::readerPointers(*part);
        const auto pools = rtps::T10aHarness::pbufPoolUse();
        resetFailures(); fail_ucdr_at[kind] = n;
        auto *result = endpoint == 0
            ? static_cast<void *>(domain.createWriter(*part, "birth-fail-w", "type", true))
            : static_cast<void *>(domain.createReader(*part, "birth-fail-r", "type", true));
        CHECK(result == nullptr && ucdr_calls[kind] >= n);
        CHECK(rtps::T10aHarness::writerCount(*part) == writers && rtps::T10aHarness::readerCount(*part) == readers);
        CHECK(rtps::T10aHarness::writerPointers(*part) == writerPointers && rtps::T10aHarness::readerPointers(*part) == readerPointers);
        CHECK(rtps::T10aHarness::domainWriterCount(domain) == domainWriters + (endpoint == 0 ? 1 : 0));
        CHECK(rtps::T10aHarness::domainReaderCount(domain) == domainReaders + (endpoint == 1 ? 1 : 0));
        CHECK(rtps::T10aHarness::applied(*part) == applied);
        const auto pubAfter = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
        const auto subAfter = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
        CHECK(sameSn(pub.min,pubAfter.min) && sameSn(pub.max,pubAfter.max) && pub.latest == pubAfter.latest);
        CHECK(sameSn(sub.min,subAfter.min) && sameSn(sub.max,subAfter.max) && sub.latest == subAfter.latest);
        const auto refsAfter = rtps::T10aHarness::historyRefs(*part);
        CHECK(refs.count == refsAfter.count && std::memcmp(refs.nodes,refsAfter.nodes,refs.count*sizeof(refs.nodes[0])) == 0);
        CHECK(refs.count == refsAfter.count && std::memcmp(refs.refs,refsAfter.refs,refs.count*sizeof(refs.refs[0])) == 0);
        const auto poolsAfter = rtps::T10aHarness::pbufPoolUse();
        CHECK(pools.pbuf == poolsAfter.pbuf && pools.pool == poolsAfter.pool);
        ++cases;
      }
    }
    for (int failureKind = 0; failureKind < 2; ++failureKind) {
      const int positions = failureKind == 0 ? allocPositions[endpoint] : takePositions[endpoint];
      for (int n = 1; n <= positions; ++n) {
        rtps::Domain domain;
        auto *part = domain.createParticipant();
        CHECK(part && rtps::T10aHarness::initialized(*part));
        const auto writers = rtps::T10aHarness::writerCount(*part);
        const auto readers = rtps::T10aHarness::readerCount(*part);
        const auto domainWriters = rtps::T10aHarness::domainWriterCount(domain);
        const auto domainReaders = rtps::T10aHarness::domainReaderCount(domain);
        const auto pub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
        const auto sub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
        const auto refs = rtps::T10aHarness::historyRefs(*part);
        const auto applied = rtps::T10aHarness::applied(*part);
        const auto writerPointers = rtps::T10aHarness::writerPointers(*part);
        const auto readerPointers = rtps::T10aHarness::readerPointers(*part);
        const auto pools = rtps::T10aHarness::pbufPoolUse();
        resetFailures();
        if (failureKind == 0) fail_pbuf_alloc_at = n; else fail_pbuf_take_at = n;
        auto *result = endpoint == 0
            ? static_cast<void *>(domain.createWriter(*part, "birth-fail-w", "type", true))
            : static_cast<void *>(domain.createReader(*part, "birth-fail-r", "type", true));
        CHECK(result == nullptr);
        CHECK((failureKind == 0 ? pbuf_alloc_calls : pbuf_take_calls) == n);
        CHECK(rtps::T10aHarness::writerCount(*part) == writers && rtps::T10aHarness::readerCount(*part) == readers);
        CHECK(rtps::T10aHarness::writerPointers(*part) == writerPointers && rtps::T10aHarness::readerPointers(*part) == readerPointers);
        CHECK(rtps::T10aHarness::domainWriterCount(domain) == domainWriters + (endpoint == 0 ? 1 : 0));
        CHECK(rtps::T10aHarness::domainReaderCount(domain) == domainReaders + (endpoint == 1 ? 1 : 0));
        CHECK(rtps::T10aHarness::applied(*part) == applied);
        const auto pubAfter = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
        const auto subAfter = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
        CHECK(sameSn(pub.min,pubAfter.min) && sameSn(pub.max,pubAfter.max) && pub.latest == pubAfter.latest);
        CHECK(sameSn(sub.min,subAfter.min) && sameSn(sub.max,subAfter.max) && sub.latest == subAfter.latest);
        const auto refsAfter = rtps::T10aHarness::historyRefs(*part);
        CHECK(refs.count == refsAfter.count && std::memcmp(refs.nodes,refsAfter.nodes,refs.count*sizeof(refs.nodes[0])) == 0);
        CHECK(refs.count == refsAfter.count && std::memcmp(refs.refs,refsAfter.refs,refs.count*sizeof(refs.refs[0])) == 0);
        const auto poolsAfter = rtps::T10aHarness::pbufPoolUse();
        CHECK(pools.pbuf == poolsAfter.pbuf && pools.pool == poolsAfter.pool);
        ++cases;
      }
    }
  }
  std::printf("T10c1_RUNTIME_BIRTH_FAILURES_PASS cases=%d writer_ucdr=%d reader_ucdr=%d writer_alloc=%d reader_alloc=%d writer_append=%d reader_append=%d pool_slots_consumed_after_successful_init=pbuf:%u,pool:%u\n",
      cases, [&](){int n=0;for(int x:ucdrPositions[0])n+=x;return n;}(),
      [&](){int n=0;for(int x:ucdrPositions[1])n+=x;return n;}(), allocPositions[0], allocPositions[1], takePositions[0], takePositions[1],
      successfulInitPoolDelta[0].pbuf + successfulInitPoolDelta[1].pbuf,
      successfulInitPoolDelta[0].pool + successfulInitPoolDelta[1].pool);
}

static void test_t10c_typed_builtin_failures() {
  static const char *names[] = {"SPDPWriter", "SPDPReader", "SEDPPublicationsReader",
                                "SEDPSubscriptionsReader", "SEDPPublicationsWriter",
                                "SEDPSubscriptionsWriter"};
  for (int failed = 1; failed <= 6; ++failed) {
    setFixtureIp(0x0a000003U);
    rtps::Domain domain;
    fail_sys_mutex_new_at = failed;
    sys_mutex_new_calls = 0;
    sys_mutex_failure_observed = false;
    sys_mutex_injection_active = true;
    rtps::Participant *part = domain.createParticipant();
    sys_mutex_injection_active = false;
    CHECK(part == nullptr);
    CHECK(sys_mutex_failure_observed && sys_mutex_new_calls == failed);
    auto *slot = rtps::T10aHarness::participantSlot(domain, 0);
    CHECK(!rtps::T10aHarness::hasBuiltin(*slot));
    CHECK(rtps::T10aHarness::writerCount(*slot) == 0);
    CHECK(rtps::T10aHarness::readerCount(*slot) == 0);
    CHECK(!rtps::T10aHarness::spdpRunning(*slot));
    slot->getSPDPAgent().start();
    CHECK(!rtps::T10aHarness::spdpRunning(*slot));
    CHECK(rtps::T10aHarness::spdpWriterInitialized(domain, 0) == (failed > 1));
    CHECK(rtps::T10aHarness::spdpReaderInitialized(domain, 0) == (failed > 2));
    CHECK(rtps::T10aHarness::statefulReaderInitialized(domain, 0) == (failed > 3));
    CHECK(rtps::T10aHarness::statefulReaderInitialized(domain, 1) == (failed > 4));
    CHECK(rtps::T10aHarness::statefulWriterInitialized(domain, 0) == (failed > 5));
    CHECK(rtps::T10aHarness::statefulWriterInitialized(domain, 1) == false);
    CHECK(rtps::T10aHarness::domainStatelessWriterCount(domain) == (failed > 1 ? 1 : 0));
    CHECK(rtps::T10aHarness::domainStatelessReaderCount(domain) == (failed > 2 ? 1 : 0));
    CHECK(rtps::T10aHarness::domainWriterCount(domain) == (failed > 5 ? 1 : 0));
    CHECK(rtps::T10aHarness::domainReaderCount(domain) == (failed > 3 ? 1 : 0) + (failed > 4 ? 1 : 0));
    CHECK(rtps::T10aHarness::nextParticipantId(domain) == 1);
    // MAX_NUM_PARTICIPANTS is one in this configured target; the retired slot
    // cannot be reinitialized, and its successful endpoint slots remain counted.
    CHECK(domain.createParticipant() == nullptr);
    CHECK(rtps::T10aHarness::nextParticipantId(domain) == 1);
    CHECK(!domain.completeInit());
    CHECK(!rtps::T10aHarness::hasBuiltin(*slot));
    CHECK(!rtps::T10aHarness::spdpRunning(*slot));
    std::printf("T10c_TYPED_INIT_FAILURE case=%s failed_mutex_call=%d complete_init=1 no_builtin_publication=1 spdp_not_started=1 retired_counts=1\n", names[failed - 1], failed);
  }
  std::puts("T10c_TYPED_INIT_FAILURES_PASS cases=6");

  // SPDP itself can initialize before SEDP initialization fails. That partially
  // initialized agent is still not a published builtin participant.
  setFixtureIp(0x0a000003U);
  rtps::Domain laterFailureDomain;
  fail_sys_mutex_new_at = 8;
  sys_mutex_new_calls = 0;
  sys_mutex_failure_observed = false;
  sys_mutex_injection_active = true;
  CHECK(laterFailureDomain.createParticipant() == nullptr);
  sys_mutex_injection_active = false;
  CHECK(sys_mutex_failure_observed && sys_mutex_new_calls == 8);
  auto *laterFailureSlot = rtps::T10aHarness::participantSlot(laterFailureDomain, 0);
  CHECK(rtps::T10aHarness::spdpInitialized(*laterFailureSlot));
  CHECK(!rtps::T10aHarness::hasBuiltin(*laterFailureSlot));
  laterFailureSlot->getSPDPAgent().start();
  CHECK(!rtps::T10aHarness::spdpRunning(*laterFailureSlot));
  CHECK(!laterFailureDomain.completeInit());
  CHECK(!rtps::T10aHarness::hasBuiltin(*laterFailureSlot));
  CHECK(!rtps::T10aHarness::spdpRunning(*laterFailureSlot));
  std::puts("T10c_LATE_AGENT_FAILURE_PASS spdp_initialized=1 sedp_mutex_failure=1 builtin_publication=0 direct_start_refused=1 complete_init_refused=1");
}

static void test_t10a_smoke() {
  rtps::Domain domain;
  rtps::Participant *part = domain.createParticipant();
  CHECK(part != nullptr);
  CHECK(rtps::T10aHarness::initialized(*part));
  CHECK(rtps::T10aHarness::applied(*part) == 0);

  // Empty user endpoint projection goes through SEDP prepare + real SPDP
  // serialization, pbuf allocation, typed writer admission, and applied-last.
  ip4_addr_t current{};
  IP4_ADDR(&current, 10, 0, 0, 6);
  const uint32_t target = current.addr;
  CHECK(target != 0);
  CHECK(rtps::T10aHarness::project(*part, target));
  CHECK(rtps::T10aHarness::applied(*part) == target);
  const rtps::CacheChange *latest = rtps::T10aHarness::latestSpdp(*part);
  CHECK(latest != nullptr);
  CHECK(latest->kind == rtps::ChangeKind_t::ALIVE);
  CHECK(latest->data.isValid());
  CHECK(latest->data.spaceUsed() != 0);
  CHECK(latest->sequenceNumber == rtps::T10aHarness::latestSpdpSequence(*part));
  CHECK(rtps::T10aHarness::project(*part, target)); // equal-IP no-op
  CHECK(rtps::T10aHarness::applied(*part) == target);
  CHECK(domain.completeInit());
  CHECK(rtps::T10aHarness::spdpRunning(*part));
  std::puts("T10a_SMOKE_PASS real_participant=1 typed_builtins=1 zero_user_projection=1 real_spdp_history=1 applied_last=1 healthy_start=1");
}

static void test_t10c2a_participant_locks() {
  setFixtureIp(0x0a000003U);
  rtps::Domain domain;
  auto *part = domain.createParticipant();
  CHECK(part != nullptr && rtps::T10aHarness::initialized(*part));
  auto *writer = domain.createWriter(*part, "locks-writer", "type", true);
  auto *reader = domain.createReader(*part, "locks-reader", "type", true);
  CHECK(writer != nullptr && reader != nullptr);
  CHECK(rtps::T10aHarness::endpointSnapshotValid(*part));

  rtps::GuidPrefix_t livePrefix{};
  livePrefix.id[0] = 0x31;
  rtps::GuidPrefix_t expiredPrefixA{};
  expiredPrefixA.id[0] = 0x41;
  rtps::GuidPrefix_t expiredPrefixB{};
  expiredPrefixB.id[0] = 0x42;
  rtps::ParticipantProxyData live(rtps::Guid_t{livePrefix, rtps::ENTITYID_UNKNOWN});
  rtps::ParticipantProxyData expiredA(rtps::Guid_t{expiredPrefixA, rtps::ENTITYID_UNKNOWN});
  rtps::ParticipantProxyData expiredB(rtps::Guid_t{expiredPrefixB, rtps::ENTITYID_UNKNOWN});
  expiredA.m_leaseDuration = {0, 0};
  expiredB.m_leaseDuration = {0, 0};
  CHECK(part->addNewRemoteParticipant(live));
  CHECK(part->getRemoteParticipantCount() == 1);

  std::atomic<bool> start{false};
  std::atomic<int> iterations{0};
  std::atomic<bool> identityValid{true};
  std::thread accessor([&] {
    while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
    for (int i = 0; i < 2000; ++i) {
      rtps::ParticipantProxyData copied;
      if (!part->copyRemoteParticipant(livePrefix, copied) ||
          !(copied.m_guid.prefix == livePrefix) ||
          !part->hasRemoteParticipant(livePrefix) ||
          part->getRemoteParticipantCount() != 1 ||
          part->getWriter(writer->m_attributes.endpointGuid.entityId) != writer ||
          part->getReader(reader->m_attributes.endpointGuid.entityId) != reader ||
          part->getMatchingWriter(writer->m_attributes) != writer ||
          part->getMatchingReader(reader->m_attributes) != reader ||
          !rtps::T10aHarness::endpointSnapshotValid(*part))
        identityValid.store(false, std::memory_order_relaxed);
      ++iterations;
    }
  });
  start.store(true, std::memory_order_release);
  for (int i = 0; i < 2000; ++i) {
    part->addHeartbeat(livePrefix);
    part->refreshRemoteParticipantLiveliness(livePrefix);
    (void)part->getRemoteParticipantCount();
    CHECK(rtps::T10aHarness::endpointSnapshotValid(*part));
  }
  accessor.join();
  CHECK(iterations == 2000 && identityValid.load());
  std::puts("T10c2a_ACCESSOR_CONTENTION_PASS real_threads=1 guarded_get_match_count=1 copied_remote_identity=1 stable_endpoint_snapshot=1 iterations=2000");

  CHECK(part->addNewRemoteParticipant(expiredA));
  CHECK(part->addNewRemoteParticipant(expiredB));
  CHECK(part->getRemoteParticipantCount() == 3);
  // Each expired prefix is snapshotted under Participant and then removed after
  // that guard is released; removal enters SEDP only after the release.
  CHECK(part->checkAndResetHeartbeats());
  CHECK(part->getRemoteParticipantCount() == 1);
  CHECK(part->hasRemoteParticipant(livePrefix));
  CHECK(!part->hasRemoteParticipant(expiredPrefixA));
  CHECK(!part->hasRemoteParticipant(expiredPrefixB));
  std::puts("T10c2a_EXPIRED_PREFIX_PASS expired_prefixes=2 remaining_live=1 participant_released_before_sedp=1");
}

int main(int argc, char **argv) {
  CHECK(argc == 2);
  CHECK(std::strcmp(argv[1], "T10a") == 0 || std::strcmp(argv[1], "T10b") == 0 || std::strcmp(argv[1], "T10b1") == 0 || std::strcmp(argv[1], "T10b2") == 0 || std::strcmp(argv[1], "T10b3") == 0 || std::strcmp(argv[1], "T10c") == 0 || std::strcmp(argv[1], "T10c1") == 0 || std::strcmp(argv[1], "T10c2a") == 0 || std::strcmp(argv[1], "T10c6") == 0);
  fixture_init();
  if (std::strcmp(argv[1], "T10a") == 0) test_t10a_smoke();
  else if (std::strcmp(argv[1], "T10b1") == 0) test_t10b1_users();
  else if (std::strcmp(argv[1], "T10b3") == 0) test_t10b3();
  else if (std::strcmp(argv[1], "T10c") == 0) test_t10c_startup_birth();
  else if (std::strcmp(argv[1], "T10c1") == 0) test_t10c1_runtime_birth_failures();
  else if (std::strcmp(argv[1], "T10c6") == 0) test_t10c_typed_builtin_failures();
  else if (std::strcmp(argv[1], "T10c2a") == 0) test_t10c2a_participant_locks();
  else test_t10b2_preparation_positions();
  return 0;
}
