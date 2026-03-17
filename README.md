# Why You Should Use AnyIO (And Why You Might Already Have It)

## Abstract

Async Python is fragmented—but you probably already have the solution installed. AnyIO is a portability layer for asyncio and Trio that fixes critical cancellation bugs and provides structured concurrency. If you use httpx, FastAPI, or Jupyter, AnyIO is already in your environment powering your HTTP clients, web frameworks, and notebooks.

This talk reveals AnyIO's level-triggered cancellation (fixing asyncio's dangerous edge-triggered behavior that causes silent hangs), demonstrates structured concurrency patterns with task groups, and shows practical tools like memory object streams for producer-consumer workflows. You'll learn why major libraries chose AnyIO—and how to use it directly for more reliable concurrent code.

Target audience: Intermediate Python developers working with async code who want portable, maintainable concurrent programs.

## Description

### Talk Structure (40 minutes)

**1. The Problem with `asyncio.create_task()` (9 min)**
- Go statements break everything: one-way jumps, no guaranteed cleanup
- Four core problems: functions aren't black boxes, resource cleanup breaks, error handling breaks, can't tell if code is finished
- The root cause: unstructured concurrency
- Real-world consequences in data pipelines
- The solution: structured concurrency with task groups

**2. Level vs Edge Cancellation (9 min)**
- Edge-triggered cancellation in asyncio: cancellation is a one-shot signal that can be swallowed
- Live bug demo: asyncio code that hangs vs AnyIO code that fails fast
- Why this causes production failures: timeouts that don't timeout, cleanup that never happens
- How AnyIO's level-triggered cancellation ensures cancelled tasks stay cancelled

**3. Building Real Applications (10 min)**
- Memory object streams: producer-consumer with backpressure by default (vs asyncio.Queue)
- Getting results from task groups: nonlocal pattern vs memory streams
- Buffered byte streams: why AnyIO adds value even on Trio
- `anyio.Path`: truly async file operations
- pytest plugin: test under both asyncio and Trio

**4. Ecosystem & Migration (6 min)**
- Major adopters revealed by pipdeptree
- Migration patterns: `asyncio.gather()` → task groups, `asyncio.Queue` → memory streams
- Why PyPI distribution matters: bugfixes on all Python versions
- Why data scientists should care

**5. The Hidden Dependency Reveal (5 min)**
- Live demo: `pipdeptree -p anyio -r` reveals dozens of packages depend on AnyIO
- Why httpx, FastAPI, Jupyter, and Anthropic's MCP SDK chose AnyIO
- You already have it installed—now you know how to use it directly

**6. Q&A (1 min)**

### Prior Knowledge Expected

- Basic understanding of async/await syntax
- Familiarity with asyncio (having used `asyncio.create_task()` or `asyncio.gather()`)
- Experience with data processing or web development helpful but not required

### Key Takeaways

1. Understanding why edge-triggered cancellation causes bugs and how level-triggered cancellation fixes them
2. Practical patterns for getting results from concurrent tasks (nonlocal vs memory streams)
3. Migration paths from common asyncio patterns to AnyIO
4. Awareness that AnyIO is already powering much of the Python async ecosystem

### Why This Matters to PyData

Async programming appears in data workflows everywhere: parallel data fetching, ETL pipelines, ML model serving, streaming data processing. AnyIO's cancellation semantics and memory streams provide battle-tested patterns for these workflows. The talk bridges "I write async/await sometimes" and "I understand why my async code has weird timeout bugs."

Code examples will be available in a public repository before the conference.

### Speaker Notes

I am diagnosed with schizoaffective disorder and autism spectrum disorder. I would appreciate a mid-day time slot (when my antipsychotics are least sedating) and would welcome any mentorship support available for speakers. This will be my second technical talk ever.

I would also appreciate a laser pointer to highlight blocks of example code during the presentation.
