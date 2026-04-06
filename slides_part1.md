---
marp: true
html: true
---
# Why you should use AnyIO — Part 1 of 3

### asyncio != async/await and Structured Concurrency

https://graingert.co.uk/why-anyio-already

<!-- Part 1 of 3 -->

---

# About Me

<img src="https://avatars.githubusercontent.com/u/413772" alt="graingert" style="display: block; margin: 0 auto;" width="150">

<style scoped>section { font-size: 22px; }</style>

**Networking & async:**
- Core developer of AnyIO, Twisted, and Trio
- CPython triager — asyncio fixes: `TaskGroup` cancellation + refcycles, `asyncio.Timeout` zero-deadline delivery, `staggered_race` task leaks, happy eyeballs refcycles, `sock_connect` UDP
- Proposed asyncio child watcher deprecation (3.12); contributed to asyncio policy system deprecation (3.14)

**Other open source:**
- Member of `PyPy`, `pytest-dev`, `PyCQA`, `Dask`, `jazzband`, `sqlalchemy-redshift`, `canvg` orgs
- Mars 2020 Helicopter Mission contributor
- 1 CVE security advisory credit

<!-- I'm Thomas Grainger, graingert on GitHub. I'm a core dev on AnyIO, Twisted, and Trio. I've contributed to CPython asyncio itself - the happy eyeballs implementation and various TaskGroup fixes. -->

---

<style scoped>section{font-size:22px; padding-top:10px;}</style>

# Part 1 Contents

* `asyncio` != `async`/`await` — the most important take-away (generators all the way down)
* What is AnyIO? How it dispatches. Callables, not coroutines
* The problems with `asyncio.create_task()` — it's a go statement
  * Problem 1: functions aren't black boxes anymore
  * Problem 2: resource cleanup breaks
  * Problem 3: error handling breaks
  * Root cause: unstructured concurrency + real-world consequences
* The fix: structured concurrency with task groups
* Key Takeaway — `asyncio.TaskGroup` too, but not all the way
* Getting a result from a task with `nonlocal`
* "But I want to return without waiting!" — FastAPI lifespan pattern
* Further Reading
* Why you probably already have AnyIO installed

---

# asyncio != async/await

*This is the most important take-away of this presentation*

