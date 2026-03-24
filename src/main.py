from langchain.agents import AgentState, create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from tools import Tools
from utils import MODEL, SYSTEM_PROMPT


class ShellAgentState(AgentState):
    user: str
    user_dir: str
    localhost: str
    current_dir: str
    is_root: bool


class OutputStructure(BaseModel):
    user: str
    user_dir: str
    localhost: str
    current_dir: str
    is_root: bool
    command_output: str


class Agent:
    def __init__(self, thread_id: str = "thread") -> None:
        self.config = RunnableConfig(configurable={"thread_id": thread_id})

        self.tools = Tools(thread_id)

        self.current_state = {
            "user": "root",
            "user_dir": "/root",
            "localhost": "svr04",
            "current_dir": "/root",
            "is_root": True,
        }
        self.total_tokens = 0

        self.model = ChatOllama(
            model=MODEL,
            temperature=0,
            seed=42,
        )
        self.shell_prompt = self._shell_prompt(self.current_state)

        self.agent = create_agent(
            model=self.model,
            tools=self.tools.get_tools(),
            system_prompt=SYSTEM_PROMPT,
            response_format=ToolStrategy(OutputStructure),
            state_schema=ShellAgentState,
        )

    def _token_counter(self, messages):
        tokens = 0
        for msgi in range(len(messages) - 1, 0, -1):
            msg = messages[msgi]
            if isinstance(msg, HumanMessage):
                tokens += len(msg.content)
            elif isinstance(msg, AIMessage):
                input_tokens = int(tokens / 4)
                last_tokens = msg.usage_metadata["total_tokens"]  # type: ignore
                return last_tokens + input_tokens
        return 0

    def _shell_prompt(self, state: dict) -> str:
        prompt = f"{state['user']}@{state['localhost']}:{state['current_dir']}{'#' if state['is_root'] else '$'} "
        return prompt.replace(state["user_dir"], "~", 1)

    def _format_state(self) -> str:
        """Format current state for LLM context."""
        return f"""Current State:
- User: {self.current_state["user"]}
- Home: {self.current_state["user_dir"]}
- Hostname: {self.current_state["localhost"]}
- Current Directory: {self.current_state["current_dir"]}
- Is Root: {self.current_state["is_root"]}"""

    def chat(self, query: str) -> str:
        output = ""
        # Add input to DB
        last_id = self.tools.set_history(query)

        # Check if command exist
        command = query.split()[0]
        valid, error_msg = self.tools.validate_command(command)
        if not valid:
            output = error_msg
        else:
            # Build full query with state context
            state_context = self._format_state()
            full_query = f"""{state_context}

User Query: {query}

Respond with JSON only."""

            result = self.agent.invoke(
                {"messages": [HumanMessage(content=full_query)]},
                self.config,
            )
            try:
                structured_output = result["structured_response"]

                # Update the state
                self.current_state = {
                    "user": structured_output.user,
                    "user_dir": structured_output.user_dir,
                    "localhost": structured_output.localhost,
                    "current_dir": structured_output.current_dir,
                    "is_root": structured_output.is_root,
                    "command_output": structured_output.command_output,
                }

                # Update the shell prompt
                self.shell_prompt = self._shell_prompt(self.current_state)
                # Update the total tokens used
                self.total_tokens = self._token_counter(result["messages"])

                output = structured_output.command_output
            except KeyError:
                output = ""

        self.tools.update_history(last_id, output)

        return output


if __name__ == "__main__":
    agent = Agent()
    while True:
        q = input(agent.shell_prompt)
        if q != "":
            response = agent.chat(q)
            print("Token used:", agent.total_tokens)
            if response != "":
                print(response)
