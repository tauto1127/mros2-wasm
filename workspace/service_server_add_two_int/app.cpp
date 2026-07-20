#include "mros2.h"
#include "std_msgs/msg/string.hpp"
#include "std_msgs/msg/int64.hpp"

#include "cmsis_os.h"
#include "netif.h"
#include "netif_wasm_add.h"

#include <stdio.h>
#include <string.h>
#include "service_msgs/msg/add_two_int_client.hpp"

// スレッドセーフなキューまたはマップを使用
// std::mutex bufferMutex;
// std::queue<CacheChangeInfo> cacheChangeQueue;

// mros2::Publisher pub_callback;
// void userCallback(service_msgs::msg::add_two_int_request *msg)
// {
//   // printf("subscribed msg: '%s'\r\n", msg->data.c_str());
//   // printf("subscribed msg: calculation sum:'%s'\r\n", msg->data);
//   printf("subscribed msg: calculation sum:'%d' + '%d'\r\n", msg->a, msg->b);
//   auto response = std_msgs::msg::Int64();
//   response.data = msg->a + msg->b;
//   printf("publishing msg: calculation sum:'%d'\r\n", response.data);
//   printf("NO-PUB publishing msg: calculation sum:'%d'\r\n", response.data);
//   pub_callback.publish(response);
// }

// mros2::Publisher pub_callback;
void service_userCallback(service_msgs::msg::add_two_int_client *msg, std_msgs::msg::Int64 *response)
{
  // printf("subscribed msg: '%s'\r\n", msg->data.c_str());
  // printf("subscribed msg: calculation sum:'%s'\r\n", msg->data);
  printf("subscribed msg: calculation sum:'%d' + '%d'\r\n", msg->a, msg->b);
  auto response_debug = std_msgs::msg::Int64();
  response_debug.data = msg->a + msg->b;
  response->data = msg->a + msg->b;
  // printf("publishing msg: calculation sum:'%d'\r\n", response->data);
  // printf("NO-PUB publishing msg: calculation sum:'%d'\r\n", response->data);
  printf("publishing msg: calculation sum:'%d'\r\n", response_debug.data);
  printf("NO-PUB publishing msg: calculation sum:'%d'\r\n", response_debug.data);
  // pub_callback.publish(response_debug);
}

void userCallback(std_msgs::msg::String *msg)
{
  printf("subscribed msg: '%s'\r\n", msg->data.c_str());
}

int main(int argc, char *argv[])
{
  netif_wasm_add(NETIF_IPADDR, NETIF_NETMASK);

  osKernelStart();

  printf("mros2-posix start!\r\n");
  printf("app name: echoback_string\r\n");
  mros2::init(0, NULL);
  MROS2_DEBUG("mROS 2 initialization is completed\r\n");

  mros2::Node node = mros2::Node::create_node("mros2_node");

  // add_two_ints サービスを提供（リクエスト受信→a+bを計算してレスポンス）
  mros2::Subscriber service = node.create_service<service_msgs::msg::add_two_int_client, std_msgs::msg::Int64>("add_two_ints", 10, service_userCallback);

  osDelay(100);
  MROS2_INFO("ready to pub/sub message\r\n");

  auto count = 0;
  // 10回送信
  // while (count < 10)
  // {
  //   auto msg = std_msgs::msg::String();
  //   msg.data = "Hello from mros2-posix onto Linux: " + std::to_string(count++);
  //   printf("publishing msg: '%s'\r\n", msg.data.c_str());
  //   pub.publish(msg);
  //   osDelay(1000);
  // }

  mros2::spin();
  return 0;
}
