# ROS 2 checkpoint/restore interoperability

This directory is the campaign for one question: after WAMR checkpoint/restore, can the existing mROS 2 Wasm node resume a string round trip with stock ROS 2, without using the mROS 2 native peer.

The design is in `plan.md`. The Wasm binary, iwasm, and native probe are mounted from `experiments/cr-state-boundary/runtime-build/` and are not rebuilt here.

## Peer image

`ros:humble` on this machine does not contain `rmw_cyclonedds_cpp`. Build a local peer image once:

```bash
rtk proxy docker build -t mros2-cr-ros2-peer:humble-20261004 \
  experiments/cr-ros2-interoperability
```

The Wasm container still uses the pinned `ros:humble` image.

## Run

From the worktree root:

```bash
rtk proxy python3 experiments/cr-ros2-interoperability/test_rtps_pcap.py
rtk proxy python3 experiments/cr-ros2-interoperability/campaign.py run control cyclonedds 1
rtk proxy python3 experiments/cr-ros2-interoperability/campaign.py run same cyclonedds 1
```

`same` and `changed` refuse to start unless the earlier gate passed. Fast DDS is selected with `fastrtps` and is only for the changed-IP comparison described in `plan.md`.

Raw trials land in `results/<rmw>/<mode>/run-NN/`. Passing checkpoint images under `/tmp/mros2-cr-ros2-interoperability/` are deleted after their hashes are recorded. Failed images are left in place.
