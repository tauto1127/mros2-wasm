# ROS 2 checkpoint/restore interoperability

## Question

Can the current mROS 2/WAMR checkpoint-restore implementation resume `std_msgs/msg/String` communication with a normal ROS 2 node after restore, both when the container address stays `172.18.0.3` and when it moves from `172.18.0.3` to `172.18.0.6`?

The changed-IP question is narrower than "does any packet flow":

> When mROS 2 re-advertises the same Participant GUID with a new locator, does a stock ROS 2 DDS implementation follow that locator?

mROS 2's own peer deletes and re-adds a remote participant when the metatraffic or default unicast locator changes (`SPDPAgent::processProxyData`). A pass against that peer does not answer the ROS 2 question.

## Fixed subject

No production or migration source is changed. The Wasm subject is the already recorded state-boundary artifact:

- `iwasm` `fa63c40c2a17f8df6461d687a95cb01bf544e0b7788377d41c317dcec6d46822`
- `libcr_state_probe.so` `b91cdb900b478292d78a8dbfab24906bbdd3252be93b688f9c03e96c0b9121ca`
- `echoback_string.wasm` `52ecd6ffde313c25cc6c20298769f7c9ad816419b0ddce80555c5bc2417520e0`

Those files stay in `experiments/cr-state-boundary/runtime-build/` and are mounted read-only. This campaign does not rebuild them and does not write into `experiments/cr-state-boundary/`.

Worktree under test:

- `/home/osslab/20261004-mros2-wasm-cr-state-boundary`
- branch `experiment/cr-state-boundary`
- root `11e78503586aae6d728d35bf2b875917583aaa3a`, which contains baseline `e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0`
- `mros2` `912cfbdd1af9a28be685ab67803093d84bb31ed1`
- `embeddedRTPS` `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182`
- `lwip-wasm` `50a6e414aa7c5863e634603102640741ea7c3dd1`, which contains the IP-refresh commit `160d01d0a088fad9b20ce334bad1e3a110576500` plus the existing observation log

## What is reused from the state-boundary campaign

`experiments/cr-state-boundary/campaign.py` supplies the harness shape:

- Docker network `mros2-cr-net` (`609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, `172.18.0.0/16`)
- Wasm container address `172.18.0.3`
- peer address `172.18.0.5`
- changed-IP destination `172.18.0.6` in a new container
- `iwasm` command line, including `--restore` only on the restore process
- SIGUSR2 checkpoint, then wait until `main-memory.img` and `main-socket.img` are stable
- host-stamped logs and the four-stage gate below

The peer process is replaced. The native `/tmp/mros2-posix-run04-final-build/mros2-posix` binary is not started.

## Application gate

The payload remains `Hello from mros2-posix onto Linux: <id>`.

```text
Wasm publish
-> ROS 2 receive
-> ROS 2 echo publish return
-> Wasm callback
```

A passing window is ten consecutive IDs with all four stages. The ROS 2 lines are:

```text
event=peer_receive topic=/to_linux id=<id> payload='<payload>'
event=peer_echo_publish_return topic=/to_stm id=<id> payload='<payload>'
```

## ROS 2 peer

The peer is a stock `rclpy` node. It subscribes to `/to_linux` and publishes the same `std_msgs/msg/String` to `/to_stm`.

Source evidence for the QoS it offers and requests:

- `Node::create_publisher` calls `createWriter(..., reliable=false)`, so `rt/to_linux` is best-effort.
- `Domain::createWriter` sets that writer's durability to transient-local.
- `Node::create_subscription` calls `createReader(..., reliable=false)`, so `rt/to_stm` is best-effort and volatile (`Domain::createReader`).
- Topic names are prefixed with `rt/`. The type string in `string.hpp` is `std_msgs::msg::dds_::String_`.
- Reliability and durability values serialized by `TopicData::serializeIntoUcdrBuffer` use best-effort `1` and transient-local `1`, which match the numeric values ROS 2 already uses.

The peer therefore uses best-effort, volatile, keep-last depth 10 in both directions. Volatile is a legal request against a transient-local writer. This is peer compatibility with the existing Wasm application, not a change to lease duration, GUID, sockets, or the mROS 2 participant.

`RMW_IMPLEMENTATION` is set explicitly. Cyclone DDS is first. Fast DDS runs only if changed-IP Cyclone DDS fails, one trial first and at most three if that trial is informative.

The `ros:humble` image on this machine contains Fast DDS and not Cyclone DDS. The peer container uses a locally built image, `mros2-cr-ros2-peer:humble-20261004`, whose only addition is `ros-humble-rmw-cyclonedds-cpp`, `tcpdump`, and `iproute2`. The Wasm container stays on unmodified `ros:humble` `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138`.

Cyclone is bound to `172.18.0.5` with multicast enabled so the container does not discover through another interface. The same address whitelist is prepared for Fast DDS. Neither file changes lease duration or participant GUID.

The ROS 2 process is not restarted across checkpoint or restore.

## Runs

1. No-C/R control on Cyclone DDS. Stop if the ten-ID gate does not pass. That failure is a cold-start interoperability failure, not a restore failure.
2. Three same-IP restores, `.3 -> .3`, only after the control passes.
3. Three changed-IP restores, `.3 -> .6`, only after same-IP is 3/3.
4. Packet-level classification if changed-IP fails.
5. Fast DDS only in that failure case.

Each C/R trial records the checkpoint-boundary ID, checkpoint and restore times, the first post-restore publish, ROS 2 receive, ROS 2 echo, and Wasm callback, and the time until ten consecutive round trips. It also records whether `mros2-posix start!` or `netif_init` appears in the restore log. A startup rerun fails the trial even if messages flow, because that would not be resume-from-restored-state.

`[CR-STATE] netif_refresh` lines already present in the mounted Wasm binary are recorded. They are not new instrumentation.

## Packet evidence

`tcpdump` on the peer container's `eth0` writes `rtps.pcap`. The parser keeps SPDP, SEDP publication, SEDP subscription, user DATA, HEARTBEAT, and ACKNACK. mROS 2 frames are identified by vendor id `{13, 37}` from `Config::VENDOR_ID`.

Changed-IP classification, used only when the application gate fails:

| Class | Observation |
|---|---|
| A. SPDP failure | No post-restore SPDP from `.6` is on the capture, or SPDP from `.6` exists but the ROS 2 trace shows no new or updated participant with that GUID. |
| B. Participant locator update failure | SPDP from `.6` carries the new locator and the same GUID, but peer user traffic still targets `.3`. |
| C. SEDP endpoint update failure | Participant data shows `.6`, while SEDP writer/reader unicast locators stay on `.3`. |
| D. Data-plane failure | SPDP and SEDP locators are `.6`, and user DATA still does not complete the round trip. |
| E. mROS 2-side failure | The capture shows no re-advertisement of the new locator, or the re-advertised locator is still `.3`. |

A passing gate is not relabeled as one of these failures. The report separates source-code evidence, runtime logs, RTPS packets, and the application gate.

## Out of scope

- Editing lwIP, embeddedRTPS, mROS 2, or WAMR to make a trial pass.
- Adding sleeps, retries, lease changes, GUID changes, socket rebuilds, or a new participant.
- Restarting the ROS 2 node after restore.
- Rewriting `experiments/cr-state-boundary/` results.
- Cross-host migration.
