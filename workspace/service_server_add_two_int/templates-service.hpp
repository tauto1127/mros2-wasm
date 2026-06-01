// NOTE: build.bash の generate_template_functions は create_publisher/subscription しか
// 解釈せず templates.hpp を毎回空に上書きするため、service サーバ用の明示的実体化は
// 生成対象でないこの templates-service.hpp に includes ごと自己完結で記述する。
// std_msgs の int64.hpp/string.hpp はインクルードガードが無いのでここで一度だけ include。
#include "std_msgs/msg/string.hpp"
#include "std_msgs/msg/int64.hpp"
#include "service_msgs/msg/add_two_int_client.hpp"

template mros2::Publisher mros2::Node::create_publisher<std_msgs::msg::String>(std::string topic_name, int qos);
template void mros2::Publisher::publish(std_msgs::msg::String &msg);
template mros2::Subscriber mros2::Node::create_subscription(std::string topic_name, int qos, void (*fp)(std_msgs::msg::String *));
template void mros2::Subscriber::callback_handler<service_msgs::msg::add_two_int_client>(void *callee, const rtps::ReaderCacheChange &cacheChange);

template mros2::Publisher mros2::Node::create_service_server_publisher<std_msgs::msg::Int64>(std::string topic_name, int qos);
template mros2::Subscriber mros2::Node::create_service_server_subscription<service_msgs::msg::add_two_int_client, std_msgs::msg::Int64>(std::string topic_name, int qos, void (*fp)(service_msgs::msg::add_two_int_client *, std_msgs::msg::Int64 *));
template mros2::Subscriber mros2::Node::create_service<service_msgs::msg::add_two_int_client, std_msgs::msg::Int64>(std::string topic_name, int qos, void (*fp)(service_msgs::msg::add_two_int_client *, std_msgs::msg::Int64 *));
template void mros2::Subscriber::service_callback_handler<service_msgs::msg::add_two_int_client, std_msgs::msg::Int64>(void *callee, const rtps::ReaderCacheChange &cacheChange);
