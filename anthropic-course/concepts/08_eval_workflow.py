"""
Lesson 08 — "A typical eval workflow (5 steps)" — GEMINI port.
Pairs with 08_eval_workflow_claude.py. Explainer: 08_eval_workflow.md.

Draft prompt -> dataset -> run -> LLM grader (1-10) -> change prompt & compare averages.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/08_eval_workflow.py
"""

import re
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


def add_user_message(contents, text):
    contents.append({"role": "user", "parts": [{"text": text}]})


def chat(contents, system=None):
    cfg = types.GenerateContentConfig(system_instruction=system)
    return client.models.generate_content(model=MODEL, contents=contents, config=cfg).text


DATASET = ["What's 2+2?", "How do I make oatmeal?", "How far away is the Moon?"]
BASELINE = "Please answer the user's question:\n\n{question}"
IMPROVED = "Please answer the user's question:\n\n{question}\n\nAnswer the question with ample detail."
GRADER_SYS = (
    "You are a strict grader. Given a QUESTION and an ANSWER, rate the answer's quality from 1 to 10 "
    "(10 = perfect, complete, correct). Respond with ONLY the integer, nothing else."
)


def answer(question, template):
    contents = []
    add_user_message(contents, template.format(question=question))
    return chat(contents)


def grade(question, ans):
    contents = []
    add_user_message(contents, f"QUESTION: {question}\n\nANSWER: {ans}")
    raw = chat(contents, system=GRADER_SYS)
    m = re.search(r"10|[1-9]", raw)
    return int(m.group()) if m else 0


def eval_prompt(template, label):
    scores = []
    for q in DATASET:
        s = grade(q, answer(q, template))
        scores.append(s)
        print(f"  [{label}] {q[:28]:<28} -> {s}/10")
    avg = sum(scores) / len(scores)
    print(f"  [{label}] AVERAGE = {avg:.2f}\n")
    return avg


if __name__ == "__main__":
    base = eval_prompt(BASELINE, "baseline")
    impr = eval_prompt(IMPROVED, "improved")
    better = "IMPROVED" if impr > base else "BASELINE" if base > impr else "TIE"
    print(f"Winner: {better}  (baseline {base:.2f} vs improved {impr:.2f}) — pick the higher score, keep iterating.")
