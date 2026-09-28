#include "mros2.h"
#include "std_msgs/msg/string.hpp"

#include "cmsis_os.h"
#include "netif.h"
#include "netif_posix_add.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

mros2::Publisher echo_pub;

static void log_event(const char *event, const char *topic,
                      const std_msgs::msg::String *msg)
{
  struct timespec now;
  clock_gettime(CLOCK_REALTIME, &now);

  long message_id = -1;
  if (msg != NULL) {
    const char *separator = strrchr(msg->data.c_str(), ':');
    if (separator != NULL) {
      char *end = NULL;
      const long parsed = strtol(separator + 1, &end, 10);
      if (end != separator + 1) {
        message_id = parsed;
      }
    }
  }

  printf("[CR-NATIVE-R04] epoch=%ld.%09ld event=%s topic=%s id=%ld",
         now.tv_sec, now.tv_nsec, event, topic, message_id);
  if (msg != NULL) {
    printf(" payload='%s'", msg->data.c_str());
  }
  printf("\n");
}

static void userCallback(std_msgs::msg::String *msg)
{
  log_event("peer_receive", "/to_linux", msg);
  echo_pub.publish(*msg);
  log_event("peer_echo_publish_return", "/to_stm", msg);
}

int main(int argc, char *argv[])
{
  setvbuf(stdout, NULL, _IONBF, 0);
  printf("[CR-NATIVE-R04] event=process_start pid=%d\n", getpid());

  const int netif_result = netif_posix_add("172.18.0.5", NETIF_NETMASK);
  printf("[CR-NATIVE-R04] event=netif_config ip=172.18.0.5 mask=%s result=%d\n",
         NETIF_NETMASK, netif_result);
  if (netif_result != 0) {
    return 2;
  }

  osKernelStart();

  printf("[CR-NATIVE-R04] event=mros2_init_begin\n");
  mros2::init(0, NULL);
  MROS2_DEBUG("mROS 2 initialization is completed\r\n");

  mros2::Node node = mros2::Node::create_node("mros2_native_peer_r04");
  echo_pub = node.create_publisher<std_msgs::msg::String>("to_stm", 10);
  mros2::Subscriber sub = node.create_subscription<std_msgs::msg::String>(
      "to_linux", 10, userCallback);

  osDelay(100);
  MROS2_INFO("native peer ready: /to_linux -> /to_stm\r\n");
  printf("[CR-NATIVE-R04] event=peer_ready subscribe=/to_linux publish=/to_stm "
         "type=std_msgs/msg/String\n");

  mros2::spin();
  printf("[CR-NATIVE-R04] event=spin_return\n");
  return 0;
}
