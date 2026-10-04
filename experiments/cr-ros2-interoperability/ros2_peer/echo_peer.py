#!/usr/bin/env python3
"""Echo /to_linux onto /to_stm with the QoS mROS 2 actually advertises.

create_publisher uses a best-effort transient-local writer.
create_subscription uses a best-effort volatile reader.
A volatile best-effort subscription is compatible with the transient-local
writer. This process does not restart discovery on its own.
"""

import os
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


PREFIX = "Hello from mros2-posix onto Linux: "


def message_id(payload):
    if not payload.startswith(PREFIX):
        return -1
    tail = payload[len(PREFIX):]
    return int(tail) if tail.isdigit() else -1


class EchoPeer(Node):
    def __init__(self):
        super().__init__("mros2_ros2_echo_peer")
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._pub = self.create_publisher(String, "/to_stm", qos)
        self.create_subscription(String, "/to_linux", self._on_string, qos)
        print(
            "event=peer_start "
            f"rmw={os.environ.get('RMW_IMPLEMENTATION', '')} "
            f"domain={os.environ.get('ROS_DOMAIN_ID', '')} "
            "subscribe=/to_linux publish=/to_stm "
            "reliability=best_effort durability=volatile depth=10",
            flush=True,
        )

    def _on_string(self, message):
        payload = message.data
        mid = message_id(payload)
        print(
            f"event=peer_receive topic=/to_linux id={mid} payload='{payload}'",
            flush=True,
        )
        outgoing = String()
        outgoing.data = payload
        self._pub.publish(outgoing)
        print(
            "event=peer_echo_publish_return "
            f"topic=/to_stm id={mid} payload='{payload}'",
            flush=True,
        )


def main():
    rclpy.init(args=sys.argv)
    node = EchoPeer()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
