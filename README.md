# HivePot

Honeypot simulation system using LLM agents to study attacker behavior patterns compared to traditional honeypots.

## How to Setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (if not already installed)
2. Install dependencies
    ```bash
    uv sync
    ```
3. Configure environment variables

    Copy the example environment file and add your API keys:

    ```bash
    cp .env.example .env
    ```

    Edit `.env` and set your OpenRouter API key:
    ```bash
    OPENAI_API_KEY="your_openai_api_key_here"
    ```

4. Docker Setup (for testing)

    ```bash
    cd docker
    docker-compose up -d
    ```

## Usage

Run the interactive shell agent:

```bash
uv run python src/main.py
```

Generate LLM command data:

```bash
uv run python src/tester.py --llm-commands
```

Generate LLM attack scenarios:

```bash
uv run python src/tester.py --llm-scenarios
```

Run full analysis:

```bash
uv run python src/tester.py --analyze
```

## Project Structure

- `src/`
    - `main.py` - Agent implementation with shell simulation
    - `tools.py` - Tool definitions
    - `utils.py` - Configuration and utilities
    - `tester.py` - Data collection and analysis script
- `datasets/` - Command and attack scenario datasets
- `docker/` - Docker containers needed for testing
