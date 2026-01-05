FROM debian:7

COPY install.sh /tmp/install.sh
RUN chmod +x /tmp/install.sh && /tmp/install.sh

EXPOSE 2220

# Run SSH daemon
CMD ["/usr/sbin/sshd", "-D"]
