---
name: consult-en
description: Dungeons & Dragons rules consultation (English). Use when the user asks about D&D 5e rules, or wants to take an action and needs to know whether it is allowed. If the user's current input is in English, use this skill.
whenToUse: The user asks a D&D rules question or states an action intent.
---

# Consultation Flow

Complete the three stages below in order. The detailed instructions for each stage live under `references/`.
**Read the corresponding file with the read tool before executing that stage** — these files are not injected into context automatically.

## 1. Decide

Read `references/decision.md`.

Determine which category the user's input falls into:

- **Rulebook lookup needed** → go to stage 2
- **No lookup needed** (the question is basic, or it is only a follow-up about the existing context) → skip to stage 3
- **Entirely unrelated to Dungeons & Dragons** → decline politely as described in `decision.md`, and stop

## 2. Retrieve

Read `references/rag-query.md`.

Rewrite the user's natural language into query keywords following the rules there, then call the `search_rules` tool.
You may call it more than once (three calls maximum in total).

## 3. Answer

Read `references/output.md`.

Combine the retrieved rule fragments with the conversation context to produce the final reply.
