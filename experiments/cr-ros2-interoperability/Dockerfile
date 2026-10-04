FROM ros:humble
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ros-humble-rmw-cyclonedds-cpp \
      tcpdump \
      iproute2 \
 && rm -rf /var/lib/apt/lists/*
