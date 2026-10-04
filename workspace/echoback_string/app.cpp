#include "mros2.h"
#include "std_msgs/msg/string.hpp"

#include "cmsis_os.h"
#include "netif.h"
#include "netif_wasm_add.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

extern "C" uint32_t cr_host_probe_get(void);
extern "C" void cr_host_probe_set(uint32_t value);

static volatile uint32_t cr_guest_probe = 0;


void userCallback(std_msgs::msg::String *msg)
{
  printf("subscribed msg: '%s'\r\n", msg->data.c_str());
}

int main(int argc, char* argv[])
{
  netif_wasm_add(NETIF_IPADDR, NETIF_NETMASK);

  osKernelStart();

  printf("mros2-posix start!\r\n");
  printf("app name: echoback_string\r\n");
  mros2::init(0, NULL);
  MROS2_DEBUG("mROS 2 initialization is completed\r\n");

  mros2::Node node = mros2::Node::create_node("mros2_node1");
  mros2::Publisher pub = node.create_publisher<std_msgs::msg::String>("to_linux", 10);
  mros2::Subscriber sub = node.create_subscription<std_msgs::msg::String>("to_stm", 10, userCallback);

  osDelay(100);
  MROS2_INFO("ready to pub/sub message\r\n");

  auto count = 0;
  while (1) {
    const auto id = count;
    const uint32_t guest_before = cr_guest_probe;
    const uint32_t host_before = cr_host_probe_get();
    printf("[CR-STATE] loop id=%d guest_before=0x%08x host_before=0x%08x\r\n",
           id, guest_before, host_before);

    const uint32_t sentinel = 0xA5000000u | (static_cast<uint32_t>(id) & 0xffffu);
    cr_guest_probe = sentinel;
    cr_host_probe_set(sentinel);

    auto msg = std_msgs::msg::String();
    msg.data = "Hello from mros2-posix onto Linux: " + std::to_string(count++);
    printf("publishing msg: '%s'\r\n", msg.data.c_str());
    pub.publish(msg);
    printf("[CR-STATE] armed id=%d value=0x%08x\r\n", id, sentinel);
    osDelay(1000);
  }

  mros2::spin();
  return 0;
}
