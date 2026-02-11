# Abstract

Async Python is powerful but fragmented—choosing asyncio or Trio often locks you into that ecosystem. Enter AnyIO: the compatibility layer that lets you write async code working seamlessly across both frameworks. Here's the surprise: **you probably already have it installed**.

Check your environment right now. If you're using `httpx`, `starlette`, `fastapi`, `jupyter-server`, or Anthropic's MCP SDK, AnyIO is already there—quietly powering your HTTP clients, web frameworks, notebooks, and AI infrastructure. Major libraries have converged on AnyIO as their async foundation, making it one of Python's most widely deployed packages you've never directly imported.

But AnyIO isn't just about compatibility. It fundamentally fixes one of asyncio's most dangerous design flaws: **edge-triggered cancellation**. While asyncio's cancellation can be silently swallowed or lost, AnyIO implements **level-triggered cancellation**—ensuring that when something is cancelled, it stays cancelled. This single design decision prevents entire classes of bugs that have plagued production async code for years.

This talk reveals why AnyIO has become the de facto standard for portable async code, and shows you how its cancellation semantics and structured concurrency patterns solve problems you didn't even know you had.

# Description

### Who This Talk Is For

Intermediate Python developers working with async code who want to write more portable, maintainable concurrent programs. Data engineers building pipelines, backend developers using async frameworks, ML engineers serving models, or anyone who's struggled with async/await patterns will find immediate practical value. 

If you use Jupyter notebooks, FastAPI, or modern HTTP clients, **you're already running AnyIO**—this talk shows you how to harness its power directly.

### Talk Outline (40 minutes)

**1. The Hidden Dependency Web (5 min)**
- **Live demo: The dependency reveal**
  - `pip install httpx starlette jupyter mcp pipdeptree`
  - `pipdeptree -p anyio -r`
  - Watch the tree unfold: dozens of packages you use daily depend on AnyIO

```
pipdeptree -p anyio -r
anyio==4.12.1
├── starlette==0.52.1 [requires: anyio>=3.6.2,<5]
│   ├── mcp==1.26.0 [requires: starlette>=0.27]
│   └── sse-starlette==3.2.0 [requires: starlette>=0.49.1]
│       └── mcp==1.26.0 [requires: sse-starlette>=1.6.1]
├── httpx==0.28.1 [requires: anyio]
│   ├── mcp==1.26.0 [requires: httpx>=0.27.1]
│   └── jupyterlab==4.5.4 [requires: httpx>=0.25.0,<1]
│       ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
│       │   └── jupyter==1.1.1 [requires: notebook]
│       └── jupyter==1.1.1 [requires: jupyterlab]
├── mcp==1.26.0 [requires: anyio>=4.5]
├── sse-starlette==3.2.0 [requires: anyio>=4.7.0]
│   └── mcp==1.26.0 [requires: sse-starlette>=1.6.1]
└── jupyter_server==2.17.0 [requires: anyio>=3.1.0]
    ├── notebook==7.5.3 [requires: jupyter_server>=2.4.0,<3]
    │   └── jupyter==1.1.1 [requires: notebook]
    ├── jupyter-lsp==2.3.0 [requires: jupyter_server>=1.1.2]
    │   └── jupyterlab==4.5.4 [requires: jupyter-lsp>=2.0.0]
    │       ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
    │       │   └── jupyter==1.1.1 [requires: notebook]
    │       └── jupyter==1.1.1 [requires: jupyterlab]
    ├── jupyterlab==4.5.4 [requires: jupyter_server>=2.4.0,<3]
    │   ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
    │   │   └── jupyter==1.1.1 [requires: notebook]
    │   └── jupyter==1.1.1 [requires: jupyterlab]
    ├── jupyterlab_server==2.28.0 [requires: jupyter_server>=1.21,<3]
    │   ├── notebook==7.5.3 [requires: jupyterlab_server>=2.28.0,<3]
    │   │   └── jupyter==1.1.1 [requires: notebook]
    │   └── jupyterlab==4.5.4 [requires: jupyterlab_server>=2.28.0,<3]
    │       ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
    │       │   └── jupyter==1.1.1 [requires: notebook]
    │       └── jupyter==1.1.1 [requires: jupyterlab]
    └── notebook_shim==0.2.4 [requires: jupyter_server>=1.8,<3]
        ├── notebook==7.5.3 [requires: notebook_shim>=0.2,<0.3]
        │   └── jupyter==1.1.1 [requires: notebook]
        └── jupyterlab==4.5.4 [requires: notebook_shim>=0.2]
            ├── notebook==7.5.3 [requires: jupyterlab>=4.5.3,<4.6]
            │   └── jupyter==1.1.1 [requires: notebook]
            └── jupyter==1.1.1 [requires: jupyterlab]
```
  
