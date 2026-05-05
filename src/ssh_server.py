#!/usr/bin/env python3
"""
Fake SSH Honeypot Server
------------------------
A fake SSH server built with Paramiko.
Logs every connection, credential attempt, command, and timing
to both the console and a structured JSONL log file.

Usage:
    python ssh_server.py [--port 22] [--host 0.0.0.0]
"""

import argparse
from datetime import date, datetime, timezone
import json
import os
import socket
import threading
import time
import uuid

import paramiko
import paramiko.transport as pt
from paramiko.common import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_SUCCEEDED,
)

from utils import (
    ACCEPTED_PASSWORDS,
    ACCEPTED_USERS,
    HOST_KEY_RSA,
    HOST_KEY_ECDSA,
    LOG_DIR,
    USER,
    SSH_BANNER,
    log,
    motd,
)
from main import Agent


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HoneypotLogger:
    """
    Writes one JSON object per line to a structured JSONL log file.
    Every event includes: timestamp, session_id, client_ip, client_port, event, + extras.

    Events logged:
        connection_open          – TCP connection accepted
        connection_close         – session ended (with total duration)
        ssh_negotiation_failed   – SSH handshake failed
        auth_attempt             – password or pubkey auth (always accepted)
        channel_open             – SSH channel opened
        pty_requested            – client requested a PTY (terminal size/type)
        shell_requested          – client requested an interactive shell
        exec_requested           – client sent a non-interactive exec command
        command                  – command typed in the shell
        empty_command            – user hit Enter with nothing typed
        keypress_ctrl            – Ctrl+C or Ctrl+D
        session_logout           – session ended (how: command/ctrl_d/channel_closed)
        no_channel               – client connected but never opened a channel
        channel_timeout          – channel opened but no shell request came
    """

    _lock = threading.Lock()

    def __init__(self, path: str):
        self.path = path

    def _write(self, record: dict):
        with self._lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(record) + "\n")

    def emit(
        self, session_id: str, client_ip: str, client_port: int, event: str, **kwargs
    ):
        record = {
            "timestamp": now_iso(),
            "session_id": session_id,
            "client_ip": client_ip,
            "client_port": client_port,
            "event": event,
            **kwargs,
        }
        self._write(record)

    # ── Convenience methods ───────────────────────────────────────────────────

    def connection_open(self, sid, ip, port):
        self.emit(sid, ip, port, "connection_open")
        log.info("[%s] NEW CONNECTION  %s:%d", sid[:8], ip, port)

    def connection_close(self, sid, ip, port, duration_s: float):
        self.emit(
            sid, ip, port, "connection_close", duration_seconds=round(duration_s, 3)
        )
        log.info(
            "[%s] DISCONNECTED  %s:%d  (session %.1fs)", sid[:8], ip, port, duration_s
        )

    def ssh_negotiation_failed(self, sid, ip, port, reason: str):
        self.emit(sid, ip, port, "ssh_negotiation_failed", reason=reason)
        log.warning(
            "[%s] SSH NEGOTIATION FAILED  %s:%d  reason=%r", sid[:8], ip, port, reason
        )

    def auth_attempt(
        self,
        sid,
        ip,
        port,
        method: str,
        username: str,
        password: str | None = None,
        pubkey_type: str | None = None,
        pubkey_fingerprint: str | None = None,
    ):
        extras = dict(method=method, username=username)
        if password is not None:
            extras["password"] = password
        if pubkey_type is not None:
            extras["pubkey_type"] = pubkey_type
        if pubkey_fingerprint is not None:
            extras["pubkey_fingerprint"] = pubkey_fingerprint
        self.emit(sid, ip, port, "auth_attempt", **extras)

        if method == "password":
            log.info(
                "[%s] AUTH password  %s:%d  user=%r  pass=%r",
                sid[:8],
                ip,
                port,
                username,
                password,
            )
        else:
            log.info(
                "[%s] AUTH pubkey  %s:%d  user=%r  key_type=%r  fingerprint=%r",
                sid[:8],
                ip,
                port,
                username,
                pubkey_type,
                pubkey_fingerprint,
            )

    def channel_open(self, sid, ip, port, kind: str):
        self.emit(sid, ip, port, "channel_open", kind=kind)
        log.debug("[%s] CHANNEL OPEN  kind=%r", sid[:8], kind)

    def pty_requested(self, sid, ip, port, term: str, width: int, height: int):
        self.emit(sid, ip, port, "pty_requested", term=term, width=width, height=height)
        log.debug("[%s] PTY  term=%r  %dx%d", sid[:8], term, width, height)

    def shell_requested(self, sid, ip, port):
        self.emit(sid, ip, port, "shell_requested")
        log.debug("[%s] SHELL REQUESTED", sid[:8])

    def exec_requested(self, sid, ip, port, command: str):
        self.emit(sid, ip, port, "exec_requested", command=command)
        log.info("[%s] EXEC REQUEST  %r", sid[:8], command)

    def command(self, sid, ip, port, raw: str, elapsed_s: float):
        self.emit(
            sid,
            ip,
            port,
            "command",
            raw=raw,
            argv=raw.split(),
            elapsed_since_login_seconds=round(elapsed_s, 3),
        )
        log.info("[%s] CMD [+%.1fs]  %r", sid[:8], elapsed_s, raw)

    def empty_command(self, sid, ip, port):
        self.emit(sid, ip, port, "empty_command")
        log.debug("[%s] EMPTY COMMAND", sid[:8])

    def keypress_ctrl(self, sid, ip, port, key: str):
        self.emit(sid, ip, port, "keypress_ctrl", key=key)
        log.debug("[%s] CTRL+%s", sid[:8], key)

    def session_logout(self, sid, ip, port, method: str):
        self.emit(sid, ip, port, "session_logout", method=method)
        log.info("[%s] LOGOUT  method=%r", sid[:8], method)

    def no_channel(self, sid, ip, port):
        self.emit(sid, ip, port, "no_channel")
        log.warning("[%s] NO CHANNEL OPENED  %s:%d", sid[:8], ip, port)

    def channel_timeout(self, sid, ip, port):
        self.emit(sid, ip, port, "channel_timeout")
        log.warning("[%s] CHANNEL TIMEOUT  %s:%d", sid[:8], ip, port)


