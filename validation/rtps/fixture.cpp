#include "rtps/storages/PBufWrapper.h"
#include "ucdr/microcdr.h"
extern "C" {
#include "cmsis_os.h"
#include "lwip/mem.h"
#include "lwip/memp.h"
#include "lwip/pbuf.h"
#include "lwip/sys.h"
#include "lwipopts.h"
}
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <type_traits>

#define CHECK(expr) do { if (!(expr)) { std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #expr); std::abort(); } } while (0)

static void fixture_init() {
  CHECK(osKernelStart() == osOK);
  sys_init();
  mem_init();
  memp_init();
  pbuf_init();
}

static void test_t01() {
  // Actual production core mutex and project OS adapter, not test replacements.
  CHECK(sys_trylock_tcpip_core() == 0);
  CHECK(sys_trylock_tcpip_core() == EBUSY);
  sys_unlock_tcpip_core();
  sys_mutex_t mutex{};
  CHECK(sys_mutex_new(&mutex) == ERR_OK);
  sys_mutex_lock(&mutex);
  sys_mutex_unlock(&mutex);
  sys_mutex_free(&mutex);

  const std::array<uint8_t, 6> bytes{{0x01, 0x7f, 0x80, 0xff, 0x33, 0x66}};
  {
    rtps::PBufWrapper prepared;
    CHECK(prepared.reserve(bytes.size()));
    CHECK(prepared.isValid());
    CHECK(prepared.append(bytes.data(), bytes.size()));
    CHECK(prepared.spaceUsed() == bytes.size());
    std::array<uint8_t, 6> actual{};
    CHECK(pbuf_copy_partial(prepared.firstElement, actual.data(), actual.size(), 0) == actual.size());
    CHECK(actual == bytes);
    static_assert(std::is_nothrow_move_constructible<rtps::PBufWrapper>::value, "owned payload move must be noexcept");
    rtps::PBufWrapper moved(std::move(prepared));
    CHECK(!prepared.isValid());
    CHECK(moved.isValid() && moved.spaceUsed() == bytes.size());
  } // Actual PBUF_POOL payload is freed by the production destructor.
  // Repeated allocation/free exercises pool reuse, not a fake pbuf adapter.
  for (int i = 0; i < 256; ++i) {
    rtps::PBufWrapper reused;
    CHECK(reused.reserve(bytes.size()));
    CHECK(reused.append(bytes.data(), bytes.size()));
  }

  uint8_t output[4]{};
  ucdrBuffer cdr{};
  ucdr_init_buffer(&cdr, output, sizeof(output));
  CHECK(ucdr_serialize_uint32_t(&cdr, 0x12345678));
  CHECK(ucdr_buffer_length(&cdr) == sizeof(output));
  CHECK(!ucdr_buffer_has_error(&cdr));
  CHECK(!ucdr_serialize_uint8_t(&cdr, 0xff));
  CHECK(ucdr_buffer_has_error(&cdr));
  // Error stays sticky; resetting the serializer is explicit, not automatic.
  CHECK(!ucdr_serialize_uint8_t(&cdr, 0x00));
  CHECK(ucdr_buffer_has_error(&cdr));
  std::puts("T01_PASS actual_pbuf=1 actual_ucdr=1 actual_core_mutex=1 actual_sys_mutex=1");
}

int main(int argc, char** argv) {
  CHECK(argc == 2);
  fixture_init();
  if (std::strcmp(argv[1], "T01") == 0) test_t01();
  else { std::fprintf(stderr, "Unknown/unimplemented task: %s\n", argv[1]); return 2; }
  return 0;
}
