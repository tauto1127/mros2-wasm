// NOTE: build.bash の generate_template_functions (templates_generator.py) は
// create_publisher/create_subscription しか解釈せず templates.hpp を毎回空に上書きする。
// そのため service 用の明示的実体化は、生成対象でないこの templates-service.hpp に
// includes ごと自己完結で記述する。
// std_msgs の int64.hpp/string.hpp はインクルードガードが無いので、ここで一度だけ include する。
#include "std_msgs/msg/string.hpp"
#include "std_msgs/msg/int64.hpp"
#include "service_msgs/msg/add_two_int_client.hpp"

template mros2::Publisher mros2::Node::create_publisher<std_msgs::msg::String>(std::string topic_name, int qos);
template void mros2::Publisher::publish(service_msgs::msg::add_two_int_client &msg);
template mros2::Subscriber mros2::Node::create_subscription(std::string topic_name, int qos, void (*fp)(std_msgs::msg::String *));
template void mros2::Subscriber::callback_handler<std_msgs::msg::String>(void *callee, const rtps::ReaderCacheChange &cacheChange);

template mros2::Publisher mros2::Node::create_client<service_msgs::msg::add_two_int_client>(std::string topic_name, int qos);
template mros2::Publisher mros2::Node::create_client_publisher<service_msgs::msg::add_two_int_client>(std::string topic_name, int qos, std::string type_name);
template mros2::Subscriber mros2::Node::create_client_subscription<std_msgs::msg::Int64>(std::string topic_name, int qos, void (*fp)(std_msgs::msg::Int64 *), std::string type_name);
template std::future<std::vector<uint8_t>> mros2::Publisher::async_send_request(service_msgs::msg::add_two_int_client &msg, uint32_t *request_id);
template void mros2::Subscriber::callback_handler<std_msgs::msg::Int64>(void *callee, const rtps::ReaderCacheChange &cacheChange);
