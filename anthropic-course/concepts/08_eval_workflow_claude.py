"""
Lesson 08 — "A typical eval workflow (5 steps)" — CLAUDE version.
Pairs with 08_eval_workflow.py (Gemini). Explainer: 08_eval_workflow.md.

The 5 steps: (1) draft a prompt (2) make an eval dataset (3) feed each case through the model
(4) feed the answer through a GRADER that scores 1-10 (5) change the prompt & repeat, comparing
average scores. The grader here is an LLM-as-judge — the same idea as your P6 dispute_judge.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/08_eval_workflow_claude.py
"""

import re
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"


def text_of(message):
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


def add_user_message(messages, text):
    messages.append({"role": "user", "content": text})


def chat(messages, system=None):
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system
    return text_of(client.messages.create(**params))


# Step 2 — the eval dataset
DATASET = ["What's 2+2?", "How do I make oatmeal?", "How far away is the Moon?"]

# Step 1 — the prompt under test (v1 = baseline, v2 = improved)
BASELINE = "Please answer the user's question:\n\n{question}"
IMPROVED = "Please answer the user's question:\n\n{question}\n\nAnswer the question with ample detail."

# Step 4 — the grader (LLM-as-judge)
GRADER_SYS = (
    "You are a strict grader. Given a QUESTION and an ANSWER, rate the answer's quality from 1 to 10 "
    "(10 = perfect, complete, correct). Respond with ONLY the integer, nothing else."
)


def answer(question, template):                       # Step 3
    messages = []
    add_user_message(messages, template.format(question=question))
    return chat(messages)


def grade(question, ans):                             # Step 4
    messages = []
    add_user_message(messages, f"QUESTION: {question}\n\nANSWER: {ans}")
    raw = chat(messages, system=GRADER_SYS)
    m = re.search(r"10|[1-9]", raw)                   # pull a 1-10 out of the reply
    return int(m.group()) if m else 0


def eval_prompt(template, label):                     # run the whole pipeline for one prompt
    scores = []
    for q in DATASET:
        s = grade(q, answer(q, template))
        scores.append(s)
        print(f"  [{label}] {q[:28]:<28} -> {s}/10")
    avg = sum(scores) / len(scores)
    print(f"  [{label}] AVERAGE = {avg:.2f}\n")
    return avg


if __name__ == "__main__":
    base = eval_prompt(BASELINE, "baseline")          # Step 1-4
    impr = eval_prompt(IMPROVED, "improved")          # Step 5 — change prompt & repeat
    better = "IMPROVED" if impr > base else "BASELINE" if base > impr else "TIE"
    print(f"Winner: {better}  (baseline {base:.2f} vs improved {impr:.2f}) — pick the higher score, keep iterating.")
