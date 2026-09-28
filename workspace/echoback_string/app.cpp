#include "mros2.h"
#include "std_msgs/msg/string.hpp"

#include "cmsis_os.h"
#include "netif.h"
#include "netif_wasm_add.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>


void userCallback(std_msgs::msg::String *msg)
{
  const char *separator = strrchr(msg->data.c_str(), ':');
  const int message_id = separator ? atoi(separator + 1) : -1;
  printf("[CR-RERUN-20260927] APP callback topic=/to_stm id=%d payload='%s'\r\n",
         message_id, msg->data.c_str());
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
    auto msg = std_msgs::msg::String();
    const int message_id = count++;
    msg.data = "Hello from mros2-posix onto Linux: " + std::to_string(message_id);
    printf("[CR-RERUN-20260927] APP publish_begin topic=/to_linux id=%d payload='%s'\r\n",
           message_id, msg.data.c_str());
    pub.publish(msg);
    printf("[CR-RERUN-20260927] APP publish_return topic=/to_linux id=%d\r\n",
           message_id);
    osDelay(1000);
  }

  mros2::spin();
  return 0;
}
