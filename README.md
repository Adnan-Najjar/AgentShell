# AgentShell

AI-powered SSH honeypot that simulates a Linux shell with LLM-backed command responses.

## Features

- **LLM-Powered Responses** - Commands handled by Large Language Model for realistic output
- **Virtual Filesystem** - Maintains stateful filesystem that persists per session
- **Session Persistence** - Saves filesystem state per attacker IP (`logs/{ip}_filesystem.pkl`)
- **Download Capture** - wget/curl downloads saved to `logs/{ip}_downloads/` for SIEM analysis
- **ELK Stack Integration** - JSON logs ship to Elasticsearch/Kibana for visualization
- **Believability Testing** - Regex-based scoring to validate command outputs
- **Docker Ready** - Full docker-compose setup with honeypot and ELK stack

## Quick Start

```bash
# Start honeypot and ELK stack
docker compose up -d

# Access honeypot SSH (use PORT)
ssh root@localhost -p $PORT
# Password: root
# (default PORT is 2223 unless overridden)

# Access Kibana dashboard
# http://localhost:5601
```

## Usage

```bash
# Serve ssh server
make serve

# Run the interactive shell agent (development)
make shell

# Run believability tests against LLMs
make test

# Analyze test results
make analysis

# Clean logs and stop containers
make clean
```

## Project Structure

```
├── src/
│   ├── main.py          # Agent class, state management, LLM chat loop
│   ├── tools.py         # Command handlers, RAG docs, curl/wget downloads
│   ├── utils.py         # SYSTEM_PROMPT, parse_shell, extract_command_flags
│   ├── ssh_server.py    # Paramiko SSH honeypot server
│   └── believability.py # Regex-based testing and scoring
├── data/
│   ├── filesystem.pkl   # Default virtual filesystem
│   ├── commands.json    # Expected command outputs (control)
│   ├── commands_rules.json   # Regex rules for command validation
│   └── scenarios_rules.json # Regex rules for scenario validation
├── results/             # Test outputs per model
├── logs/                # Session logs, downloads, SQLite history
├── logstash/
│   ├── pipeline/        # Logstash config for honeypot events
│   └── config/          # Logstash settings
└── docker-compose.yml   # Honeypot + ELK stack deployment
```

## Configuration

Environment variables (in `.env` or docker-compose):

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `2223` | SSH server and container listen port |
| `MODEL` | `agentshell/low-risk` | LLM model to use |
| `BASE_URL` | `http://host.docker.internal:11434/v1` | LLM API endpoint |
| `API_KEY` | `ollama` | API key for authentication |

## ELK Integration

Logs are automatically shipped to Elasticsearch via Logstash:

1. **Log Format**: JSONL per IP (`logs/2026-04-29_192_168_1_100.log`)
2. **Index Pattern**: `honeypot-*`
3. **Kibana**: http://localhost:5601 - Create Data View with `honeypot-*`

## Testing

```bash
# Run tests against configured models
make test

# Check results
make analysis
```

### Believability Scores

Tests compare outputs against regex rules in `commands_rules.json` and `scenarios_rules.json`.

## Virtual Filesystem

The honeypot maintains a virtual filesystem that:
- Loads from `data/filesystem.pkl` on new session
- Saves to `logs/{ip}_filesystem.pkl` on session end
- Updates via LLM responses (mkdir, touch, wget, etc.)

## System Model


