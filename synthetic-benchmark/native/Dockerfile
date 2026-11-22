FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ca-certificates dbus python3 nlohmann-json3-dev zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY .vendor/scandit-amd64.deb /tmp/scandit.deb
RUN dpkg -i /tmp/scandit.deb \
    && ln -sf /usr/lib/libscanditsdk.so.8.7.1 /usr/lib/libscanditsdk.so \
    && ldconfig \
    && rm /tmp/scandit.deb
WORKDIR /workspace
