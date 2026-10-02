#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <type_traits>
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
static int probe_fd = -1;
static int fail_pbuf_alloc_at = 0, pbuf_alloc_calls = 0;
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
  return __real_pbuf_alloc(layer, length, type);
}
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
  const auto locatorWriter = userWriter->m_attributes.unicastLocator.address;
  const auto locatorReader = userReader->m_attributes.unicastLocator.address;
  const auto baselineSpdpBytes = rtps::T10aHarness::latestBytes(*part);
  int cases = 0;
  const auto checkState = [&]() {
    CHECK(rtps::T10aHarness::applied(*part) == ip3.addr);
    CHECK(userWriter->m_attributes.unicastLocator.address == locatorWriter);
    CHECK(userReader->m_attributes.unicastLocator.address == locatorReader);
    CHECK(rtps::T10aHarness::output(*part) == baselineOutput);
    CHECK(rtps::T10aHarness::latestBytes(*part) == baselineSpdpBytes);
    const auto spdp = rtps::T10aHarness::writerView(rtps::T10aHarness::spdpWriter(*part));
    const auto pub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpPubWriter(*part));
    const auto sub = rtps::T10aHarness::writerView(rtps::T10aHarness::sedpSubWriter(*part));
    CHECK(sameSn(spdp.min, baselineSpdp.min) && sameSn(spdp.max, baselineSpdp.max) && sameSn(spdp.cursor, baselineSpdp.cursor) && spdp.latest == baselineSpdp.latest && spdp.length == baselineSpdp.length);
    CHECK(sameSn(pub.min, baselinePub.min) && sameSn(pub.max, baselinePub.max) && sameSn(pub.cursor, baselinePub.cursor) && pub.latest == baselinePub.latest && pub.length == baselinePub.length);
    CHECK(sameSn(sub.min, baselineSub.min) && sameSn(sub.max, baselineSub.max) && sameSn(sub.cursor, baselineSub.cursor) && sub.latest == baselineSub.latest && sub.length == baselineSub.length);
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
  std::puts("T10a_SMOKE_PASS real_participant=1 typed_builtins=1 zero_user_projection=1 real_spdp_history=1 applied_last=1");
}

int main(int argc, char **argv) {
  CHECK(argc == 2);
  CHECK(std::strcmp(argv[1], "T10a") == 0 || std::strcmp(argv[1], "T10b") == 0 || std::strcmp(argv[1], "T10b1") == 0 || std::strcmp(argv[1], "T10b2") == 0);
  fixture_init();
  if (std::strcmp(argv[1], "T10a") == 0) test_t10a_smoke();
  else if (std::strcmp(argv[1], "T10b1") == 0) test_t10b1_users();
  else test_t10b2_preparation_positions();
  return 0;
}
