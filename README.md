# Why You Should Use AnyIO (And Why You Might Already Have It)

## Slides

This repository contains six sets of slides built with [Marp](https://marp.app/):

- **`slides.md`** — Full-length talk: "Why you should use AnyIO and why you might already have it installed"
- **`slides_40.md`** — Trimmed 40-minute version of the full talk
- **`lightning.md`** — Lightning talk edition (~4 minutes)
- **`slides_part1.md`** — Part 1 of 3: asyncio ≠ async/await + Structured Concurrency
- **`slides_part2.md`** — Part 2 of 3: Level-Triggered Cancellation + Shielding
- **`slides_part3.md`** — Part 3 of 3: AnyIO Features + Why You Already Have It

PDF and PPTX files are generated automatically by CI on every push to `default` and attached to a [GitHub Release](https://github.com/graingert/anyio_why_already_slides/releases).

### Generating PDFs and PPTX locally

```
for deck in slides slides_40 lightning slides_part1 slides_part2 slides_part3; do
  npx @marp-team/marp-cli@latest ${deck}.md --pdf  --html
  npx @marp-team/marp-cli@latest ${deck}.md --pptx --html
done
```

## Abstract

Async Python is fragmented—but you probably already have the solution installed. AnyIO is a portability layer for asyncio and Trio that fixes critical cancellation bugs and provides structured concurrency. If you use httpx, FastAPI, or Jupyter, AnyIO is already in your environment powering your HTTP clients, web frameworks, and notebooks.

This talk reveals AnyIO's level-triggered cancellation (fixing asyncio's dangerous edge-triggered behavior that causes silent hangs), demonstrates structured concurrency patterns with task groups, and shows practical tools like memory object streams for producer-consumer workflows. You'll learn why major libraries chose AnyIO—and how to use it directly for more reliable concurrent code.

Target audience: Intermediate Python developers working with async code who want portable, maintainable concurrent programs.

## Description

### Talk Structure (40 minutes)

**1. Misconception: `asyncio` != `async`/`await` (1 min)**
- `async`/`await` is syntactic sugar over generators — no event loop required
- AnyIO dispatches to the right backend at runtime

**2. The Problems with `asyncio.create_task()` (8 min)**
- Go statements break everything: one-way jumps, no guaranteed cleanup
- Four core problems: functions aren't black boxes, resource cleanup breaks, error handling breaks, can't tell if code is finished
- The root cause: unstructured concurrency
- Real-world consequences in data pipelines
- The solution: structured concurrency with task groups
- "But I want to return without waiting!": using a long-lived task group scoped to the application lifetime (FastAPI lifespan example with `except* Done` and `cancel_scope.cancel()` alternatives)

**3. Two Most Important Reasons to Use AnyIO (1 min)**
- Incrementally adoptable: drop into an existing asyncio codebase
- Cancellations are level-triggered

**4. Level vs Edge Cancellation (8 min)**
- Level-triggered cancellation: every `await` in a cancelled `CancelScope` raises `CancelledError`
- Edge-triggered cancellation in asyncio: `CancelledError` is a one-shot event that can be swallowed
- Live bug demo: asyncio code that hangs vs AnyIO code that fails fast
- Deadlocks in asyncio caused by edge cancellation
- `asyncio.shield` (duct-tape approach) vs AnyIO shielded `CancelScope` (structured approach)

**5. Building Real Applications (10 min)**
- Memory object streams: producer-consumer with backpressure by default (vs `asyncio.Queue`)
- "If I'm already using Trio, I don't need AnyIO" — rebuttal: AnyIO adds buffered byte streams, stapled streams, memory object streams, and more on top of Trio
- Buffered byte streams: why AnyIO adds value even on Trio
- `anyio.Path`: truly async file operations
- pytest plugin: test under both asyncio and Trio

**6. Ecosystem & The Hidden Dependency Reveal (6 min)**
- The advantage of being on PyPI: bugfixes on all Python versions
- Live demo: `pipdeptree -p anyio -r` reveals dozens of packages depend on AnyIO
- Why httpx, FastAPI, Jupyter, and Anthropic's MCP SDK chose AnyIO
- You already have it installed—now you know how to use it directly

**7. Q&A (6 min)**

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
