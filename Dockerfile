FROM ubuntu:latest

WORKDIR /app

RUN yes | unminimize
RUN apt-get update && apt-get install -y \
    bash coreutils findutils util-linux file openssh-server \
    grep sed gawk net-tools iproute2 iputils-ping traceroute ncat \
    wget curl dnsutils procps psmisc tree openssl python3 fdisk \
    gzip bzip2 xz-utils zip unzip cron netcat-traditional gnupg \
    iptables whois busybox sudo manpages man-db manpages-posix manpages-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*;

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh;
ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock .
RUN uv sync --frozen --no-dev;

RUN mkdir output logs;
COPY src/ ./src/
COPY data/ ./data/

EXPOSE 22

CMD ["uv", "run", "src/ssh_server.py"]
