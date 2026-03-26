#!/usr/bin/env bash

echo "svr04" > /etc/hostname

echo "deb http://archive.debian.org/debian/ wheezy main contrib non-free" > /etc/apt/sources.list
echo "deb http://archive.debian.org/debian-security wheezy/updates main contrib non-free" >> /etc/apt/sources.list
rm -f /etc/apt/sources.list.d/*

useradd -m -d /home/phil -s /bin/bash phil

apt-get update -o Acquire::Check-Valid-Until=false && \
apt-get install -y --force-yes --no-install-recommends -o Acquire::Check-Valid-Until=false \
    bash coreutils findutils util-linux file openssh-server \
    grep sed gawk net-tools iproute iputils-ping traceroute \
    wget curl dnsutils procps psmisc tree vim-tiny nano openssl \
    gzip bzip2 xz-utils zip unzip cron netcat-traditional gnupg \
    iptables whois busybox sudo sshpass man && \
    apt-get clean

mkdir -p /var/run/sshd
echo "root:password" | chpasswd
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/Port 22/Port 2220/' /etc/ssh/sshd_config