# ── Host key ──────────────────────────────────────────────────────────────────
def get_host_key() -> list:
    keys = []

    if os.path.exists(HOST_KEY_RSA):
        log.info("Loaded RSA host key from %s", HOST_KEY_RSA)
        keys.append(paramiko.RSAKey(filename=HOST_KEY_RSA))
    else:
        log.info("Generating new RSA host key → %s", HOST_KEY_RSA)
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(HOST_KEY_RSA)
        keys.append(key)

    if os.path.exists(HOST_KEY_ECDSA):
        log.info("Loaded ECDSA host key from %s", HOST_KEY_ECDSA)
        keys.append(paramiko.ECDSAKey(filename=HOST_KEY_ECDSA))
    else:
        log.info("Generating new ECDSA host key → %s", HOST_KEY_ECDSA)
        key = paramiko.ECDSAKey.generate()
        key.write_private_key_file(HOST_KEY_ECDSA)
        keys.append(key)

    return keys


# ── SSH Server interface ───────────────────────────────────────────────────────
class FakeSSHServer(paramiko.ServerInterface):
    def __init__(
        self, session_id: str, client_ip: str, client_port: int, hlog: HoneypotLogger
    ):
        self.session_id = session_id
        self.client_ip = client_ip
        self.client_port = client_port
        self.username = "unknown"

        self.event = threading.Event()

        self.exec_command: str | None = None

        self.hlog = hlog

    # ── AUTH ────────────────────────────────────────────────────────────────

    def check_auth_password(self, username: str, password: str) -> int:
        self.hlog.auth_attempt(
            self.session_id,
            self.client_ip,
            self.client_port,
            method="password",
            username=username,
            password=password,
        )

        if username not in ACCEPTED_USERS or password not in ACCEPTED_PASSWORDS:
            return AUTH_FAILED

        self.username = username
        return AUTH_SUCCESSFUL

    def check_auth_publickey(self, username: str, key) -> int:
        self.hlog.auth_attempt(
            self.session_id,
            self.client_ip,
            self.client_port,
            method="publickey",
            username=username,
            pubkey_type=key.get_name(),
            pubkey_fingerprint=key.get_fingerprint().hex(),
        )

        if username not in ACCEPTED_USERS:
            return AUTH_FAILED

        self.username = username
        return AUTH_SUCCESSFUL

    def get_allowed_auths(self, username: str) -> str:
        return "password,publickey"

    # ── CHANNEL HANDLING ────────────────────────────────────────────────────

    def check_channel_request(self, kind: str, chanid: int) -> int:
        self.hlog.channel_open(self.session_id, self.client_ip, self.client_port, kind)

        if kind == "session":
            return OPEN_SUCCEEDED

        return OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ) -> bool:
        self.hlog.pty_requested(
            self.session_id,
            self.client_ip,
            self.client_port,
            term.decode() if isinstance(term, bytes) else term,
            width,
            height,
        )
        return True

    def check_channel_shell_request(self, channel) -> bool:
        self.hlog.shell_requested(self.session_id, self.client_ip, self.client_port)

        # Interactive shell requested
        self.exec_command = None
        self.event.set()
        return True

    def check_channel_exec_request(self, channel, command: bytes) -> bool:
        cmd = command.decode(errors="replace")

        self.exec_command = cmd

        self.hlog.exec_requested(
            self.session_id,
            self.client_ip,
            self.client_port,
            cmd,
        )

        self.event.set()
        return True