- **The transitive dependency explosion:**
  - httpx → httpcore → anyio
  - starlette → anyio (and therefore FastAPI → starlette → anyio)
  - ipython → ipykernel → jupyter-client → anyio
  - mcp → anyio (Anthropic's Model Context Protocol SDK)
  - And dozens more in the tree
  
- **The scale of adoption:**
  - httpx: 12M+ downloads/month
  - starlette/FastAPI: millions of API requests daily
  - IPython/Jupyter: every notebook you run
  - The silent infrastructure layer powering modern Python async
  
- Why major libraries chose AnyIO (spoiler: it's not just compatibility)

**2. The Cancellation Problem Nobody Talks About (9 min)**
*This is the most important part of AnyIO and where the deepest work went*

- **Edge-triggered cancellation in asyncio: The footgun**
  - What edge-triggered means: cancellation is a one-shot signal
  - Live bug demo: Catching CancelledError and continuing—asyncio lets you!
  - Real production failure: How edge cancellation causes silent hangs
  - The `try/except CancelledError` trap that looks safe but isn't
  
- **Level-triggered cancellation in AnyIO: The fix**
  - What level-triggered means: cancellation is a persistent state
  - How AnyIO ensures cancelled tasks stay cancelled
  - The checkpoint system: `await anyio.sleep(0)` re-raises if you're cancelled
  - Live demo: The same buggy code in asyncio vs AnyIO—one hangs, one fails fast
  
- **Why this matters in production**
  - Data pipelines that hang instead of timing out
  - Web requests that never complete after client disconnect
  - Resource cleanup that never happens
  - How FastAPI/Starlette benefit from this without most users knowing

- **The implementation challenge**
  - Why this was hard to build on top of asyncio
  - The CancelScope abstraction and its guarantees
  - Edge case handling that took years to get right

**3. Structured Concurrency: Practical Patterns (9 min)**
- Why unstructured async is dangerous (building on the cancellation story)
- Task groups: automatic cleanup, error propagation, and resource safety
- How task groups use cancel scopes internally

- **Getting results from tasks: The asyncio → AnyIO transition**
  - The surprise: `task_group.start_soon()` returns `None` (unlike `asyncio.create_task()`)
  - Why: enforces structured concurrency—no task outlives its task group
  - **Pattern 1: Using nonlocal variables**
    ```python
    results = []
    async with anyio.create_task_group() as tg:
        for url in urls:
            tg.start_soon(fetch_and_append, url, results)
    # All tasks complete here, results is populated
    ```
  - **Pattern 2: Memory object streams (the proper way)**
    ```python
    send_stream, receive_stream = anyio.create_memory_object_stream()
    async with anyio.create_task_group() as tg:
        for url in urls:
            tg.start_soon(fetch_and_send, url, send_stream.clone())
    # Collect results from receive_stream
    ```
  - Why memory streams are better: backpressure, type safety, clean separation
  - Real example: Parallel data fetching for ML training pipeline
  
- Comparison with `asyncio.gather()`, `asyncio.create_task()`, and manual task tracking
- The problems structured concurrency solves:
  - No more leaked tasks (because cancellation actually works)
  - No more silent failures (because cancellation propagates correctly)
  - Automatic cancellation propagation through nested scopes
  - Clear ownership of concurrent operations
  - Enforced result collection patterns

**4. Building Real Applications with AnyIO (10 min)**
- **Async streams and channels**
  - Memory object streams for producer-consumer patterns
  - Building async queues with backpressure
  - Example: Processing large datasets in chunks with bounded memory
  
- **Practical async patterns**
  - Async file I/O and path operations for data processing
  - Network programming with portable stream APIs and proper timeout handling
  - Cross-platform subprocess management with reliable cancellation
  - Testing async code: AnyIO's pytest plugin (`pytest.mark.anyio`)
  
- **Working with AnyIO in Jupyter**
  - It's already managing your notebook server (as we saw in pipdeptree!)
  - Using task groups in notebook cells
  - Async data loading patterns for interactive analysis
  
- **Integration patterns**
  - Using AnyIO with pandas for async data loading (nonlocal pattern)
  - Async database clients built on AnyIO (why they chose it)
  - Building async ETL pipelines with memory streams
  - ML model serving with async request handling and proper cancellation
  - Streaming results from LLMs with memory object streams

**5. The Ecosystem & Your Migration Path (6 min)**
- **Major adopters deep dive** (as revealed by pipdeptree):
  - **FastAPI/Starlette**: Using `anyio.to_thread.run_sync` and benefiting from level cancellation
  - **HTTPX**: Built entirely on AnyIO streams—the modern async HTTP client
  - **Jupyter/IPython**: jupyter-client, ipykernel, and the entire Jupyter ecosystem
  - **MCP (Model Context Protocol)**: Anthropic's SDK for AI agents
  - **And dozens more**: uvicorn, databases, encode ecosystem
  
- **Migration from asyncio**
  - `asyncio.gather()` → task groups with nonlocal/streams
  - `asyncio.create_task()` → `task_group.start_soon()`
  - `asyncio.Queue` → `anyio.create_memory_object_stream()`
  - Manual timeout handling → cancel scopes
  - Common gotchas and how to avoid them
  
- Why data scientists should care:
  - Your notebooks already depend on it (we just proved it!)
  - Data pipelines that actually respect timeouts
  - Parallel data loading with proper backpressure
  - Building async data APIs with FastAPI
  - Streaming results from ML models efficiently
  
- Performance characteristics: The overhead is negligible (benchmarks included)
- The future: Could Python's asyncio adopt level-triggered cancellation?

**6. Q&A (1 min)**

### Key Takeaways

Attendees will leave with:

1. **Awareness**: Recognition that AnyIO is already in their stack (with proof via pipdeptree)
2. **Deep Understanding**: Why edge-triggered cancellation is dangerous and how level-triggered cancellation fixes it
3. **Practical Skills**: How to get results from task groups (nonlocal vs memory streams)
4. **Patterns**: When to use memory object streams for producer-consumer workflows
5. **Migration Path**: Clear patterns for converting asyncio code to AnyIO
6. **Context**: Understanding of how modern Python infrastructure relies on AnyIO
7. **Confidence**: Ability to write structured async code from day one
8. **Appreciation**: Understanding the engineering effort behind making cancellation and structured concurrency actually work

### Code Examples Repository

All examples will be available before the conference, including:
- The pipdeptree command and sample output for reference
- Edge vs level cancellation demonstrations
- Task group result collection patterns (both nonlocal and streams)
- Memory object stream examples for data pipelines
- Migration patterns from common asyncio code
- Production-ready async data processing templates
- Integration examples with pandas, httpx, and databases

### Why This Matters to PyData

Async programming is everywhere in modern data workflows, but **cancellation bugs and result collection patterns in data pipelines are particularly important**:

- Long-running data processing jobs that hang when they should timeout
- Parallel data fetching that needs proper backpressure (memory streams!)
- ETL pipelines that don't clean up resources properly
- ML training jobs with async data loading
- Streaming data pipelines that need bounded queues
- AI agent workflows with MCP that need reliable cancellation
- Real-time data processing with producer-consumer patterns

AnyIO's level-triggered cancellation and memory streams provide battle-tested patterns that make these workflows actually reliable. The surprise factor—"you already have this installed" **proven live with pipdeptree**—makes it immediately relevant, but the **cancellation semantics and structured patterns are what make it essential**.

Understanding why major libraries like httpx, FastAPI, and jupyter-server chose AnyIO (hint: it's not just the compatibility layer—it's the cancellation semantics and proper abstractions) helps practitioners write better, more reliable data applications.

**The result collection patterns are particularly important** for data scientists who are used to `asyncio.gather()` returning a list. Understanding why `start_soon()` returns `None` and learning the proper patterns (nonlocal for simple cases, memory streams for production) is a crucial part of the AnyIO learning curve that this talk will smooth out.

This talk bridges the gap between "I write async/await sometimes" and "I understand why my async code has weird timeout bugs and how to properly structure concurrent data workflows."

# Notes

I'm flexible on format and can adapt to different time slots. The talk includes:
- Live demonstrations with `pipdeptree -p anyio -r` showing the actual dependency tree
- Real bug reproductions comparing asyncio edge cancellation vs AnyIO level cancellation
- Side-by-side code comparisons of asyncio.gather() vs task groups with results
- Practical examples of memory object streams for data processing
- All code examples will be available in a public GitHub repository

**The pipdeptree demo is particularly powerful** because it makes the "hidden dependency" concept visceral and immediate. Watching the tree unfold on screen, seeing dozens of familiar packages all depending on anyio, creates an "aha!" moment that sets up the rest of the talk perfectly.

The cancellation discussion and result collection patterns are the heart of the talk—this is where the deepest engineering work went in AnyIO, and these are the patterns that most developers don't realize they need until they've been bitten by edge-triggered bugs or struggled with getting data out of concurrent tasks.

**Special note**: The level-triggered cancellation work and the task group design represent years of careful engineering and edge case handling. This talk will honor that effort by explaining not just *what* it does, but *why* it's hard to implement correctly and *how* it prevents real production bugs. The result collection patterns (`start_soon` returning None, memory streams) are deliberate design choices that enforce structured concurrency—I'll explain why these "limitations" are actually features.

This will be my first PyData talk, and I have limited experience with technical presentations. I'm happy to provide references or answer any questions about the proposal.
This will be my second talk ever, my first talk was a completely off the cuff live demo of how Babel.js uses a duffs device to enable async/await on IE10

I'm diagnosed with schizoaffective disorder and autism spectrum disorder so would apreciate a mid-day slot (when my antipsychotics are least sedating) and some mentorship with this proposal
