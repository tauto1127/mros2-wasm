#include <array>
#include <cstdio>
#include <cstdlib>

#include "rtps/communication/UdpDriver.h"
#include "lwip/netif.h"

extern "C" {
struct netif *netif_default = nullptr;
static unsigned core_locks = 0;
void sys_lock_tcpip_core(void) { ++core_locks; }
void sys_unlock_tcpip_core(void) { if (core_locks == 0) std::abort(); --core_locks; }
}

#define REQUIRE(expr) do { if (!(expr)) { std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #expr); return 1; } } while (0)

int main() {
  std::array<uint8_t, 4> address{{9, 8, 7, 6}};
  REQUIRE(!rtps::UdpDriver::getLocalIpAddress(address));
  REQUIRE((address == std::array<uint8_t, 4>{{9, 8, 7, 6}}));
  REQUIRE(core_locks == 0);

  struct netif iface{};
  IP4_ADDR(&iface.ip_addr, 203, 17, 91, 6);
  IP4_ADDR(&iface.netmask, 255, 255, 240, 0);
  netif_default = &iface;
  REQUIRE(rtps::UdpDriver::getLocalIpAddress(address));
  REQUIRE((address == std::array<uint8_t, 4>{{203, 17, 91, 6}}));
  ip4_addr_t same_subnet{};
  ip4_addr_t other_subnet{};
  IP4_ADDR(&same_subnet, 203, 17, 95, 240);
  IP4_ADDR(&other_subnet, 203, 17, 107, 240);
  REQUIRE(rtps::UdpDriver::isSameSubnet(same_subnet));
  REQUIRE(!rtps::UdpDriver::isSameSubnet(other_subnet));
  REQUIRE(core_locks == 0);
  std::puts("T10c2b_NATIVE_IP_MAPPING_PASS ip=203.17.91.6 mask=255.255.240.0 network_order_octets=1 invalid_netif_rejected=1 core_lock_balanced=1");
  return 0;
}
