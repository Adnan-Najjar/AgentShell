FROM debian:7

# Set hostname
RUN echo "svr04" > /etc/hostname

RUN echo "deb http://archive.debian.org/debian/ wheezy main contrib non-free" > /etc/apt/sources.list
RUN echo "deb http://archive.debian.org/debian-security wheezy/updates main contrib non-free" >> /etc/apt/sources.list
RUN rm -f /etc/apt/sources.list.d/*

RUN getent group daemon || groupadd -g 1 daemon && \
    id -u daemon || useradd -u 1 -g 1 -s /usr/sbin/nologin -d /usr/sbin daemon && \
    getent group bin || groupadd -g 2 bin && \
    id -u bin || useradd -u 2 -g 2 -s /usr/sbin/nologin -d /bin bin && \
    getent group sys || groupadd -g 3 sys && \
    id -u sys || useradd -u 3 -g 3 -s /usr/sbin/nologin -d /dev sys && \
    id -u www-data || useradd -u 33 -g 33 -s /usr/sbin/nologin -d /var/www www-data && \
    id -u phil || useradd -m -d /home/phil -s /bin/bash phil

RUN apt-get update -o Acquire::Check-Valid-Until=false && \
    apt-get install -y --force-yes --no-install-recommends -o Acquire::Check-Valid-Until=false \
        bash coreutils findutils util-linux file openssh-server \
        grep sed gawk net-tools iproute iputils-ping traceroute \
        wget curl dnsutils procps psmisc tree vim-tiny nano openssl \
        gzip bzip2 xz-utils zip unzip cron netcat-traditional gnupg \
        iptables whois busybox sudo sshpass && \
        apt-get clean

RUN mkdir -p /var/run/sshd
RUN echo "root:password" | chpasswd
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed -i 's/Port 22/Port 2220/' /etc/ssh/sshd_config

EXPOSE 2220

# Run SSH daemon
CMD ["/usr/sbin/sshd", "-D"]
