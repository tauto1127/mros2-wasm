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
static int fail_ucdr_serialize_at = 0, ucdr_serialize_calls = 0;
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
extern "C" bool __real_ucdr_serialize_array_uint8_t(ucdrBuffer *, const uint8_t *, uint32_t);
extern "C" bool __wrap_ucdr_serialize_array_uint8_t(ucdrBuffer *buffer, const uint8_t *data, uint32_t length) {
  if (++ucdr_serialize_calls == fail_ucdr_serialize_at) { buffer->error = true; return false; }
  return __real_ucdr_serialize_array_uint8_t(buffer, data, length);
}
static void resetFailures() {
  fail_pbuf_alloc_at = fail_pbuf_take_at = fail_ucdr_serialize_at = 0;
  pbuf_alloc_calls = pbuf_take_calls = ucdr_serialize_calls = 0;
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

static void test_t10b_preparation_failures() {
  rtps::Domain domain;
  rtps::Participant *part = domain.createParticipant();
  CHECK(part != nullptr && rtps::T10aHarness::initialized(*part));
  ip4_addr_t target{};
  IP4_ADDR(&target, 10, 0, 0, 8);
  const uint32_t address = target.addr;
  ip4_addr_t initial{};
  IP4_ADDR(&initial, 10, 0, 0, 6);
  CHECK(rtps::T10aHarness::project(*part, initial.addr));
  const auto checkFailureAtomic = [&](const char *name, int &failAt) {
    const auto oldOutput = rtps::T10aHarness::output(*part);
    const auto oldBytes = rtps::T10aHarness::latestBytes(*part);
    const auto oldSequence = rtps::T10aHarness::latestSpdpSequence(*part);
    resetFailures();
    failAt = 1;
    CHECK(!rtps::T10aHarness::project(*part, address));
    resetFailures();
    CHECK(rtps::T10aHarness::applied(*part) == initial.addr);
    CHECK(rtps::T10aHarness::latestSpdpSequence(*part) == oldSequence);
    CHECK(rtps::T10aHarness::output(*part) == oldOutput);
    CHECK(rtps::T10aHarness::latestBytes(*part) == oldBytes);
    std::printf("T10b_PREP_FAIL_PASS stage=%s applied_unchanged=1 spdp_history_unchanged=1 output_unchanged=1\\n", name);
  };
  checkFailureAtomic("ucdr_serialize", fail_ucdr_serialize_at);
  checkFailureAtomic("pbuf_alloc", fail_pbuf_alloc_at);
  checkFailureAtomic("pbuf_take_at", fail_pbuf_take_at);
  resetFailures();
  CHECK(rtps::T10aHarness::project(*part, address));
  CHECK(rtps::T10aHarness::applied(*part) == address);
  CHECK(rtps::T10aHarness::project(*part, address));
  std::puts("T10b_BASELINE_PASS appliedA_to_B_retry=1 equal_noop=1");
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
  CHECK(std::strcmp(argv[1], "T10a") == 0 || std::strcmp(argv[1], "T10b") == 0);
  fixture_init();
  if (std::strcmp(argv[1], "T10a") == 0) test_t10a_smoke();
  else test_t10b_preparation_failures();
  return 0;
}
