---
created: 2026-03-06T04:46:33.101Z
title: Improve parser and planner for better results
area: general
files:
  - src/agentic_workflows/orchestration/langgraph/graph.py
  - src/agentic_workflows/orchestration/langgraph/mission_parser.py
  - src/agentic_workflows/orchestration/langgraph/action_parser.py
---

## Problem

The current action parser and planner produce suboptimal results. The parser (action_parser.py) handles JSON extraction from LLM responses, and the planner logic in graph.py drives multi-step mission planning. There may be opportunities to improve prompt engineering, structured output handling, plan quality, and recovery from bad parses to lead to more reliable and accurate agent task execution.

## Solution

TBD — investigate areas such as:
- Better structured output prompting for the planner
- More robust fallback/retry logic in the parser
- Improved plan decomposition (subtask granularity, ordering)
- Tighter feedback loops between planner and executor
- Eval-driven iteration using audit reports to identify patterns of failure
