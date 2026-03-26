# DecoyPot

DecoyPot paper implementation.

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

    Edit `.env` and set your GROQ API key:
    ```bash
    export GROQ_API_KEY="your_api_key_here"
    ```

4. Docker Setup (for testing)

    ```bash
    cd docker
    docker-compose up -d
    ```

## Usage

Run the interactive shell:

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
    - `main.py` - Implementation with shell simulation
    - `utils.py` - Configuration and utilities
    - `tester.py` - Data collection and analysis script
- `datasets/` - Command and attack scenario datasets
- `docker/` - Docker containers needed for testing
