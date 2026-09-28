#!/usr/bin/env python3
"""ROS 2 echo peer with explicit graph and message evidence for one C/R run."""

import json
import os
import re
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


TAG = "[CR-RERUN-20260927-R02]"
ID_PATTERN = re.compile(r":\s*(\d+)\s*$")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class EchoPeer(Node):
    def __init__(self):
        super().__init__("mros2_cr_peer")
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.publisher = self.create_publisher(String, "/to_stm", qos)
        self.subscription = self.create_subscription(
            String, "/to_linux", self.on_message, qos
        )
        self.snapshot_number = 0
        self.timer = self.create_timer(1.0, self.log_graph)
        self.log("peer_start", role="ros2-echo-peer", pid=os.getpid())

    def log(self, event, **fields):
        payload = {
            "event": event,
            "pid": os.getpid(),
            "utc": utc_now(),
            **fields,
        }
        print(f"{TAG} peer=ros-peer {json.dumps(payload, sort_keys=True)}", flush=True)

    @staticmethod
    def endpoint_record(info, endpoint_type):
        qos = info.qos_profile
        return {
            "endpoint_type": endpoint_type,
            "gid": bytes(info.endpoint_gid).hex(),
            "node_name": info.node_name,
            "node_namespace": info.node_namespace,
            "topic_type": info.topic_type,
            "reliability": str(qos.reliability),
            "durability": str(qos.durability),
            "history": str(qos.history),
            "depth": qos.depth,
        }

    def topic_records(self, topic):
        publishers = [
            self.endpoint_record(info, "publisher")
            for info in self.get_publishers_info_by_topic(topic)
        ]
        subscriptions = [
            self.endpoint_record(info, "subscription")
            for info in self.get_subscriptions_info_by_topic(topic)
        ]
        return {
            "publishers": publishers,
            "subscriptions": subscriptions,
            "publisher_count": self.count_publishers(topic),
            "subscription_count": self.count_subscribers(topic),
        }

    def log_graph(self):
        self.snapshot_number += 1
        self.log(
            "graph_snapshot",
            snapshot=self.snapshot_number,
            topics={
                "/to_linux": self.topic_records("/to_linux"),
                "/to_stm": self.topic_records("/to_stm"),
            },
        )

    def on_message(self, msg):
        match = ID_PATTERN.search(msg.data)
        message_id = int(match.group(1)) if match else None
        self.log("peer_receive", topic="/to_linux", message_id=message_id,
                 payload=msg.data)
        self.publisher.publish(msg)
        self.log("peer_echo", topic="/to_stm", message_id=message_id,
                 payload=msg.data)


def main():
    rclpy.init()
    node = EchoPeer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.log("peer_stop", reason="shutdown")
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