- `async`/`await` is syntactic sugar over generators - completely decoupled from any event loop
- `async`/`await` also doesn't require async I/O — it's just a way to write coroutines
- **Three separate things:** async I/O (the concept) · `asyncio` (Python's stdlib module) · `async`/`await` (the syntax)
- Twisted, Trio, and Curio all use `async`/`await` with their own event loops
- You can even use `async`/`await` with no event loop at all

<!-- async/await is NOT asyncio. it's just syntax built on top of the generator protocol. any framework can drive coroutines - Twisted, Trio, Curio all do it with completely different event loops. and as I'll show you, you don't even need an event loop. -->

---

# It's Generators All the Way Down

```python
import types

@types.coroutine
def _async_yield(v):
    return (yield v)

async def async_range():
    await _async_yield(1)
    await _async_yield(2)
    await _async_yield(3)
```

```python
coro = async_range()
list(coro.__await__())  # [1, 2, 3] — no asyncio, no event loop
```

`async`/`await` is just the generator protocol. Any framework can drive it.

<!-- grab the __await__ iterator, drain it into a list. no event loop, no scheduler, just generators. this is why multiple async frameworks can use the same async/await syntax. -->

---

# Further Reading: Generator Tricks

- [Generator Tricks for Systems Programmers](https://graingert.co.uk/dabeaz-gen) - `graingert.co.uk/dabeaz-gen`
- [A Curious Course on Coroutines and Concurrency](https://graingert.co.uk/dabeaz-coro) - `graingert.co.uk/dabeaz-coro`
- [Generators: The Final Frontier](https://graingert.co.uk/dabeaz-final) - `graingert.co.uk/dabeaz-final`

<!-- if you want to go deeper on generators, David Beazley's talks are brilliant. these three progressively build from basic generators to full coroutine-based concurrency. -->

---

# What is AnyIO?

**AnyIO is a structured concurrency and I/O library** that works on top of asyncio and Trio.

- **Structured concurrency** — task groups that guarantee tasks can't outlive their scope
- **Level-triggered cancellation** — timeouts that actually work
- **Batteries included** — streams, paths, subprocesses, pytest plugin
- **Incrementally adoptable** — drop it into an existing asyncio codebase; your code automatically works on Trio too

Think of it as: the async standard library that Python should have shipped.

---

# How AnyIO Dispatches to the Right Backend

- Uses `sniffio` to detect which async framework is currently running
- Dispatches to the right backend API - asyncio or Trio
- Similar in approach to `six` (the Python 2/3 compatibility library): write once, run on both

<!-- so how does AnyIO work? it uses sniffio to detect which async framework is running, then dispatches to the right API. similar to how the old `six` library worked for Python 2/3 compat - write once, run on both asyncio and Trio. -->

---

# Callables, Not Coroutines

Trio and AnyIO never require you to create a coroutine — you pass async functions, the framework calls them:

```python
# AnyIO / Trio - pass the function itself ✅
tg.start_soon(myfunc)
anyio.run(main)   # OR trio.run(main) - pick one based on your backend
```

```python
# asyncio - pass a coroutine object ❌
asyncio.create_task(myfunc())
asyncio.run(main())           # note: coroutine, not the function
```

No bare coroutine objects → no `RuntimeWarning: coroutine '...' was never awaited`

<!-- start_soon takes myfunc, not myfunc(). the Trio tutorial deliberately never mentions "coroutine" - you don't need to understand coroutine objects to use structured concurrency. bonus: since you never create coroutine objects yourself, you can't forget to await them. -->

---

# The Problems with `asyncio.create_task()`

## It's a "go statement" - and go statements break everything

<!-- ok this is the core of the talk. asyncio.create_task is what njs calls a "go statement". it's a one-way jump that splits control flow and it's fundamentally broken for the same reasons goto was broken. -->

---

# What's a "go statement"?

```python
# asyncio
asyncio.create_task(myfunc())  # Fire and forget!
# Control returns immediately, myfunc() runs in background
# Golang
go myfunc()  // Same thing
# Python threads  
threading.Thread(target=myfunc).start()  # Also same
```

**Key problem:** Control flow splits with **one-way jump**

-   Parent returns immediately
-   Child jumps to myfunc and runs unsupervised
-   No guaranteed reunion point

<!-- it's the same pattern everywhere - asyncio.create_task, Go's `go` keyword, threading.Thread.start. parent spawns a child and immediately moves on. child runs off unsupervised. no guaranteed reunion point. this one-way jump is the root of all the problems. -->

---

# Problem 1: Functions Aren't Black Boxes Anymore

```python
async def process_data(data):
    # Does this function spawn background tasks?
    # Are they still running after it returns?
    # You have NO IDEA without reading all the source code!
    await some_library_function(data)
    # Function returned... but is it done? 🤷
```

**You can't reason locally about control flow**

Every function call might secretly spawn tasks that outlive the function

<!-- this is devastating for maintainability. when you call a function you have no idea whether it spawned background tasks still running after it returns. you'd have to read every line of source, transitively, to know. completely breaks functions as black boxes. -->

---

# Problem 2: Resource Cleanup Breaks

```python
# This LOOKS safe... (pseudocode)
async with aopen("data.csv") as f:
    await process_file(f)

# File closed here... right?
# But what if process_file did this:
async def process_file(f):
    asyncio.create_task(read_data(f))  # Background task!
    return  # Function returns immediately
# Now: file is CLOSED while background task still uses it
# 💥 Error! (if you're lucky)
```

**The language can't help you with automatic cleanup**

<!-- concrete example. you open a file in an async with block, pass the handle to process_file, block exits, file closes. but if process_file secretly spawned a background task still reading from that handle - boom, error on a closed file. async with can't protect you because it doesn't know about the orphaned task. context managers are broken. -->

---

# Problem 3: Error Handling Breaks

```python
async def background_task():
    raise ValueError("Something went wrong!")

# Start background task
task = asyncio.create_task(background_task())
# Error happens... but where does it go?
# Answer: NOWHERE! It's silently dropped!
# (Maybe printed to console if you're lucky)
```

<!-- errors in background tasks have nowhere to go. in sync Python, exceptions propagate up the call stack automatically. but a fire-and-forget task is an orphan - the error gets silently dropped. maybe asyncio prints a warning to the console if you're lucky, but your program keeps running in a broken state. -->

---

# Why Errors Can't Propagate

**Exceptions can't propagate because there's no stack to unwind**

Compare to regular Python:

```python
def my_function():
    raise ValueError("Something went wrong!")

my_function()  # Exception propagates to caller automatically
```

<!-- compare: in sync Python when a function raises, the exception propagates to the caller. that's just how the call stack works. create_task breaks this. -->

---

# The Root Cause: Unstructured Concurrency

<svg font-family="'Courier New', monospace" style="display: block; margin: 0 auto;" viewBox="0 0 600 340" width="700" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="asyncio-create-task-bgGrad" x1="0" x2="1" y1="0" y2="1">
<stop offset="0%" stop-color="#f6f8fa"/>
<stop offset="100%" stop-color="#ffffff"/>
</linearGradient>
<marker id="asyncio-create-task-arrowBlue" markerHeight="7" markerWidth="10" orient="auto" refX="9" refY="3.5">
<polygon fill="#2563eb" points="0 0, 10 3.5, 0 7"/>
</marker>
<marker id="asyncio-create-task-arrowRed" markerHeight="7" markerWidth="10" orient="auto" refX="9" refY="3.5">
<polygon fill="#dc2626" points="0 0, 10 3.5, 0 7"/>
</marker>
</defs>
<rect fill="url(#asyncio-create-task-bgGrad)" height="340" rx="12" width="600"/>
<text fill="#1f2328" font-size="16" font-weight="700" letter-spacing="0.5" text-anchor="middle" x="300" y="36">asyncio.create_task() control flow</text>
<line stroke="#d0d7de" stroke-width="1" x1="24" x2="576" y1="50" y2="50"/>
<rect fill="#dbeafe" height="64" rx="8" stroke="#2563eb" stroke-width="2" width="210" x="195" y="66"/>
<text fill="#1e3a5f" font-size="18" font-weight="700" text-anchor="middle" x="300" y="94">Parent task</text>
<text fill="#2563eb" font-size="14" text-anchor="middle" x="300" y="118">async def main():</text>
<line marker-end="url(#asyncio-create-task-arrowBlue)" stroke="#2563eb" stroke-width="2.5" x1="300" x2="300" y1="130" y2="168"/>
<text fill="#c2410c" font-size="15" font-weight="700" text-anchor="middle" x="300" y="157">create_task()</text>
<line stroke="#64748b" stroke-width="2.5" x1="150" x2="440" y1="182" y2="182"/>
<line marker-end="url(#asyncio-create-task-arrowBlue)" stroke="#2563eb" stroke-width="2.5" x1="195" x2="195" y1="182" y2="218"/>
<line marker-end="url(#asyncio-create-task-arrowRed)" stroke="#dc2626" stroke-width="2.5" x1="395" x2="395" y1="182" y2="218"/>
<rect fill="#f0fdf4" height="64" rx="8" stroke="#16a34a" stroke-width="2" width="190" x="100" y="224"/>
<text fill="#14532d" font-size="16" text-anchor="middle" x="195" y="253">Parent returns</text>
<text fill="#16a34a" font-size="15" font-weight="700" text-anchor="middle" x="195" y="275">[OK]</text>
<rect fill="#fef2f2" height="64" rx="8" stroke="#dc2626" stroke-width="2" width="260" x="300" y="224"/>
<text fill="#7f1d1d" font-size="17" font-weight="700" text-anchor="middle" x="430" y="250">Child task</text>
<text fill="#991b1b" font-size="13" text-anchor="middle" x="430" y="274">(orphaned, unsupervised)</text>
<text fill="#9ca3af" font-size="12" x="18" y="330">asyncio</text>
<text fill="#9ca3af" font-size="12" x="534" y="330">CPython</text>
</svg>

⚠ no await, no supervision, no cancellation - exceptions silently swallowed

consider: `anyio.create_task_group()` for structured concurrency

<!-- this diagram shows it. create_task launches a task that runs off on its own with no structural connection back to the parent. no guaranteed reunion point. unstructured concurrency - the concurrent equivalent of goto spaghetti. -->

---

# Real-World Consequences

### In asyncio programs:

❌ **Resource leaks** - Files/sockets stay open because cleanup is manual\
❌ **Silent failures** - Errors in background tasks get dropped\
❌ **Shutdown hangs** - Can't wait for "done" because tasks are invisible\
❌ **Operations on closed files** - Tasks outlive the data they operate on

### In data pipelines specifically:

❌ **Timeouts don't work** - Can't cancel tasks you've lost track of\
❌ **Can't reason about code** - Every function is a potential landmine

<!-- these aren't theoretical. people hit these in production every day. resource leaks, silent failures, shutdown hangs, operations on closed files. and for data pipelines: timeouts are meaningless because you can't cancel tasks you've lost track of. -->

---

# Structured Concurrency with Task Groups

*"structured" = tasks have a guaranteed reunion point with their parent*

```python
# asyncio - UNSTRUCTURED (bad)
async def unstructured():
    asyncio.create_task(myfunc())  # Fire and forget
    asyncio.create_task(other())   # Where do errors go?
    return  # Are we done? Who knows!

# AnyIO - STRUCTURED (good)
async def structured():
    async with anyio.create_task_group() as tg:
        tg.start_soon(myfunc)
        tg.start_soon(other)
    # BLOCKED HERE until all tasks finish
    # All errors propagated automatically
    # All cleanup happens automatically
    return  # NOW we're actually done
```

<!-- here's the fix: task groups. you can't exit the async with block until ALL child tasks have finished. errors propagate automatically. cleanup happens automatically. when the function returns, it's actually done. this is structured concurrency - same revolution that if/while/for brought to control flow. -->

---

<style scoped>section { padding-top: 40px; }</style>

# The Fix: Structured Concurrency

<svg font-family="'Courier New', monospace" style="display: block; margin: 0 auto;" viewBox="0 0 780 480" width="700" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="anyio-create-task-group-bgGrad" x1="0" x2="1" y1="0" y2="1">
<stop offset="0%" stop-color="#f6f8fa"/>
<stop offset="100%" stop-color="#ffffff"/>
</linearGradient>
<marker id="anyio-create-task-group-arrowBlue" markerHeight="7" markerWidth="10" orient="auto" refX="9" refY="3.5">
<polygon fill="#2563eb" points="0 0, 10 3.5, 0 7"/>
</marker>
<marker id="anyio-create-task-group-arrowGreen" markerHeight="7" markerWidth="10" orient="auto" refX="9" refY="3.5">
<polygon fill="#16a34a" points="0 0, 10 3.5, 0 7"/>
</marker>
<marker id="anyio-create-task-group-arrowPurple" markerHeight="7" markerWidth="10" orient="auto" refX="9" refY="3.5">
<polygon fill="#7c3aed" points="0 0, 10 3.5, 0 7"/>
</marker>
<marker id="anyio-create-task-group-arrowGold" markerHeight="7" markerWidth="10" orient="auto" refX="9" refY="3.5">
<polygon fill="#b45309" points="0 0, 10 3.5, 0 7"/>
</marker>
</defs>
<rect fill="url(#anyio-create-task-group-bgGrad)" height="480" rx="12" width="780"/>
<text fill="#1f2328" font-size="16" font-weight="700" letter-spacing="0.5" text-anchor="middle" x="390" y="36">anyio.create_task_group() control flow</text>
<line stroke="#d0d7de" stroke-width="1" x1="24" x2="756" y1="52" y2="52"/>
<rect fill="#dbeafe" height="60" rx="8" stroke="#2563eb" stroke-width="2" width="200" x="290" y="68"/>
<text fill="#1e3a5f" font-size="17" font-weight="700" text-anchor="middle" x="390" y="95">Parent task</text>
<text fill="#2563eb" font-size="13" text-anchor="middle" x="390" y="117">async def main():</text>
<line marker-end="url(#anyio-create-task-group-arrowBlue)" stroke="#2563eb" stroke-width="2.5" x1="390" x2="390" y1="128" y2="152"/>
<rect fill="#ede9fe" height="48" rx="8" stroke="#7c3aed" stroke-width="2" width="350" x="215" y="158"/>
<text fill="#4c1d95" font-size="14" font-weight="700" text-anchor="middle" x="390" y="179">async with</text>
<text fill="#4c1d95" font-size="14" text-anchor="middle" x="390" y="197">create_task_group() as tg</text>
<line stroke="#7c3aed" stroke-width="2" x1="390" x2="390" y1="206" y2="270"/>
<text fill="#c2410c" font-size="14" font-weight="600" text-anchor="middle" x="390" y="228">tg.start_soon(task1)</text>
<text fill="#c2410c" font-size="14" font-weight="600" text-anchor="middle" x="390" y="248">tg.start_soon(task2)</text>
<line stroke="#7c3aed" stroke-width="2.5" x1="90" x2="690" y1="270" y2="270"/>
<line marker-end="url(#anyio-create-task-group-arrowBlue)" stroke="#2563eb" stroke-width="2.5" x1="155" x2="155" y1="270" y2="300"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#16a34a" stroke-width="2.5" x1="390" x2="390" y1="270" y2="300"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#16a34a" stroke-width="2.5" x1="625" x2="625" y1="270" y2="300"/>
<rect fill="#f8fafc" height="58" rx="8" stroke="#2563eb" stroke-dasharray="6,3" stroke-width="1.5" width="190" x="60" y="306"/>
<text fill="#475569" font-size="13" text-anchor="middle" x="155" y="331">Parent body</text>
<text fill="#2563eb" font-size="13" text-anchor="middle" x="155" y="351">(runs concurrently)</text>
<rect fill="#dcfce7" height="58" rx="8" stroke="#16a34a" stroke-width="2" width="190" x="295" y="306"/>
<text fill="#14532d" font-size="16" font-weight="700" text-anchor="middle" x="390" y="333">Child task 1</text>
<text fill="#14532d" font-size="13" text-anchor="middle" x="390" y="353">task1()</text>
<rect fill="#dcfce7" height="58" rx="8" stroke="#16a34a" stroke-width="2" width="190" x="530" y="306"/>
<text fill="#14532d" font-size="16" font-weight="700" text-anchor="middle" x="625" y="333">Child task 2</text>
<text fill="#14532d" font-size="13" text-anchor="middle" x="625" y="353">task2()</text>
<line stroke="#2563eb" stroke-width="2" x1="155" x2="155" y1="364" y2="392"/>
<line stroke="#16a34a" stroke-width="2" x1="390" x2="390" y1="364" y2="392"/>
<line stroke="#16a34a" stroke-width="2" x1="625" x2="625" y1="364" y2="392"/>
<line stroke="#b45309" stroke-width="2.5" x1="155" x2="625" y1="392" y2="392"/>
<line marker-end="url(#anyio-create-task-group-arrowGold)" stroke="#b45309" stroke-width="2.5" x1="390" x2="390" y1="392" y2="412"/>
<text fill="#b45309" font-size="12" font-weight="600" text-anchor="middle" x="390" y="386">__aexit__ waits for all tasks</text>
<rect fill="#fef3c7" height="44" rx="8" stroke="#b45309" stroke-width="2" width="350" x="215" y="418"/>
<text fill="#78350f" font-size="15" font-weight="700" text-anchor="middle" x="390" y="438">TaskGroup exits cleanly</text>
<text fill="#78350f" font-size="12" text-anchor="middle" x="390" y="455">all tasks joined</text>
<text fill="#9ca3af" font-size="12" x="18" y="473">anyio</text>
<text fill="#9ca3af" font-size="12" x="680" y="473">trio/asyncio</text>
</svg>

✓ structured concurrency - no orphaned tasks

cancellation · exception propagation · task supervision included

<!-- compare this with the previous diagram. tasks are contained within the task group scope. they fan out, do work, fan back in. structured and predictable. -->

---

# Key Takeaway

**`asyncio.create_task()` is the `goto` of concurrency**

-   It's powerful
-   It seems convenient
-   **It breaks everything**

**AnyIO task groups are the `if/while/for` of concurrency**

-   Tasks can't outlive their scope
-   They preserve abstractions
-   They make the language features work again
-   **They let you reason about your code**

<!-- this is the slide I want you to remember. create_task is goto. task groups are if/while/for. if someone told you to use goto today you'd laugh. start treating create_task the same way. -->

---

# "But asyncio has TaskGroup too!"

Yes! Python 3.11 added `asyncio.TaskGroup`. But:

- Still uses **edge-triggered cancellation** (as we'll see shortly, this causes real bugs)
- Bugfixes are tied to your Python version — not backported (3.13 fixed deadlocks that still exist in 3.11/3.12)
- No `CancelScope(shield=True)` — can't shield cleanup work from cancellation
- No `start()` — can't wait for a task to signal it's ready

`asyncio.TaskGroup` is a step forward. AnyIO takes it the rest of the way.

<!-- you're probably thinking "asyncio has TaskGroup too, why do I need AnyIO?" and yes, Python 3.11 added asyncio.TaskGroup. but it still uses edge-triggered cancellation, which as I'll show you causes real bugs including deadlocks. bugfixes are tied to your Python version. and it's missing CancelScope(shield=True) and start(). asyncio.TaskGroup is progress, but AnyIO finishes the job. -->

---

<style scoped>section { padding-top: 20px; }</style>

# Getting a Result from a Task

```python
async def fetch_both(url1: str, url2: str) -> tuple[str, str]:
    result1: str | None = None
    result2: str | None = None

    async def get1() -> None:
        nonlocal result1
        result1 = await fetch(url1)

    async def get2() -> None:
        nonlocal result2
        result2 = await fetch(url2)

    async with anyio.create_task_group() as tg:
        tg.start_soon(get1)
        tg.start_soon(get2)
    # both tasks are done - results are ready
    assert result1 is not None
    assert result2 is not None
    return result1, result2
```

<!-- tasks can't return values directly, but you can close over a nonlocal variable. each inner function sets its nonlocal when it finishes. after the task group exits, both results are guaranteed to be set - structured concurrency gives you that guarantee for free. -->

---

# "But I want to return without waiting!"

Sometimes you genuinely need to kick off work and respond immediately - e.g. a web endpoint that accepts a job and returns `202 Accepted`.

The answer: a **long-lived task group** scoped to the application lifetime.

---

<style scoped>section { padding-top: 20px; }</style>

# An Example with FastAPI

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import TypedDict
import anyio.abc

class State(TypedDict):
    tg: anyio.abc.TaskGroup

class ProcessResponse(BaseModel):
    status: str

class Done(Exception): pass

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[State]:
    try:
        async with anyio.create_task_group() as tg:
            yield State(tg=tg)
            raise Done
    except* Done:
        pass

app = FastAPI(lifespan=lifespan)

@app.post("/process", status_code=202)
async def process(data: str, request: Request[State]) -> ProcessResponse:
    request.state["tg"].start_soon(background_job, data)
    return ProcessResponse(status="accepted")
```

<!-- the task group lives for the lifetime of the app. individual requests can start_soon without waiting - fire and forget from the endpoint's point of view. but the tasks are still supervised: errors propagate, and on shutdown the lifespan context waits for all tasks to finish before the server exits. note: Request[State] generic support requires starlette>=0.37.0. with older versions use request.state.tg (attribute access) instead of request.state["tg"] (dict access). -->

---

# Zooming in: the lifespan context

```python
class Done(Exception): pass

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[State]:
    try:
        async with anyio.create_task_group() as tg:
            yield State(tg=tg)
            raise Done
    except* Done:
        pass
```

<!-- `yield` - app is running, tasks can be started. `raise Done` - on shutdown, raises Done inside the task group, which wraps it in an ExceptionGroup. `except* Done` - the except* syntax unpacks the ExceptionGroup and handles Done branches, cleanly absorbing the shutdown signal so it doesn't propagate as an error. -->

---

# Zooming in: the lifespan context (alternative)

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[State]:
    async with anyio.create_task_group() as tg:
        yield State(tg=tg)
        tg.cancel_scope.cancel()
```

<!-- simpler alternative: cancel_scope.cancel() directly cancels the task group's scope on shutdown, so child tasks receive Cancelled and stop immediately. no exception propagates out of the async with block - no except* needed. this is the idiomatic AnyIO way to stop a task group. the Done/except* version is more verbose but demonstrates Python 3.11's ExceptionGroup and except* syntax, which is worth knowing for error handling in concurrent code. both approaches cancel in-flight tasks rather than waiting for them to finish. -->

---

# "But I want to return without waiting!" (continued)

- On Trio: `trio.lowlevel.spawn_system_task()` spawns into a system nursery (Trio's name for a TaskGroup) that lives for the entire `trio.run()`
- AnyIO can't provide a portable `anyio.spawn_system_task()` - asyncio has no equivalent global supervised task group, only the unstructured `asyncio.create_task()`

<!-- trio has spawn_system_task for this pattern natively. anyio can't abstract over it because asyncio has no equivalent - there's no global supervised nursery, only the unstructured create_task. the FastAPI lifespan pattern is the asyncio-compatible solution. -->

---

# Further Reading

**Nathaniel J. Smith (Trio author):**\
["Notes on structured concurrency, or: Go statement considered harmful"](https://graingert.co.uk/trio-sc)\
`graingert.co.uk/trio-sc`

**Original Dijkstra paper:**\
["Go To Statement Considered Harmful" (1968)](https://graingert.co.uk/dijkstra68)\
`graingert.co.uk/dijkstra68`

<!-- njs's blog post is the definitive argument for structured concurrency. and Dijkstra's original paper is a surprisingly easy read - it's only a page long. -->

---

Normally at this stage of my talk I'd ask you to go run

# ~~pip install anyio~~

but if you're in this room you probably already have it in your virtual
environments!

<!-- normally at this point I'd tell you to go pip install AnyIO. but that's the punchline - you probably already have it. if you've installed httpx, FastAPI, Jupyter, MCP, or any number of popular packages, AnyIO is already in your virtualenv. -->

---

# Demo: You Already Have It

```sh
$ pip install httpx fastapi jupyter mcp pipdeptree
$ pipdeptree -p anyio -r  # reverse dependencies (dependants) of anyio
```

Watch the tree unfold: loads of packages you use daily depend on AnyIO

<!-- try this yourself. install a few common packages and run pipdeptree in reverse mode for AnyIO. you'll see a massive dependency tree. -->

---

<style scoped>section { padding-top: 20px; }</style>

# `pipdeptree` Output
```
anyio==4.13.0
├── starlette==1.0.0 [requires: anyio>=3.6.2,<5]
│   ├── fastapi==0.135.3 [requires: starlette>=0.46.0]
│   ├── sse-starlette==3.3.4 [requires: starlette>=0.49.1]
│   │   └── mcp==1.27.0 [requires: sse-starlette>=1.6.1]
│   └── mcp==1.27.0 [requires: starlette>=0.27]
├── jupyter_server==2.17.0 [requires: anyio>=3.1.0]
│   ├── jupyterlab==4.5.6 [requires: jupyter_server>=2.4.0,<3]
│   │   ├── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │   │   └── jupyter==1.1.1 [requires: notebook]
│   │   └── jupyter==1.1.1 [requires: jupyterlab]
│   ├── jupyter-lsp==2.3.1 [requires: jupyter_server>=1.1.2]
│   │   └── jupyterlab==4.5.6 [requires: jupyter-lsp>=2.0.0]
│   │       ├── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │       │   └── jupyter==1.1.1 [requires: notebook]
│   │       └── jupyter==1.1.1 [requires: jupyterlab]
│   ├── notebook==7.5.5 [requires: jupyter_server>=2.4.0,<3]
│   │   └── jupyter==1.1.1 [requires: notebook]
│   ├── jupyterlab_server==2.28.0 [requires: jupyter_server>=1.21,<3]
│   │   ├── jupyterlab==4.5.6 [requires: jupyterlab_server>=2.28.0,<3]
│   │   │   ├── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │   │   │   └── jupyter==1.1.1 [requires: notebook]
│   │   │   └── jupyter==1.1.1 [requires: jupyterlab]
│   │   └── notebook==7.5.5 [requires: jupyterlab_server>=2.28.0,<3]
│   │       └── jupyter==1.1.1 [requires: notebook]
│   └── notebook_shim==0.2.4 [requires: jupyter_server>=1.8,<3]
│       ├── jupyterlab==4.5.6 [requires: notebook_shim>=0.2]
│       │   ├── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│       │   │   └── jupyter==1.1.1 [requires: notebook]
│       │   └── jupyter==1.1.1 [requires: jupyterlab]
│       └── notebook==7.5.5 [requires: notebook_shim>=0.2,<0.3]
│           └── jupyter==1.1.1 [requires: notebook]
├── sse-starlette==3.3.4 [requires: anyio>=4.7.0]
│   └── mcp==1.27.0 [requires: sse-starlette>=1.6.1]
├── httpx==0.28.1 [requires: anyio]
│   ├── jupyterlab==4.5.6 [requires: httpx>=0.25.0,<1]
│   │   ├── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │   │   └── jupyter==1.1.1 [requires: notebook]
│   │   └── jupyter==1.1.1 [requires: jupyterlab]
│   └── mcp==1.27.0 [requires: httpx>=0.27.1]
└── mcp==1.27.0 [requires: anyio>=4.5]
```

<!-- look at this tree. starlette, FastAPI, MCP, httpx, Jupyter - they all depend on AnyIO. if you're using any modern Python web framework or data science tool you already have it installed. might as well use it. -->

---

# If you've installed any of these...

- `httpx` - the HTTP client
- `fastapi` - async web framework
- `jupyter` - data science notebooks
- `mcp` - Anthropic's Model Context Protocol SDK

...AnyIO was already there.

<!-- the point isn't just that it's popular - it's that you've been benefiting from AnyIO's correctness guarantees without knowing it. might as well start using it intentionally. -->

---

# Wrap Up

* remember: `asyncio` != `async`/`await` - other async frameworks exist (Twisted, Trio, Curio) and AnyIO works across asyncio and Trio
* I've given you a whistle-stop tour of some of my favourite features, there's loads more
   * and more being added all the time
* I hope I've persuaded you to give AnyIO a try
* you might as well give it a go if you already have it installed

<!-- to wrap up: asyncio is not the only async framework - async/await is decoupled from any event loop and other frameworks like Twisted, Trio, and Curio all use the same syntax. AnyIO works across asyncio and Trio. structured concurrency, level-triggered cancellation, great batteries. you've probably already got it installed. give it a go. -->

---

<style scoped>section { font-size: 21px; }</style>

# Any questions?

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

**Further reading:**
- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO documentation
- [graingert.co.uk/dabeaz-gen](https://graingert.co.uk/dabeaz-gen) — Generator Tricks for Systems Programmers
- [graingert.co.uk/dabeaz-coro](https://graingert.co.uk/dabeaz-coro) — A Curious Course on Coroutines and Concurrency
- [graingert.co.uk/dabeaz-final](https://graingert.co.uk/dabeaz-final) — Generators: The Final Frontier
- [graingert.co.uk/trio-sc](https://graingert.co.uk/trio-sc) — Go statement considered harmful (njs)
- [graingert.co.uk/dijkstra68](https://graingert.co.uk/dijkstra68) — Go To Statement Considered Harmful (1968)
