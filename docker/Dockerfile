FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    bash coreutils findutils util-linux file openssh-server \
    grep sed gawk net-tools iproute2 iputils-ping traceroute \
    wget curl dnsutils procps psmisc tree vim-tiny nano openssl \
    gzip bzip2 xz-utils zip unzip cron netcat-traditional gnupg \
    iptables whois busybox sudo manpages man-db manpages-posix manpages-dev \
    && apt-get clean

RUN mkdir -p /var/run/sshd
RUN useradd -m -s /bin/bash user
RUN echo "user:user" | chpasswd
RUN sed -i 's/^#*Port.*/Port 2220/' /etc/ssh/sshd_config
RUN sed -i 's/^#*ListenAddress 0.0.0.0/ListenAddress 0.0.0.0/' /etc/ssh/sshd_config
RUN sed -i 's/^#*ListenAddress ::/ListenAddress ::/' /etc/ssh/sshd_config
RUN sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
RUN sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed -i 's/^PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config

EXPOSE 2220

# Run SSH daemon
CMD ["/usr/sbin/sshd", "-D"]
