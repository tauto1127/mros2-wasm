// NOTE: std_msgs の int64.hpp / string.hpp はインクルードガードを持たないため、
// templates.hpp と templates-service.hpp の双方では include せず、ここで一度だけ include する。
// mros2.cpp では templates.hpp → templates-service.hpp の順に include されるため、
// templates-service.hpp 側はここで定義済みの型を参照できる。
#include "std_msgs/msg/string.hpp"
#include "std_msgs/msg/int64.hpp"
#include "service_msgs/msg/add_two_int_client.hpp"

template mros2::Publisher mros2::Node::create_publisher<std_msgs::msg::String>(std::string topic_name, int qos);
template void mros2::Publisher::publish(service_msgs::msg::add_two_int_client &msg);
template mros2::Subscriber mros2::Node::create_subscription(std::string topic_name, int qos, void (*fp)(std_msgs::msg::String *));
template void mros2::Subscriber::callback_handler<std_msgs::msg::String>(void *callee, const rtps::ReaderCacheChange &cacheChange);
