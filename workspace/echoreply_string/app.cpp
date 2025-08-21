#include "mros2.h"
#include "std_msgs/msg/string.hpp"

#include "cmsis_os.h"
#include "netif.h"
#include "netif_wasm_add.h"

#include <stdio.h>
#include <string.h>


mros2::Subscriber sub;
mros2::Publisher pub;

void userCallback(std_msgs::msg::String *msg)
{
  printf("subscribed msg: '%s'\r\n", msg->data.c_str());
  printf("publishing msg: '%s'\r\n", msg->data.c_str());
  pub.publish(*msg);
}

int main(int argc, char* argv[])
{
  netif_wasm_add(NETIF_IPADDR, NETIF_NETMASK);

  osKernelStart();

  printf("mros2-posix start!\r\n");
  printf("happy happy mROS 2!\r\n");
  printf("app name: echoreply_stringgggg\r\n");
  mros2::init(0, NULL);
  MROS2_DEBUG("mROS 2 initialization is completed\r\n");

  mros2::Node node = mros2::Node::create_node("mros2_node2");
  // pub = node.create_publisher<std_msgs::msg::String>("to_linux", 10);
  sub = node.create_subscription<std_msgs::msg::String>("to_linux", 10, userCallback);
  osDelay(100);
  MROS2_INFO("ready to pub/sub message\r\n");

  mros2::spin();
  return 0;
}
