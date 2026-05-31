// 型(std_msgs::msg::Int64 / service_msgs::msg::add_two_int_client)は templates.hpp で
// 先に include 済み。ガード無しヘッダの二重 include を避けるためここでは再 include しない。
template mros2::Publisher mros2::Node::create_client<service_msgs::msg::add_two_int_client>(std::string topic_name, int qos);
template mros2::Publisher mros2::Node::create_client_publisher<service_msgs::msg::add_two_int_client>(std::string topic_name, int qos, std::string type_name);
template mros2::Subscriber mros2::Node::create_client_subscription<std_msgs::msg::Int64>(std::string topic_name, int qos, void (*fp)(std_msgs::msg::Int64 *), std::string type_name);
template std::future<uint8_t *> mros2::Publisher::async_send_request(service_msgs::msg::add_two_int_client &msg);
template void mros2::Subscriber::callback_handler<std_msgs::msg::Int64>(void *callee, const rtps::ReaderCacheChange &cacheChange);
