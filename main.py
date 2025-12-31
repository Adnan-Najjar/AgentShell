from langchain_openai import ChatOpenAI
from langchain.agents import create_agent, AgentState
from langchain.agents.structured_output import ToolStrategy
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import SecretStr
from typing import Tuple
import sqlite3
import os
from utils import SYSTEM_PROMPT, SUMMARY_PROMPT, MODEL, SUMMARY_MODEL
from tools import Tools


class ShellAgentState(AgentState):
    user: str
    user_dir: str
    localhost: str
    current_dir: str
    is_root: bool
    command_output: str


class Agent:
    def __init__(self, thread_id: str = "default") -> None:
        self.config = RunnableConfig(configurable={"thread_id": thread_id})

        self.model = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
            model=MODEL,
            temperature=0,
            seed=42,
        )
        self.summarize_model = ChatOpenAI(
            base_url="https://localhost:11434/v1",
            model=SUMMARY_MODEL,
        )

        os.makedirs(thread_id, exist_ok=True)
        self.checkpoint_path = os.path.join(thread_id, "checkpoint.db")
        self.checkpointer = SqliteSaver(
            sqlite3.connect(self.checkpoint_path, check_same_thread=False)
        )

        self.tools = Tools(thread_id)

        # Load data from last saved checkpoint
        saved_checkpoint = self.checkpointer.get(self.config)
        if saved_checkpoint:
            saved_state = saved_checkpoint["channel_values"]
            self.total_tokens = self._token_counter(saved_state["messages"])
            try:
                saved_state = saved_state["structured_response"]
            except KeyError as e:
                raise KeyError(
                    f"{MODEL} doesn't support/didn't use [structured responses](https://docs.langchain.com/oss/python/langchain/structured-output)\n{e}"
                )
            self.current_state = {
                "user": saved_state["user"],
                "user_dir": saved_state["user_dir"],
                "localhost": saved_state["localhost"],
                "current_dir": saved_state["current_dir"],
                "is_root": saved_state["is_root"],
            }
        # Otherwise use default values
        else:
            self.current_state = {
                "user": "root",
                "user_dir": "/root",
                "localhost": "svr01",
                "current_dir": "/root",
                "is_root": True,
            }
            self.total_tokens = 0

        self.shell_prompt = self._shell_prompt(self.current_state)

        self.agent = create_agent(
            model=self.model,
            tools=self.tools.get_tools(),
            system_prompt=SYSTEM_PROMPT,
            response_format=ToolStrategy(ShellAgentState),
            state_schema=ShellAgentState,
            checkpointer=self.checkpointer,
            middleware=[
                SummarizationMiddleware(
                    model=self.summarize_model,
                    token_counter=self._token_counter,
                    summary_prompt=SUMMARY_PROMPT,
                    trigger=("tokens", 10000),
                    keep=("messages", 1),
                ),
            ],
        )

    def _token_counter(self, messages):
        tokens = 0
        for msgi in range(len(messages) - 1, 0, -1):
            msg = messages[msgi]
            # Count last input tokens
            if isinstance(msg, HumanMessage):
                tokens += len(msg.content)
            # Get last total tokens
            elif isinstance(msg, AIMessage):
                input_tokens = int(tokens / 4)
                last_tokens = msg.response_metadata["token_usage"]["total_tokens"]
                return last_tokens + input_tokens
        return 0

    def _shell_prompt(self, state: dict) -> str:
        prompt = f"{state['user']}@{state['localhost']}:{state['current_dir']}{'#' if state['is_root'] else '$'} "
        return prompt.replace(state["user_dir"], "~", 1)

    def chat(self, query: str) -> Tuple[str, int]:
        last_id = self.tools.set_global_history(query)

        result = self.agent.invoke(
            {"messages": [{"role": "user", "content": query}]},
            self.config,
        )

        try:
            structured_output = result["structured_response"]
        except KeyError as e:
            raise KeyError(
                f"{MODEL} doesn't support/didn't use [structured responses](https://docs.langchain.com/oss/python/langchain/structured-output)\n{e}"
            )

        self.current_state = {
            "user": structured_output["user"],
            "user_dir": structured_output["user_dir"],
            "localhost": structured_output["localhost"],
            "current_dir": structured_output["current_dir"],
            "is_root": structured_output["is_root"],
            "command_output": structured_output["command_output"],
        }

        self.tools.update_history_output(last_id, structured_output["command_output"])

        self.shell_prompt = self._shell_prompt(self.current_state)

        self.total_tokens = self._token_counter(result["messages"])

        return structured_output["command_output"], self.total_tokens


if __name__ == "__main__":
    agent = Agent()
    while True:
        q = input(agent.shell_prompt)
        if q != "":
            response = agent.chat(q)
            if response[0] != "":
                print(response[0])
