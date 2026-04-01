FROM ubuntu:latest

RUN apt-get update && apt-get install -y openssh-server busybox netcat-openbsd

RUN mkdir -p /run/sshd && chmod 755 /run/sshd

RUN useradd -m -s /bin/bash eve
RUN echo "eve:password" | chpasswd

RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed -i 's/#Port 22/Port 2221/' /etc/ssh/sshd_config
COPY attacker_key.pub /home/eve/.ssh/
COPY attacker_key /home/eve/.ssh/
RUN cat /home/eve/.ssh/attacker_key.pub >> /home/eve/.ssh/authorized_keys
RUN chmod 600 /home/eve/.ssh/attacker_key && \
    chmod 644 /home/eve/.ssh/attacker_key.pub && \
    chmod 600 /home/eve/.ssh/authorized_keys && \
    chmod 700 /home/eve/.ssh

RUN mkdir -p /var/www
RUN echo '#!/usr/bin/env bash\n echo "Hello world?"' > /var/www/file.sh
RUN echo '<h1>Hello World!</h1>' > /var/www/index.html

RUN mkdir -p /home/eve/received/
RUN echo '#!/bin/bash' > /home/eve/nc.sh && \
    echo 'while true; do' >> /home/eve/nc.sh && \
    echo '    nc -l -p 15000 > "/home/eve/received/$(date +%Y%m%d_%H%M%S).gz"' >> /home/eve/nc.sh && \
    echo 'done' >> /home/eve/nc.sh && \
    chmod +x /home/eve/nc.sh

EXPOSE 2221 8080 15000

CMD /bin/bash -c "/usr/sbin/sshd && busybox httpd -f -p 8080 -h /var/www & /home/eve/nc.sh"
