// add_two_ints.hpp
#ifndef _SERVICE_MSGS_SRV_ADD_TWO_INTS_H
#define _SERVICE_MSGS_SRV_ADD_TWO_INTS_H

#include "add_two_int_client.hpp"                                                                          // 既存のリクエストメッセージクラス
#include "/home/oss-wasm/Documents/test-mros/vm_share/mros2-posix/mros2/mros2_msgs/std_msgs/msg/int64.hpp" // 既存のレスポンスメッセージクラス

namespace service_msgs
{
  namespace msg
  {
    class add_two_ints
    {
    public:
      using Request = service_msgs::msg::add_two_int_client;
      using Response = std_msgs::msg::Int64;
    };
    // class変数で、example_interfaces::srv::dds_::AddTwoInts_Request_と、example_interfaces::srv::dds_::AddTwoInts_Response_を定義する

  } // namespace msg

} // namespace service_msgs

#endif // _SERVICE_MSGS_SRV