# ── Shell emulator ─────────────────────────────────────────────────────────────
def dispatch(cmd: str, agent: Agent) -> str | None:
    base = cmd.split()[0] if cmd.split() else ""
    if base in ("exit", "logout", "quit"):
        return None
    if base == "clear":
        return "\x1b[2J\x1b[H"

    return agent.chat(cmd)


def run_shell(
    channel: paramiko.Channel,
    session_id: str,
    client_ip: str,
    client_port: int,
    agent: Agent,
    hlog: HoneypotLogger,
):
    prompt = agent.shell_prompt
    login_time = time.monotonic()

    def send(data: str):
        channel.sendall(data.encode())

    def send_line(line: str = ""):
        line = line.replace("\r\n", "\n").replace("\n", "\r\n")
        send(line + "\r\n")

    def elapsed() -> float:
        return time.monotonic() - login_time

    # MOTD
    send_line()
    for line in motd().splitlines():
        send_line(line)
    send(prompt)

    buf = ""

    while True:
        try:
            chunk = channel.recv(256)
        except Exception:
            hlog.session_logout(session_id, client_ip, client_port, "channel_closed")
            break

        if not chunk:
            hlog.session_logout(session_id, client_ip, client_port, "channel_closed")
            break

        for byte in chunk:
            ch = chr(byte) if isinstance(byte, int) else byte

            if ch == "\x03":  # Ctrl-C
                hlog.keypress_ctrl(session_id, client_ip, client_port, "C")
                send_line("^C")
                buf = ""
                send(agent.shell_prompt)
                continue

            if ch == "\x04":  # Ctrl-D
                hlog.keypress_ctrl(session_id, client_ip, client_port, "D")
                hlog.session_logout(session_id, client_ip, client_port, "ctrl_d")
                send_line("logout")
                channel.close()
                return

            if ch in ("\x7f", "\x08"):  # Backspace
                if buf:
                    buf = buf[:-1]
                    send("\x08 \x08")
                continue

            if ch in ("\r", "\n"):  # Enter
                send_line()
                cmd = buf.strip()
                buf = ""

                if not cmd:
                    hlog.empty_command(session_id, client_ip, client_port)
                    send(agent.shell_prompt)
                    continue

                hlog.command(session_id, client_ip, client_port, cmd, elapsed())
                response = dispatch(cmd, agent)

                if response is None:
                    hlog.session_logout(session_id, client_ip, client_port, "command")
                    send_line("logout")
                    channel.close()
                    return

                if response:
                    response = response.replace("\r\n", "\n").replace("\n", "\r\n")
                    send_line(response)

                send(agent.shell_prompt)
                continue

            if ch.isprintable():
                buf += ch
                send(ch)


