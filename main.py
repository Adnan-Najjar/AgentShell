from langchain_openai import ChatOpenAI
from langchain.agents import create_agent, AgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import SecretStr
from typing import Tuple
import sqlite3
import os
from utils import SYSTEM_PROMPT, MODEL


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

        self.checkpointer = SqliteSaver(
            sqlite3.connect(f"{thread_id}_checkpoint.db", check_same_thread=False)
        )

        # Load data from last saved checkpoint
        saved_checkpoint = self.checkpointer.get(self.config)
        if saved_checkpoint:
            saved_state = saved_checkpoint["channel_values"]
            try:
                saved_state = saved_state["structured_response"]
            except KeyError as e:
                raise KeyError(f"{MODEL} doesn't support/didn't use [structured responses](https://docs.langchain.com/oss/python/langchain/structured-output)\n{e}")
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

        self.shell_prompt = self._shell_prompt(self.current_state)

        # TODO: Make system prompt dynamic based on current state from AgentState
        self.agent = create_agent(
            model=self.model,
            system_prompt=SYSTEM_PROMPT, # TODO: make system prompt dynamic
            response_format=ToolStrategy(ShellAgentState),
            state_schema=ShellAgentState,
            checkpointer=self.checkpointer,
            # Summerization middleware for context size managment
        )

    def _shell_prompt(self, state: dict) -> str:
        prompt = f"{state['user']}@{state['localhost']}:{state['current_dir']}{'#' if state['is_root'] else '$'} "
        return prompt.replace(state["user_dir"], "~", 1)

    def chat(self, query: str) -> Tuple[str, int]:
        result = self.agent.invoke(
            {"messages": [{"role": "user", "content": query}]},
            self.config,
        )

        try:
            structured_output = result["structured_response"]
        except KeyError as e:
            raise KeyError(f"{MODEL} doesn't support/didn't use [structured responses](https://docs.langchain.com/oss/python/langchain/structured-output)\n{e}")

        self.current_state = {
            "user": structured_output["user"],
            "user_dir": structured_output["user_dir"],
            "localhost": structured_output["localhost"],
            "current_dir": structured_output["current_dir"],
            "is_root": structured_output["is_root"],
            "command_output": structured_output["command_output"],
        }

        self.shell_prompt = self._shell_prompt(self.current_state)

        total_tokens = result["messages"][-2].response_metadata['token_usage']['total_tokens']

        return structured_output["command_output"], total_tokens


if __name__ == "__main__":
    agent = Agent()
    while True:
        q = input(agent.shell_prompt)
        if q != "":
            response = agent.chat(q)
            if response != "":
                print(response[0])
