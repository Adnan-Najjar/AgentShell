from openai import OpenAI
import re
from typing import List, Dict, Set, Tuple
from utils import *


class FrontendInterface:
    """
    1:1 implementation of the Adaptive Context LLM Honeypot from the IEEE paper:
    "On Designing Low-Risk Honeypots Using Generative Pre-Trained Transformer Models With Curated Inputs"

    Implements Algorithms 2-4 exactly as described in the paper.
    """

    def __init__(self):
        # Algorithm 2 initialization (lines 1-6)
        self.S: str = SYSTEM_PROMPT  # Persona-defining System Prompt
        self.H0: Set[str] = {"history", "!!", "!-1", "!-2"}  # {q | q requires H1}
        self.C0: Set[str] = {
            "cd",
            "su",
            "mkdir",
            "rmdir",
            "rm",
            "touch",
            "cp",
            "mv",
            "chmod",
            "chown",
            "ln",
            "mount",
            "umount",
            "echo",
            "tar",
            "gzip",
            "gpg",
            "dd",
            "useradd",
            "service",
            "nc",
            "ncat",
            "curl",
            "wget",
            "scp",
            "apt-get",
            "iptables",
            "sysctl",
            "ulimit",
            "fdisk",
            "usermod",
        }  # {q | q affects aq+1}
        self.KillCmds: Set[str] = {"exit", "shutdown", "reboot", "logout"}
        self.C1: List[Dict[str, str]] = (
            []
        )  # {[q', a'] | q' generates a'} (Session Context History)
        self.H1: List[str] = []  # {q' | q'0, q'1, ..., q'n-1} (Session Global History)
        self.MAX_TOKENS: int = 4000
        self.total_tokens = 0

    def count_tokens(self, text: str) -> int:
        """Approximate token count: ~4 characters per token"""
        return len(text) // 4

    def sanitize(self, answer: str) -> str:
        """
        Algorithm 2 Line 13: Sanitize answers to maintain the deception.
        Removes AI-like phrases and unwanted content as described in the paper.
        """
        if not answer:
            return answer

        # Remove code block markers
        answer = answer.replace("```bash\n", "").replace("```", "").strip()

        # Remove common AI prefixes and explanatory phrases
        ai_phrases = [
            r"^As an AI.*?\n",
            r"^I am.*?\n",
            r"^The command.*?\n",
            r"^This will.*?\n",
            r"^Output:.*?\n",
            r"^Here is.*?\n",
            r"^The result.*?\n",
        ]
        for phrase in ai_phrases:
            answer = re.sub(phrase, "", answer, flags=re.IGNORECASE | re.MULTILINE)

        # Remove trailing notes or comments
        answer = re.sub(
            r"\n.*?(note|comment|explanation|as an ai).*?$",
            "",
            answer,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # Clean up extra whitespace
        answer = re.sub(r"\n\s*\n", "\n", answer.strip())

        return answer

    def choose_context(self, q: str) -> List[Dict[str, str]]:  # type: ignore
        """
        Algorithm 3: Choose Context
        Input: S, q, C1, H1, H0
        Output: Chosen History Set

        Line 1: if q ∈ H0 or len(S, C1, q) ≥ MAX_TOKENS then
        Line 2:   return H1
        Line 3: end if
        Line 4: return C1
        """
        # Calculate total tokens for system prompt, context history, and question
        system_tokens = self.count_tokens(self.S)
        question_tokens = self.count_tokens(q)

        # Calculate tokens for C1 (context history)
        c1_tokens = sum(self.count_tokens(msg["content"]) for msg in self.C1)
        total_tokens = system_tokens + c1_tokens + question_tokens

        # Line 1: Check if question requires global history OR exceeds token limit
        if q in self.H0 or total_tokens >= self.MAX_TOKENS:
            # Line 2: Return global history (convert H1 to message format)
            return [{"role": "user", "content": cmd} for cmd in self.H1]

        # Line 4: Return context history
        return self.C1

    def update_context(self, q: str, a: str) -> Tuple[List[Dict[str, str]], List[str]]:
        """
        Algorithm 4: Update Context
        Input: q, a, C1, H1, C0
        Output: C1, H1

        Lines 1-5: Update global history H1
        Lines 6-8: Update context history C1 if q ∈ C0
        """
        # Lines 1-5: Update global history
        new_h1 = self.H1.copy()
        new_h1.append(q)

        # Check if we exceed MAX_TOKENS and remove earliest if needed
        h1_tokens = sum(self.count_tokens(cmd) for cmd in new_h1)
        while h1_tokens >= self.MAX_TOKENS and len(new_h1) > 0:
            removed = new_h1.pop(0)
            h1_tokens -= self.count_tokens(removed)

        # Lines 6-8: Update context history if question affects future outputs
        new_c1 = self.C1.copy()
        if q.split()[0] in self.C0:
            new_c1.append({"role": "user", "content": q})
            new_c1.append({"role": "assistant", "content": a})

            # Also trim C1 if it exceeds token limits
            c1_tokens = sum(self.count_tokens(msg["content"]) for msg in new_c1)
            while c1_tokens >= self.MAX_TOKENS and len(new_c1) > 0:
                removed = new_c1.pop(0)
                c1_tokens -= self.count_tokens(removed["content"])

        return new_c1, new_h1

    def process_question(self, q: str) -> str:
        """
        Core processing following Algorithm 2 lines 11-14

        Line 11: h' ← ChooseContext(S, q, C1, H1, H0)
        Line 12: a ← LLM(S, h', q)
        Line 13: a ← Sanitize(a)
        Line 14: C1, H1 ← UpdateContext(q, a, C1, H1, C0)
        """
        if len(q.strip()) < 1:
            return ""

        # Line 11: Choose context
        h_prime = self.choose_context(q)

        # Line 12: Generate answer using LLM
        try:
            client = OpenAI(
                base_url=BASE_URL,
                api_key=API_KEY,
            )

            # Build messages: system prompt + context + question
            messages = [{"role": "system", "content": self.S}]
            messages.extend(h_prime)
            messages.append({"role": "user", "content": q})

            response = client.chat.completions.create(
                messages=messages,  # type: ignore
                seed=42,
                temperature=0,
                model=MODEL,
            )

            raw_answer = response.choices[0].message.content or ""
            self.total_tokens = response.usage.total_tokens if response.usage else 0

            # Line 13: Sanitize answer
            sanitized_answer = self.sanitize(raw_answer)

            # Line 14: Update contexts
            self.C1, self.H1 = self.update_context(q, sanitized_answer)

            return sanitized_answer

        except Exception as e:
            print(f"Error getting LLM response: {e}")
            return ""

    def run(self, command: str) -> str:
        try:
            # Line 8-9: Check for kill commands
            if command.split()[0] in self.KillCmds:
                return ""

            # Line 11-14: Process question
            answer = self.process_question(command)

            # Line 15: Send answer
            if answer:
                return answer
            return ""
        except:
            return ""

    def chat(self):
        """
        Algorithm 2: Adaptive Context LLM Honeypot
        Lines 7-16: Main loop
        """
        print("$ ", end="", flush=True)

        while True:
            try:
                q = input().strip()

                # Line 8-9: Check for kill commands
                if q.split()[0] in self.KillCmds:
                    break

                # Line 11-14: Process question
                answer = self.process_question(q)

                # Line 15: Send answer
                if answer:
                    print(answer)

                # Line 16: Continue loop
                print("$ ", end="", flush=True)

            except KeyboardInterrupt:
                break
            except EOFError:
                break


if __name__ == "__main__":
    honeypot = FrontendInterface()
    honeypot.chat()
