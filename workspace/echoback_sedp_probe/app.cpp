#include "mros2.h"
#include "std_msgs/msg/string.hpp"

#include "cmsis_os.h"
#include "netif.h"
#include "netif_wasm_add.h"

#include <stdio.h>
#include <string.h>

extern "C" void mros2_experiment_arm_sedp_drop(void);

static volatile int create_requested = 0;
static volatile int drop_requested = 0;
static int created = 0;

static int command_kind(const char *payload)
{
  if (std::strcmp(payload, "CREATE_AFTER_RESTORE") == 0)
  {
    return 1;
  }
  if (std::strcmp(payload, "CREATE_AFTER_RESTORE_DROP") == 0)
  {
    return 2;
  }
  return 0;
}

void userCallback(std_msgs::msg::String *msg)
{
  printf("subscribed msg: '%s'\r\n", msg->data.c_str());
  int kind = command_kind(msg->data.c_str());
  if (kind != 0 && !create_requested)
  {
    drop_requested = (kind == 2);
    create_requested = 1;
    printf("event=create_after_requested drop=%d\r\n", drop_requested);
  }
}

int main(int argc, char *argv[])
{
  netif_wasm_add(NETIF_IPADDR, NETIF_NETMASK);

  osKernelStart();

  printf("mros2-posix start!\r\n");
  printf("app name: echoback_sedp_probe\r\n");
  mros2::init(0, NULL);
  MROS2_DEBUG("mROS 2 initialization is completed\r\n");

  mros2::Node node = mros2::Node::create_node("mros2_node1");
  mros2::Publisher pub = node.create_publisher<std_msgs::msg::String>("to_linux", 10);
  mros2::Subscriber sub = node.create_subscription<std_msgs::msg::String>("to_stm", 10, userCallback);
  mros2::Publisher after_pub;

  osDelay(100);
  MROS2_INFO("ready to pub/sub message\r\n");

  auto count = 0;
  auto after_count = 0;
  while (1)
  {
    if (create_requested && !created)
    {
      printf("event=create_publisher_begin topic=migration_after_restore drop=%d\r\n",
             drop_requested);
      if (drop_requested)
      {
        mros2_experiment_arm_sedp_drop();
      }
      after_pub = node.create_publisher<std_msgs::msg::String>("migration_after_restore", 10);
      created = 1;
      printf("event=create_publisher_done topic=migration_after_restore\r\n");
    }

    auto msg = std_msgs::msg::String();
    msg.data = "Hello from mros2-posix onto Linux: " + std::to_string(count++);
    printf("publishing msg: '%s'\r\n", msg.data.c_str());
    pub.publish(msg);

    if (created)
    {
      auto after = std_msgs::msg::String();
      after.data = "after-restore " + std::to_string(after_count++);
      printf("event=after_publish payload='%s'\r\n", after.data.c_str());
      after_pub.publish(after);
    }
    osDelay(1000);
  }

  mros2::spin();
  return 0;
}