# ── Connection handler ─────────────────────────────────────────────────────────
_semaphore = threading.Semaphore(50)


def handle_connection(
    conn: socket.socket, addr: tuple, host_key: list[paramiko.RSAKey]
):
    with _semaphore:
        conn.settimeout(30)
        client_ip, client_port = addr[0], addr[1]
        session_id = str(uuid.uuid4())
        connect_time = time.monotonic()

        hlog = HoneypotLogger(
            f"{LOG_DIR}/{date.today()}_{client_ip.replace('.', '_')}.log"
        )
        hlog.connection_open(session_id, client_ip, client_port)

        transport = paramiko.Transport(conn)
        transport.local_version = SSH_BANNER

        for key in host_key:
            transport.add_server_key(key)

        server = FakeSSHServer(session_id, client_ip, client_port, hlog)

        try:
            transport.start_server(server=server)
        except (paramiko.SSHException, ConnectionResetError) as exc:
            hlog.ssh_negotiation_failed(session_id, client_ip, client_port, str(exc))
            hlog.connection_close(
                session_id, client_ip, client_port, time.monotonic() - connect_time
            )
            return

        channel = transport.accept(timeout=30)
        if channel is None:
            hlog.no_channel(session_id, client_ip, client_port)
            hlog.connection_close(
                session_id, client_ip, client_port, time.monotonic() - connect_time
            )
            transport.close()
            return

        server.event.wait(timeout=30)
        if not server.event.is_set():
            hlog.channel_timeout(session_id, client_ip, client_port)
            hlog.connection_close(
                session_id, client_ip, client_port, time.monotonic() - connect_time
            )
            channel.close()
            transport.close()
            return

        agent = Agent(client_ip)
        try:
            if server.exec_command is not None:
                cmd = server.exec_command.strip()
                server.exec_command = None

                response = dispatch(cmd, agent)
                output = (response or "") + "\n"

                try:
                    channel.sendall(output.encode())
                    channel.shutdown_write()
                except Exception:
                    pass

                return

            run_shell(channel, session_id, client_ip, client_port, agent, hlog)

        finally:
            agent.save_session_filesystem()
            hlog.connection_close(
                session_id, client_ip, client_port, time.monotonic() - connect_time
            )
            try:
                channel.close()
            except Exception:
                pass
            transport.close()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Fake SSH honeypot server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=22)
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Starting SSH AgentShell Honeypot...")
    log.info("Bind    : %s:%d", args.host, args.port)
    log.info(
        "Events  : %s/<today_date>_<ip_addr>.log  (JSONL, one event per line)", LOG_DIR
    )
    log.info("Debug   : %s/debug.log", LOG_DIR)
    log.info("=" * 60)

    host_key = get_host_key()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    sock.listen(10)

    log.info(
        "Ready — connect with:  ssh -p %d anyuser@%s",
        args.port,
        "localhost" if args.host == "0.0.0.0" else args.host,
    )

    while True:
        try:
            conn, addr = sock.accept()
        except KeyboardInterrupt:
            log.info("Shutting down.")
            break

        threading.Thread(
            target=handle_connection,
            args=(conn, addr, host_key),
            daemon=True,
        ).start()


if __name__ == "__main__":
    main()
