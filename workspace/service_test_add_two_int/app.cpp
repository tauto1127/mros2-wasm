#include "mros2.h"
#include "std_msgs/msg/string.hpp"
#include "std_msgs/msg/int64.hpp"

#include "cmsis_os.h"
#include "netif.h"
#include "netif_wasm_add.h"

#include <stdio.h>
#include <string.h>
#include "service_msgs/msg/add_two_int_client.hpp"

#include <condition_variable>

void userCallback(std_msgs::msg::Int64 *msg)
{
  // printf("subscribed msg: calculation sum:'%ld'\r\n", msg->data);
}

int main(int argc, char *argv[])
{
  netif_wasm_add(NETIF_IPADDR, NETIF_NETMASK);

  osKernelStart();

  printf("mros2-wasm start!\r\n");
  printf("app name: service_test_add_two_int\r\n");
  mros2::init(0, NULL);
  MROS2_DEBUG("mROS 2 initialization is completed\r\n");

  mros2::Node node = mros2::Node::create_node("mros2_node");

  mros2::Publisher pub = node.create_client<service_msgs::msg::add_two_int_client>("add_two_ints", 10);

  mros2::wait_service(1);

  MROS2_INFO("ready to pub/sub message\r\n");

  auto start_time = std::chrono::high_resolution_clock::now();
  while (1)
  {
    auto msg = service_msgs::msg::add_two_int_client();
    msg.a = 3;
    msg.b = 3;

    printf("publishing msg: '%d' + '%d'\r\n", msg.a, msg.b);

    auto response = pub.async_send_request(msg);

    printf("future.get() start\r\n");
    mros2::spin_until_future_complete(node, &response);

    printf("future.get() return\r\n");
    std_msgs::msg::Int64 msg_test;
    const std::vector<uint8_t> response_frame = response.get();
    if (response_frame.size() < 4)
    {
      printf("invalid service response: size=%zu\r\n", response_frame.size());
      break;
    }
    msg_test.copyFromBuf(&response_frame[4]);
    printf("future subscribed msg_test: calculation sum:'%ld'\r\n", msg_test.data);
    break;
  }

  mros2::spin();
  return 0;
}
