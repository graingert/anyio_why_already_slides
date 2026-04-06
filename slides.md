---
marp: true
html: true
---

# Why you should use AnyIO

### ...and why you probably already have it installed

https://graingert.co.uk/why-anyio-already

<!-- right so this is a talk about AnyIO. you probably already have it installed and don't know it. I'm going to try and convince you to actually use it on purpose. -->

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

# Agenda

* misconception: `asyncio` == `async`/`await`
* the problems with `asyncio.create_task` (and the fix: structured concurrency)
* getting a result from a task with `nonlocal`
* "But I want to return without waiting!": application scoped task groups
* the two most important reasons to use AnyIO
  * incrementally adoptable — drop into any asyncio codebase
  * cancellations are level-triggered (not edge-triggered like asyncio)
* `asyncio.shield` vs shielded `CancelScope`s
* some of my favourite AnyIO features
    * memory object streams (`asyncio.Queue` done right)
    * `anyio.Path`
    * pytest plugin built in
    * summary of features
* why you already have AnyIO installed

<!-- here's the plan. first I'll clear up the misconception that asyncio IS async/await, then I'll explain why create_task is broken, cover structured concurrency and the "return without waiting" pattern, then the two main reasons to use AnyIO, cancellation semantics, features I like, and finally reveal that you've already got AnyIO installed. -->

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


<!-- so what is AnyIO? it's the async standard library Python should have shipped. structured concurrency is the biggest conceptual shift - that's what we'll spend most of the talk on. level-triggered cancellation is the biggest practical win. and crucially, it's incrementally adoptable - you can drop it into an existing asyncio codebase today. -->

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

<style scoped>section { padding-top: 10px; }</style>

# The Root Cause: Unstructured Concurrency

<svg font-family="'Courier New', monospace" style="display: block; margin: 0 auto;" viewBox="0 0 420 320" width="700" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="asyncio-create-task-arrowGreen" markerHeight="6" markerWidth="8" orient="auto" refX="7" refY="3">
<polygon fill="#22c55e" points="0 0, 8 3, 0 6"/>
</marker>
<marker id="asyncio-create-task-arrowRed" markerHeight="6" markerWidth="8" orient="auto" refX="7" refY="3">
<polygon fill="#ef4444" points="0 0, 8 3, 0 6"/>
</marker>
</defs>
<rect fill="#f8fafc" height="320" rx="10" width="420"/>
<text fill="#1e293b" font-size="15" font-weight="700" text-anchor="middle" x="210" y="28">asyncio.create_task()</text>
<line stroke="#e2e8f0" stroke-width="1" x1="20" x2="400" y1="40" y2="40"/>
<line stroke="#22c55e" stroke-width="3" x1="150" x2="150" y1="60" y2="100"/>
<text fill="#c2410c" font-size="13" font-weight="700" text-anchor="middle" x="210" y="112">create_task()</text>
<circle cx="150" cy="100" fill="#64748b" r="4"/>
<line marker-end="url(#asyncio-create-task-arrowGreen)" stroke="#22c55e" stroke-width="3" x1="150" x2="150" y1="100" y2="200"/>
<line stroke="#ef4444" stroke-width="3" x1="150" x2="310" y1="100" y2="100"/>
<line marker-end="url(#asyncio-create-task-arrowRed)" stroke="#ef4444" stroke-width="3" x1="310" x2="310" y1="100" y2="200"/>
<text fill="#22c55e" font-size="14" font-weight="700" text-anchor="middle" x="150" y="226">parent</text>
<text fill="#64748b" font-size="12" text-anchor="middle" x="150" y="244">returns</text>
<text fill="#ef4444" font-size="14" font-weight="700" text-anchor="middle" x="310" y="226">myfunc</text>
<text fill="#64748b" font-size="12" text-anchor="middle" x="310" y="244">orphaned</text>
<line stroke="#ef4444" stroke-dasharray="5,4" stroke-width="2" x1="310" x2="310" y1="254" y2="296"/>
<text fill="#ef4444" font-size="11" text-anchor="middle" x="310" y="310">no reunion</text>
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

<style scoped>section { padding-top: 10px; }</style>

# The Fix: Structured Concurrency

<svg font-family="'Courier New', monospace" style="display: block; margin: 0 auto;" viewBox="0 0 420 340" width="700" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="anyio-create-task-group-arrowGreen" markerHeight="6" markerWidth="8" orient="auto" refX="7" refY="3">
<polygon fill="#22c55e" points="0 0, 8 3, 0 6"/>
</marker>
</defs>
<rect fill="#f8fafc" height="340" rx="10" width="420"/>
<text fill="#1e293b" font-size="15" font-weight="700" text-anchor="middle" x="210" y="28">anyio.create_task_group()</text>
<line stroke="#e2e8f0" stroke-width="1" x1="20" x2="400" y1="40" y2="40"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#22c55e" stroke-width="3" x1="210" x2="210" y1="56" y2="76"/>
<rect fill="none" height="190" rx="8" stroke="#22c55e" stroke-width="2.5" width="340" x="40" y="82"/>
<text fill="#14532d" font-size="12" font-weight="600" text-anchor="middle" x="210" y="104">async with create_task_group() as tg:</text>
<line stroke="#22c55e" stroke-width="2" x1="210" x2="210" y1="112" y2="126"/>
<circle cx="210" cy="126" fill="#22c55e" r="3"/>
<line stroke="#22c55e" stroke-width="2" x1="210" x2="100" y1="126" y2="126"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#22c55e" stroke-width="2" x1="100" x2="100" y1="126" y2="210"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#22c55e" stroke-width="2" x1="210" x2="210" y1="126" y2="210"/>
<line stroke="#22c55e" stroke-width="2" x1="210" x2="320" y1="126" y2="126"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#22c55e" stroke-width="2" x1="320" x2="320" y1="126" y2="210"/>
<text fill="#14532d" font-size="12" text-anchor="middle" x="100" y="230">parent</text>
<text fill="#14532d" font-size="12" text-anchor="middle" x="100" y="244">body</text>
<text fill="#14532d" font-size="12" text-anchor="middle" x="210" y="237">task1</text>
<text fill="#14532d" font-size="12" text-anchor="middle" x="320" y="237">task2</text>
<circle cx="210" cy="256" fill="#22c55e" r="3"/>
<line stroke="#22c55e" stroke-width="2" x1="100" x2="100" y1="250" y2="256"/>
<line stroke="#22c55e" stroke-width="2" x1="100" x2="210" y1="256" y2="256"/>
<line stroke="#22c55e" stroke-width="2" x1="320" x2="320" y1="250" y2="256"/>
<line stroke="#22c55e" stroke-width="2" x1="320" x2="210" y1="256" y2="256"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#22c55e" stroke-width="2" x1="210" x2="210" y1="256" y2="276"/>
<line marker-end="url(#anyio-create-task-group-arrowGreen)" stroke="#22c55e" stroke-width="3" x1="210" x2="210" y1="278" y2="310"/>
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


<!-- I get this objection a lot. people hear "structured concurrency" and think it means you can never fire and forget. that's not true - you just need to scope it to something with a lifetime, like your application. -->

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

# Two most important reasons to use AnyIO
* incrementally adoptable - drop into an existing asyncio codebase, and your code automatically works on Trio too
* cancellations are level-triggered

<!-- two biggest selling points. first: it's additive - you can sprinkle it into an existing asyncio codebase and optionally add Trio support later. second, and this is the one I really care about: cancellations are level-triggered. this is subtle but it prevents real bugs. -->

---

# Level-Triggered Cancellation (AnyIO) ✅

With level cancellation, every `await` inside a cancelled `CancelScope` raises `CancelledError` — cancellation is a **persistent state**, not a one-shot event.

```python
import anyio

async def example():
    with anyio.fail_after(0):
        try:
            await anyio.sleep(1)     # raises CancelledError
        finally:
            await anyio.sleep(1000)  # also raises CancelledError ✅
    # raises TimeoutError as you leave the scope

anyio.run(example)
# Note: not anyio.run(example()) - anyio.run takes a callable, not a coroutine
```

Your timeout of 0 seconds means exactly that: **0 seconds**.

<!-- with level cancellation, once a CancelScope is cancelled, EVERY await inside it raises CancelledError. even in the finally block. the cancellation is a state, not an event. so fail_after(0) means every single await in that scope fails immediately. predictable and safe. note: anyio.run takes a callable, not a coroutine - so no parentheses on example. -->

---

# Edge-Triggered Cancellation (asyncio) ❌

With edge cancellation, `CancelledError` is a **one-shot event** — once consumed, the next `await` succeeds even inside a cancelled scope.

```python
import asyncio

async def example():
    async with asyncio.timeout(0):
        try:
            await asyncio.sleep(1)     # raises CancelledError
        finally:
            await asyncio.sleep(1000)  # waits 1000 seconds 😱
    # raises TimeoutError.... eventually

asyncio.run(example())
# Note: not asyncio.run(example) - asyncio.run takes a coroutine, not a callable
```

Your timeout of 0 seconds becomes a timeout of **1000 seconds**.

<!-- now look at the same thing with asyncio. the first await raises CancelledError as expected. but in the finally block the cancellation has been consumed - it was edge-triggered, a one-shot event. so await asyncio.sleep(1000) actually waits 1000 seconds. your timeout of 0 becomes a timeout of 1000. this is a real class of bug. note: asyncio.run takes a coroutine, not a callable - so it's asyncio.run(example()) with parentheses, the opposite of anyio.run. -->

---
<style scoped>section { padding-top: 20px; }</style>
# Deadlocks in asyncio

```python
import asyncio

async def main():
    never = asyncio.Future()

    async def task_with_finally():
        try:
            print("task_with_finally running")
            await asyncio.sleep(10)
        finally:
            print("task_with_finally in finally")
            print("awaiting never-completing future (WILL HANG)")
            await never
            print("never reached")

    async def crash_soon():
        await asyncio.sleep(1)
        print("crash_soon raising")
        raise RuntimeError("boom")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(task_with_finally())
        tg.create_task(crash_soon())

asyncio.run(main())
```
<!-- edge cancellation doesn't just cause slowdowns - it can deadlock. here's a real example that hangs. -->

---

# asyncio Output *(Python 3.14 — deadlock affects all current versions)*

<!-- walk through it: task_with_finally sleeps, then in its finally block awaits a Future that never completes. crash_soon raises after 1 second. the TaskGroup cancels task_with_finally, but because cancellation is edge-triggered, the finally block's `await never` is NOT cancelled - it just hangs forever. you have to Ctrl+C multiple times to kill it. -->

```sh
$ python demo_asyncio.py
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL HANG)
```

---

# Output after hitting Ctrl+C a few times

```sh
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL HANG)
^C^Cunhandled exception during asyncio.run() shutdown
task: <Task finished name='Task-1' coro=<main() done, defined at /home/graingert/projects/anyio_why_already_slides/demo_asyncio.py:3> exception=ExceptionGroup('unhandled errors in a TaskGroup', [RuntimeError('boom')])>
  + Exception Group Traceback (most recent call last):
  |   File "/home/graingert/projects/anyio_why_already_slides/demo_asyncio.py", line 21, in main
  |     async with asyncio.TaskGroup() as tg:
  |                ~~~~~~~~~~~~~~~~~^^
  |   File "/usr/lib/python3.14/asyncio/taskgroups.py", line 72, in __aexit__
  |     return await self._aexit(et, exc)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/usr/lib/python3.14/asyncio/taskgroups.py", line 174, in _aexit
  |     raise BaseExceptionGroup(
  |     ...<2 lines>...
  |     ) from None
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/home/graingert/projects/anyio_why_already_slides/demo_asyncio.py", line 19, in crash_soon
    |     raise RuntimeError("boom")
    | RuntimeError: boom
    +------------------------------------
Traceback (most recent call last):
  File "/home/graingert/projects/anyio_why_already_slides/demo_asyncio.py", line 25, in <module>
    asyncio.run(main())
    ~~~~~~~~~~~^^^^^^^^
  File "/usr/lib/python3.14/asyncio/runners.py", line 204, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "/usr/lib/python3.14/asyncio/runners.py", line 127, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/usr/lib/python3.14/asyncio/base_events.py", line 706, in run_until_complete
    self.run_forever()
    ~~~~~~~~~~~~~~~~^^
  File "/usr/lib/python3.14/asyncio/base_events.py", line 677, in run_forever
    self._run_once()
    ~~~~~~~~~~~~~~^^
  File "/usr/lib/python3.14/asyncio/base_events.py", line 2008, in _run_once
    event_list = self._selector.select(timeout)
  File "/usr/lib/python3.14/selectors.py", line 452, in select
    fd_event_list = self._selector.poll(timeout, max_ev)
  File "/usr/lib/python3.14/asyncio/runners.py", line 166, in _on_sigint
    raise KeyboardInterrupt()
KeyboardInterrupt
```

<!-- that's a lot of traceback just to say "your program hung and you had to kill it". the program didn't exit cleanly - we had to interrupt it multiple times. the actual error from crash_soon only surfaces after we force-kill the process. -->

---

<style scoped>section { padding-top: 20px; }</style>

# The Same Example with AnyIO

```python
import asyncio
import anyio

async def main():
    never = asyncio.Future()

    async def task_with_finally():
        try:
            print("task_with_finally running")
            await asyncio.sleep(10)
        finally:
            print("task_with_finally in finally")
            print("awaiting never-completing future (WILL NOT HANG)")
            await never
            print("never reached")

    async def crash_soon():
        await asyncio.sleep(1)
        print("crash_soon raising")
        raise RuntimeError("boom")

    async with anyio.create_task_group() as tg:
        tg.start_soon(task_with_finally)
        tg.start_soon(crash_soon)

asyncio.run(main())
```


<!-- same program, one change: anyio.create_task_group instead of asyncio.TaskGroup. notice the inner functions still use asyncio.sleep and asyncio.Future directly - you don't have to rewrite everything to get the benefits. that's what incrementally adoptable means in practice. -->

---

# AnyIO Output

<!-- same program with anyio.create_task_group. only change is using anyio.create_task_group instead of asyncio.TaskGroup. because AnyIO uses level-triggered cancellation, when crash_soon raises, the cancellation of task_with_finally persists into its finally block. the `await never` is immediately cancelled too. no hang. -->
```sh
$ python demo_anyio.py
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL NOT HANG)
  + Exception Group Traceback (most recent call last):
  |   File "/home/graingert/projects/anyio_why_already_slides/demo_anyio.py", line 26, in <module>
  |     asyncio.run(main())
  |     ~~~~~~~~~~~^^^^^^^^
  |   File "/usr/lib/python3.14/asyncio/runners.py", line 204, in run
  |     return runner.run(main)
  |            ~~~~~~~~~~^^^^^^
  |   File "/usr/lib/python3.14/asyncio/runners.py", line 127, in run
  |     return self._loop.run_until_complete(task)
  |            ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  |   File "/usr/lib/python3.14/asyncio/base_events.py", line 719, in run_until_complete
  |     return future.result()
  |            ~~~~~~~~~~~~~^^
  |   File "/home/graingert/projects/anyio_why_already_slides/demo_anyio.py", line 22, in main
  |     async with anyio.create_task_group() as tg:
  |                ~~~~~~~~~~~~~~~~~~~~~~~^^
  |   File "/home/graingert/projects/anyio_why_already_slides/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__
  |     raise BaseExceptionGroup(
  |         "unhandled errors in a TaskGroup", self._exceptions
  |     ) from None
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/home/graingert/projects/anyio_why_already_slides/demo_anyio.py", line 20, in crash_soon
    |     raise RuntimeError("boom")
    | RuntimeError: boom
    +------------------------------------
```

<!-- clean exit, clear traceback, no hanging, no Ctrl+C. the program terminates immediately with the actual error. notice "WILL NOT HANG" - the await never was properly cancelled by level-triggered cancellation. -->

---

# Edge Cancellation with WebSockets over TLS

<style scoped>section { padding-top: 20px; }</style>

- Cancellation fires inside `process()` - but the `async with` still runs `__aexit__`
- WebSocket `__aexit__` does a TLS shutdown, which **awaits I/O**
- With edge cancellation, that await **succeeds** even in a cancelled state
- So the timeout is bypassed - your 10-second limit can hang forever

```python
async def consume_ws():
    async with await connect_ws("wss://example.com/news") as ws:
        async for message in ws:
            await process(message)  # cancellation happens here
    # cancellation doesn't happen as we `__aexit__()` the context manager

async def example():
    async with asyncio.timeout(10):
        await consume_ws()  # could hang forever
```

<!-- this isn't contrived. if you're using WebSockets over TLS, the TLS shutdown in __aexit__ involves awaiting I/O. with edge cancellation that await succeeds even though you're in a cancelled state, so your timeout becomes meaningless. your 10-second timeout could hang forever. -->

---

# Shielding from Cancellation

## When you *can't* just walk away - even after cancelling

Sometimes you can cancel the work, but you **must wait for it to finish dying**:

- Subprocesses (`anyio.to_process.run_sync`): you can `terminate()` the process, but you must still `wait()` to join it - otherwise you get zombie processes
- Waiting for a thread to finish (`loop.run_in_executor`, `anyio.to_thread.run_sync`) - threads can't be interrupted at all
- On Windows IOCP (Proactor): cancelled operations complete with `ERROR_OPERATION_ABORTED`, and you must wait for the completion packet before freeing memory

<!-- sometimes you can cancel the work but you can't just walk away. subprocesses are the perfect example: you can terminate the process, but you MUST still join it afterwards. if you don't wait, you get zombie processes. threads are worse - you can't even cancel them. and on Windows IOCP the OS must acknowledge the cancel before you can free memory. this is where shielding comes in. -->

---

# Cancellation Abandons the Work, Not the Task

The async framework can raise `CancelledError` in your coroutine, but:
- the **underlying thread keeps running**
- a **terminated subprocess still needs to be joined**
- **something still needs to wait to be able to clear memory**

You're not cancelling the work - you're just *abandoning* the future that was watching it. 👻

<!-- key insight: when you cancel an executor task in asyncio, the thread keeps running. when you cancel a subprocess wrapper, the process might still be alive or needs joining. you've just abandoned the Future. the work is still happening, you just stopped paying attention to it. like hanging up the phone on someone mid-sentence. -->

---

# Example: Windows IOCP Buffer Safety

```python
# IOCP
buffer = allocate_buffer(1024)
try:
    await write_buffer_to_socket(buffer, socket)
finally:
    # if write_buffer_to_socket is cancelled and we don't wait for the cancel
    # signal the OS could still be using the buffer and we send undefined
    # bytes to the socket.
    clear(buffer)
```

<!-- concrete Windows example. if you cancel during write_buffer_to_socket and immediately clear the buffer, the OS might still be DMA-ing from that buffer. you'd send undefined bytes over the network. you MUST wait for cancellation to complete before freeing resources. -->

---

# `asyncio.shield` - The Duct-Tape Approach

```python
async def run_in_process(fn, *args):
    process = await asyncio.create_subprocess_exec(...)
    try:
        await asyncio.shield(process.wait())
        # ⚠️ If cancelled, shield absorbs the cancel...
        # ... but process.wait() keeps running as a detached task
    except asyncio.CancelledError:
        process.terminate()
        # ⚠️ Edge cancellation: nested asyncio.timeout blocks or
        # multiple task.cancel() calls can cancel this await again
        # before the process exits - leaving it un-joined
        await process.wait()  # might be cancelled before process exits!
        raise
```

<!-- asyncio.shield is the standard answer to "how do I protect work from cancellation". but it's duct tape. it wraps a single await, creates a detached task. and because of edge cancellation - from nested asyncio.timeout blocks or multiple task.cancel() calls - the process.wait() in the except block can be cancelled again before the process exits, leaving it un-joined. -->

---

# Problems

❌ **Edge-triggered**: a `CancelledError` sneaks through on the *next* checkpoint after the shield exits  
❌ **Orphaned inner task**: the shielded `process.wait()` keeps running with no owner  
❌ **No scope**: shield applies to one `await`, not a logical block (terminate + join)  
❌ **Can't compose terminate + join**: need to shield the wait, then join, then re-raise - but edge cancellation makes the join unreliable

<!-- four problems. shield only wraps one await. the inner task is orphaned. and the critical issue for subprocesses: you need to terminate AND join as a single logical unit, but shield can't express that. edge cancellation - from nested asyncio.timeout blocks or multiple task.cancel() calls - means the join in the except block can be cancelled again before the process exits, leaving it un-joined. -->

---

# AnyIO Shielded Cancel Scopes - The Structured Approach

```python
# Simplified implementation of anyio.to_process.run_sync
async def to_process_run_sync(fn, *args):
    process = await anyio.open_process(...)
    try:
        await process.wait()
        return process.returncode
    except anyio.get_cancelled_exc_class():
        process.terminate()
        # Shield the join: we MUST wait for the process to exit
        # even though we've been cancelled
        with anyio.CancelScope(shield=True):
            await process.wait()  # no zombie processes
        raise
    # Pending cancellation is re-raised after the shielded join
```

<!-- AnyIO's approach is fundamentally different. when cancellation hits, we terminate the process, then shield the join. CancelScope with shield=True protects the wait - the process is properly reaped even under cancellation. pending cancellation is deferred and reliably re-raised after we exit the shield. no zombies, no orphans. -->

---

# Why It Works

✅ **Level-triggered**: cancellation is *deferred*, not lost — re-fires on the next `await` after the shield exits  
✅ **Process-aware**: `terminate()` + shielded `wait()` — kill it, then reap it  
✅ **Scoped**: protect the whole terminate-and-join block, not just one `await`  
✅ **No zombies**: structured concurrency means every process is joined

The key insight: sometimes cleanup requires I/O. `asyncio.shield` can only protect a single expression. `CancelScope(shield=True)` protects an entire logical block — terminate *and* join — which is exactly what subprocess cleanup needs.


<!-- so why does this work where asyncio.shield doesn't? because sometimes cleanup requires I/O - you need to protect an entire logical block, not just a single await. CancelScope gives you that. and because cancellation is level-triggered, it's reliably re-raised after the shield exits. -->

---

<style scoped>section { padding-top: 10px; }</style>

# Shielding in Detail: asyncio.shield
<svg font-family="'Courier New', monospace" style="display: block; margin: 0 auto;" viewBox="0 0 520 260" width="650" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="asyncio-shield-arrowRed" markerHeight="6" markerWidth="8" orient="auto" refX="7" refY="3">
<polygon fill="#ef4444" points="0 0, 8 3, 0 6"/>
</marker>
<marker id="asyncio-shield-arrowGrey" markerHeight="6" markerWidth="8" orient="auto" refX="7" refY="3">
<polygon fill="#94a3b8" points="0 0, 8 3, 0 6"/>
</marker>
</defs>
<rect fill="#f8fafc" height="260" rx="10" width="520"/>
<text fill="#1e293b" font-size="15" font-weight="700" text-anchor="middle" x="260" y="28">asyncio.shield() under cancellation</text>
<line stroke="#e2e8f0" stroke-width="1" x1="20" x2="500" y1="40" y2="40"/>
<text fill="#475569" font-size="13" font-weight="600" text-anchor="middle" x="140" y="62">your code sees</text>
<text fill="#475569" font-size="13" font-weight="600" text-anchor="middle" x="380" y="62">inside shield()</text>
<rect fill="#fecaca" height="194" rx="3" width="8" x="255" y="50"/>
<line stroke="#2563eb" stroke-width="2.5" x1="140" x2="140" y1="76" y2="96"/>
<text fill="#2563eb" font-size="13" font-weight="700" text-anchor="middle" x="140" y="114">await shield(f)</text>
<line marker-end="url(#asyncio-shield-arrowRed)" stroke="#ef4444" stroke-width="2.5" x1="140" x2="140" y1="122" y2="148"/>
<text fill="#ef4444" font-size="12" font-weight="600" x="168" y="142">cancel</text>
<text fill="#ef4444" font-size="15" font-weight="700" text-anchor="middle" x="140" y="172">CancelledError</text>
<text fill="#64748b" font-size="11" text-anchor="middle" x="140" y="194">edge-triggered: used up</text>
<text fill="#b45309" font-size="11" font-weight="600" text-anchor="middle" x="140" y="210">next await may succeed [!]</text>
<line stroke="#94a3b8" stroke-width="2.5" x1="380" x2="380" y1="76" y2="96"/>
<text fill="#ea580c" font-size="13" font-weight="600" text-anchor="middle" x="380" y="114">cancel NOT forwarded</text>
<line marker-end="url(#asyncio-shield-arrowGrey)" stroke="#94a3b8" stroke-width="2.5" x1="380" x2="380" y1="122" y2="148"/>
<text fill="#64748b" font-size="11" x="398" y="142">runs on...</text>
<text fill="#ef4444" font-size="15" font-weight="700" text-anchor="middle" x="380" y="172">result lost</text>
<text fill="#64748b" font-size="11" text-anchor="middle" x="380" y="194">no owner, no supervision</text>
<text fill="#64748b" font-size="11" text-anchor="middle" x="380" y="210">cleanup may never run</text>
<line stroke="#ef4444" stroke-dasharray="5,4" stroke-width="2" x1="380" x2="380" y1="218" y2="248"/>
</svg>

<!-- in this diagram you can see the orphaned inner task running off on its own - same problem as create_task. shield wraps a single point, and after it exits you're back to unstructured territory. -->

---

# Shielding in Detail: asyncio.shield (continued)

`shield()` wraps the outer Future around an inner Task. When the outer cancel arrives, the outer Future is cancelled immediately (edge-triggered). The inner Task is orphaned — it keeps running with no owner. The result is silently discarded.

---

<style scoped>section { padding-top: 15px; }</style>

# Comparison

| | `asyncio.shield` | `anyio.CancelScope(shield=True)` |
|---|---|---|
| Cancellation model | Edge (one-shot) | Level (persistent, deferred) |
| Scope | Single `await` | Entire `with` block |
| Process cleanup | ❌ Can't reliably terminate + join | ✅ Terminate then shielded join |
| Cancellation after exit | ⚠️ Maybe (edge, unreliable) | ✅ Always re-raised |
| Orphaned tasks | ❌ Yes | ✅ Never |
| Composable | ❌ Not really | ✅ Nests with task groups |

<!-- full comparison side by side. every row is a win for AnyIO. key insight: shielding should be a scope, not a wrapper around a single expression. the process case makes this crystal clear - you need to shield a multi-step cleanup sequence. -->


---

<style scoped>section { font-size: 22px; padding-top: 20px; }</style>

# Mixing Native asyncio Cancellation

❌ `task.cancel()` injects `CancelledError` directly, bypassing AnyIO's cancel scope stack — the shield cannot defer it:

```python
async def ham():
    with anyio.CancelScope(shield=True):
        await spam()  # shield does NOT protect against task.cancel()

async def bad():
    task = asyncio.create_task(ham())
    task.cancel()   # bypasses AnyIO's cancel scope machinery entirely
    await task      # CancelledError — task never started
```

✅ `tg.cancel_scope.cancel()` goes through AnyIO's machinery — the shield defers it correctly:

```python
async def main():
    async with anyio.create_task_group() as tg:
        tg.cancel_scope.cancel()
        tg.start_soon(ham)  # spam() runs to completion ✅
```

AnyIO guarantees every `start_soon`'d task runs to its first `await` before cancellation is delivered — so `with anyio.CancelScope(shield=True):` (synchronous) is always entered first.

<!-- task.cancel() is a raw asyncio operation that bypasses AnyIO's cancel scope stack entirely. CancelScope(shield=True) only defers cancellations delivered through AnyIO's own machinery. tg.cancel_scope.cancel() goes through that machinery, so the shield works. AnyIO's start_soon guarantee means the synchronous with block is always entered before cancellation fires, so the shield is always in place. -->

---

# More AnyIO Features: Backpressure by Default. Structured. Composable.

<!-- ok we've covered the big conceptual stuff - structured concurrency and level-triggered cancellation. now let me show you some practical features I like. -->

* AnyIO provides `MemoryObjectSendStream` and `MemoryObjectReceiveStream`
* like `asyncio.Queue` but you don't need to keep a count of how many producer/consumers you have
  * you just make a clone for each producer/consumer
  * use a `with` or `async with` to close the clones.
  * Once all the clones of one end of the memory object stream are closed
  iterating the other end will raise StopAsyncIteration.

<!-- memory object streams are like asyncio.Queue but designed right. the killer feature is clone() - each producer/consumer gets their own clone, and when all clones of one end are closed the other end gets a clean StopAsyncIteration. no sentinel values, no manual counting, no shutdown coordination. -->

---

# Memory Object Streams: Full Example

```python
import anyio

async def consume_ws(url, stream):
    with stream:              # sync - runs before first await
        async with await connect_ws(url) as ws:
            async for msg in ws:
                await stream.send(msg)

async def news_and_weather():
    tx, rx = anyio.create_memory_object_stream[bytes]()  # default buffer size = 0
    with tx, rx:
        async with anyio.create_task_group() as tg:
            tg.start_soon(consume_ws, "ws://example.com/news", tx.clone())
            tg.start_soon(consume_ws, "ws://example.com/weather", tx.clone())
            tx.close()
            async for item in rx:
                print(item)

anyio.run(news_and_weather)
```

<!-- look how clean this is. two WebSocket consumers, each with a clone of the send stream, feeding a single receive stream. when both producers finish their clones close, original tx is already closed, so the async for on rx terminates naturally. fully structured shutdown with zero boilerplate. default buffer size is 0 so you get backpressure for free.

note the synchronous `with stream:` - AnyIO guarantees every start_soon'd task runs to its first await point before cancellation is delivered. the sync with runs before any await, so __exit__ always fires and the clone is always closed. no leaked clones, no phantom senders keeping rx open forever.

the [bytes] on create_memory_object_stream is for static type checking - create_memory_object_stream is a generic tuple subclass, so [bytes] specialises the type. no runtime effect, but your type checker and IDE will know the stream carries bytes. -->

---

<style scoped>section { padding-top: 10px; padding-bottom: 40px; }</style>

# Key Properties

-   ✅ **Buffer size defaults to 0** → automatic backpressure

-   ✅ `async for` works naturally

-   ✅ `aclose()` or `close()` signals end-of-stream

-   ✅ `clone()` enables multiple consumers safely - use `async with` or sync `with` to gain ownership and automatically close:

    ```python
    async def consume_ws(url, stream):
        with stream:          # sync - runs before first await
            async with await connect_ws(url) as ws:
                ...

    tg.start_soon(consume_ws, url, tx.clone())
    ```

-   ✅ Structured shutdown - unlike asyncio, AnyIO tasks always run to their first `await` before cancellation, so `with stream:` always closes the clone

<!-- five properties you want from inter-task communication. you get them all for free just by using memory object streams instead of asyncio.Queue. the clone pattern is safe because AnyIO guarantees start_soon'd tasks reach their first checkpoint before cancellation - and the synchronous with stream runs before any await, so the clone is always closed. -->

---

# `async with` shortcut

- `async with` = `with` for streams - automatic cleanup
- Combine streams, task groups, etc. in one `async with`:

```python
async def consume_ws(url, stream):
    async with stream, await connect_ws(url) as ws:
        async for msg in ws:
            await stream.send(msg)

async def news_and_weather():
    tx, rx = anyio.create_memory_object_stream[bytes]()
    async with tx, rx, anyio.create_task_group() as tg:
        tg.start_soon(consume_ws, "ws://example.com/news", tx.clone())
        tg.start_soon(consume_ws, "ws://example.com/weather", tx.clone())
        tx.close()
        async for item in rx:
            print(item)
```

<!-- async with gives you automatic cleanup of streams just like files. stacking tx, rx, and the task group into a single async with means you get structured ownership. -->

---

# `async with` shortcut — why it's safe

Three resources enter one `async with`: the send stream, receive stream, and task group. They're all closed/joined together on exit — **in the right order, even under exceptions or cancellation**.

- `tx.close()` is called explicitly in the body — this is what signals end-of-stream to tasks
- `async with tx, rx` exits in *reverse* entry order: `tg.__aexit__` first (joins tasks), then `rx`, then `tx` — the explicit close is what actually stops new work before the tasks finish
- `MemoryObjectStream.__aenter__` returns `self` without yielding — not a real checkpoint — so the structured shutdown guarantee still holds

<!-- the key insight: async with on a MemoryObjectStream doesn't yield to the event loop, so it's safe to use inside a task group even with cancellation. everything closes in structured order. -->

---

# asyncio.Queue Comparison

```python
import asyncio

async def main():
    q = asyncio.Queue()  # unbounded by default (!)

    async def producer():
        for i in range(3):
            print("put", i)
            await q.put(i)
        # How do we signal completion?

    async def consumer():
        while True:
            item = await q.get()
            print("got", item)
```

<!-- here's the equivalent with asyncio.Queue. notice the problems immediately: unbounded by default, no async iteration, and - how do you signal completion? there's no mechanism. you end up with sentinel values or manual counters. -->

---

# Problems with `asyncio.Queue`

-   ❌ Unbounded by default (no backpressure)

-   ❌ No async iteration

-   ❌ No built-in structured close (historically)

-   ❌ No clone() so requires sentinel values or custom shutdown logic

<!-- every one of these is a footgun. unbounded means memory grows without limit. no async iteration means you write while True loops. no structured close means you invent your own shutdown protocol. -->

---

# asyncio.Queue.shutdown() (3.13+)

Python 3.13 added:

```python
q.shutdown()
```

But:

-   Only on Python 3.13+

-   Still no cloning

-   Still no structured fan-out

<!-- Python 3.13 added Queue.shutdown() which is progress, but it's only on the latest Python, doesn't have cloning, doesn't compose with structured concurrency. AnyIO gives you all of this on Python 3.10+. -->

---
# Conceptual Comparison

| Feature | AnyIO Stream | asyncio.Queue |
|---------|--------------|---------------|
| Default backpressure | ✅ (buffer=0) | ❌ (unbounded) |
| Async iteration | ✅ | ❌ |
| Structured close | ✅ | ⚠️ (3.13+) |
| Clone receivers | ✅ | ❌ |
| Trio-compatible | ✅ | ❌ |

AnyIO streams compose with structured concurrency. `asyncio.Queue`
predates it.

<!-- the table tells the story. AnyIO streams were designed with structured concurrency in mind. asyncio.Queue predates it and it shows. -->

---
# "If I'm already using Trio, I don't need AnyIO."

Trio is a minimal framework — only what's mandatory for a network framework. AnyIO is a portability + abstraction layer with batteries included.

What AnyIO adds on top of Trio:

-   ✅ Backend portability (asyncio and Trio) — a stable public API for libraries
-   ✅ High-level stream utilities: `BufferedByteReceiveStream`, `StapledStream`, `anyio.Path`
-   ✅ Thread/subprocess/subinterpreter helpers

<!-- common pushback: "I already use Trio, why do I need AnyIO?" Trio is deliberately minimal - it only gives you what a network framework must provide. AnyIO is batteries-included on top of that. -->

---

# Writing Libraries: Target AnyIO, Not Trio

If you write a library **directly against Trio**:

- ❌ You lock out asyncio users entirely.

If you write a library **against AnyIO**:

- ✅ Trio users still get full Trio semantics.
- ✅ asyncio users can incrementally adopt structured concurrency.
- ✅ You get a bunch of cool extra tools.

**AnyIO is the right target for any library that wants to support both backends.**


<!-- if you're writing a library, this matters. httpx, FastAPI, and MCP all chose AnyIO over raw Trio precisely because it doesn't lock out asyncio users. you get Trio semantics for free, and asyncio users can adopt structured concurrency incrementally. -->

---

# Buffered Byte Streams (AnyIO Feature Trio Lacks)

Trio provides `SendStream` / `ReceiveStream`.

But it does **not** provide:

-   Buffered reads

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Automatic read buffering

AnyIO does.

<!-- one of my favourite examples. Trio gives you raw byte streams but if you need line-by-line reading or fixed-size reads you're on your own. AnyIO's BufferedByteReceiveStream handles all the annoying buffering for you. -->

---

<style scoped>section { padding-top: 20px; }</style>

# Demo --- AnyIO Buffered Byte Streams

```python
import anyio.streams.buffered

async def main():

    async def producer(stream):
        with stream:
            await stream.send(b"hello\nworld\n")

    async def consumer(stream):
        with stream:
            buffered = anyio.streams.buffered.BufferedByteReceiveStream(stream)
            line1 = await buffered.receive_until(b"\n", 4096)
            print("line1:", line1)
            line2 = await buffered.receive_until(b"\n", 4096)
            print("line2:", line2)

    tx, rx = anyio.create_memory_object_stream[bytes]()
    async with tx, rx, anyio.create_task_group() as tg:
        tg.start_soon(producer, tx.clone())
        tx.close()
        tg.start_soon(consumer, rx.clone())
        rx.close()

anyio.run(main)
```


<!-- so the producer sends both lines in a single chunk. the consumer uses receive_until to split by newline delimiter - no manual buffer management. and notice the sync `with stream:` pattern - that runs before the first await, so the clone is always closed even under cancellation. -->

---

# Output + What Just Happened

<!-- producer sends both lines in one chunk. consumer uses receive_until to split by newline. no manual buffer management, no partial read handling. it just works. -->

```sh
$ python demo_buffered_bytes.py
line1: b'hello'
line2: b'world'
```

-   The producer sent both lines in one chunk.
-   The consumer parsed them cleanly by delimiter.
-   No manual buffering. No partial read bookkeeping.

<!-- clean output. the buffered stream handled all the complexity of parsing delimited data from arbitrary chunk boundaries. saves you from writing buggy buffer management code. -->

---

# How You'd Do This in Trio

Trio gives you raw receive:

```python
data = await stream.receive_some(1024)
```

But you must manually:

-   Accumulate into a buffer

-   Search for delimiters

-   Slice the buffer

-   Handle partial frames

-   Handle EOF correctly

<!-- with raw Trio you have to do all this yourself. accumulate into a buffer, scan for delimiters, slice, handle partial frames, handle EOF. it's not rocket science but it's tedious and easy to get wrong. speaking of getting it wrong... -->

---
# Can You Spot the Performance Footgun?

I asked ChatGPT for an example - can you spot the problem?

```python
buffer = bytearray()
while True:
    chunk = await stream.receive_some(1024)
    if not chunk:
        break
    buffer.extend(chunk)
    while b"\n" in buffer:
        line, _, rest = buffer.partition(b"\n")
        print(line + b"\n")
        buffer = bytearray(rest)  # copies remaining bytes every iteration
```

<!-- I asked ChatGPT to write this and it has a bug. can anyone spot it? -->

---

# Quadratic Performance in the Inner Loop

Every iteration of `while b"\n" in buffer` does `buffer = bytearray(rest)`,
copying the remaining data each time. If you receive a chunk with many
newlines, this is O(n²) in the number of bytes.

<!-- it's quadratic! every iteration copies the remaining buffer into a new bytearray. if you get a large chunk with many newlines you're doing O(n²) work. BufferedByteReceiveStream handles this correctly with efficient internal buffering. -->

---

# What AnyIO Adds Here

`BufferedByteReceiveStream` gives you:

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Proper EOF semantics

-   Efficient internal buffering

-   Works on both Trio and asyncio backends

This is a real ergonomic upgrade.

<!-- receive_exactly, receive_until, proper EOF, efficient buffering, works on both backends. real ergonomic upgrade. -->

---

# Further Reading

-   [github.com/python-trio/trio/issues/796](https://github.com/python-trio/trio/issues/796) - Provide standard mechanism for splitting a stream into lines
-   [github.com/groove-x/trio-util/issues/22](https://github.com/groove-x/trio-util/issues/22) - Add a LineReader?
-   [github.com/python-trio/trio/issues/562](https://github.com/python-trio/trio/issues/562) - Get N items from Channel

<!-- these are the Trio issues where buffered streams were discussed and ultimately not added to Trio itself. AnyIO fills this gap. -->

---

# anyio.Path: Async File Operations

## The Problem with pathlib

```python
from pathlib import Path

async def amain():
    # ⚠️ These all BLOCK the event loop!
    path = Path("data.txt")

    path.write_text("Hello!")      # Blocks
    content = path.read_text()     # Blocks
    exists = path.exists()         # Blocks
```

<!-- pathlib is great but every operation blocks the event loop. in an async application, calling path.read_text() blocks the entire loop while waiting for disk I/O. defeats the whole point of async. -->

---

# The Solution: `anyio.Path`

```python
import anyio

async def amain():
    # ✅ Non-blocking - each runs in a thread pool via anyio.to_thread.run_sync
    path = anyio.Path("data.txt")
    await path.write_text("Hello!")    # Async
    content = await path.read_text()  # Async
    exists = await path.exists()      # Async
```

**Same API as `pathlib`, but async-native.** Each operation offloads to a thread pool, so your event loop stays free while the disk I/O happens.

<!-- anyio.Path is a drop-in async replacement for pathlib.Path. under the hood, each method wraps the blocking call with anyio.to_thread.run_sync. the event loop isn't blocked - other tasks keep running. -->

---

# Real Power: Parallel File Operations

```python
import anyio

async def concurrently_chmod_all_csvs():
    data_dir = anyio.Path("training_data")
    async with anyio.create_task_group() as tg:
        async for path in data_dir.iterdir():
            if await path.is_file() and path.suffix == '.csv':
                tg.start_soon(path.chmod, 0o644)

anyio.run(concurrently_chmod_all_csvs)
# All files processed concurrently!
```

<!-- and because it's async you can combine it with task groups for parallel file I/O. process all CSVs in a directory concurrently, with structured concurrency ensuring everything completes before you continue. -->

---

# Key Features

| Feature | pathlib | anyio.Path |
|---------|---------|------------|
| Async operations | ❌ Blocks | ✅ async with threads |
| Parallel I/O | ❌ Sequential | ✅ Works with task groups |
| Event loop friendly | ❌ Blocks | ✅ Non-blocking |
| API compatibility | ✅ Standard | ✅ Same interface but async |
| Type hints | ✅ Yes | ✅ Yes |

**Key Takeaway:** Drop-in replacement for pathlib that actually respects
async/await

<!-- anyio.Path gives you everything pathlib does but without blocking the event loop. genuine drop-in replacement. -->

---

# pytest Plugin

* AnyIO ships with a pytest plugin that it uses to test itself.
* This means if you already depend on AnyIO you don't need pytest-asyncio as well.

```python
@pytest.mark.anyio
async def test_something():
    assert await something() == "result"
```

<!-- AnyIO ships with its own pytest plugin - the same one it uses to test itself. so if you already depend on AnyIO you don't need pytest-asyncio. just @pytest.mark.anyio and you're done. -->

---
# Limiting the Plugin to asyncio
* By default the plugin runs your tests under both asyncio and Trio
* if you're still gradually migrating to AnyIO and still call asyncio APIs directly
* you can run your tests in asyncio mode only by adding the following to your root `conftest.py`

```python
@pytest.fixture
def anyio_backend():
    return 'asyncio'
```

<!-- by default the plugin runs tests on both asyncio and Trio, which is great for catching backend-specific bugs. if you're still migrating and only need asyncio, add this fixture to your conftest. -->

---

# Networking & I/O

| Feature | Benefit |
|---|---|
| **TCP/UDP/UNIX sockets** | Happy Eyeballs built in (fixed refcycles in CPython's implementation); async/await UDP — no Transports/Protocols |
| **TLS streams** | `TLSStream` wraps any byte stream with TLS, not just sockets |
| **Subprocesses** | `run_process()` / `open_process()` with async stream I/O on stdin/stdout/stderr |
| **Signal handling** | `open_signal_receiver()` - async iterator over OS signals |

<!-- AnyIO has a full networking stack. TCP, UDP, Unix sockets with Happy Eyeballs built in. TLS that wraps any byte stream, not just sockets. subprocesses with async stream I/O. signal handling as an async iterator. -->

---

# Streams & Concurrency

| Feature | Benefit |
|---|---|
| **`TextReceiveStream`** | Incremental UTF-8 decoding over any byte stream |
| **`StapledStream`** | Combine separate send/receive streams into one bidirectional stream |
| **`tg.start()`** | `await tg.start(server_fn)` - blocks until the task calls `task_status.started(value)`, perfect for server startup |
| **Synchronization primitives** | `Lock`, `Condition`, `Event`, `Semaphore`, `CapacityLimiter` - portable across backends |

<!-- more batteries: TextReceiveStream for incremental UTF-8 decoding, StapledStream for combining send/receive, tg.start() which blocks until a task signals it's ready - great for server startup - and all the sync primitives you'd expect, portable across backends. -->

---

# Threads & Beyond

| Feature | Benefit |
|---|---|
| **`to_thread` / `from_thread`** | Bidirectional sync↔async bridging with structured cancellation — run blocking code without blocking the event loop, or call async code from a thread |
| **Subinterpreters** | `anyio.to_interpreter.run_sync` subinterpreter helpers for true parallelism (Python 3.13+) |
| **Async `functools`** | `anyio.functools.lru_cache` for async functions |
| **Fully typed** | Great IDE autocompletion and type checker support |

<!-- and more: bidirectional sync/async bridging with structured cancellation, subinterpreter support for true parallelism on 3.13+, async functools like lru_cache, and the whole API is fully typed for great IDE and type checker support. -->

---

# The Advantage of Being on PyPI

In Python 3.13, a number of bug-fixes were applied to asyncio.TaskGroup
but they were considered breaking changes so were not backported to 3.11
or 3.12:

https://docs.python.org/3/whatsnew/3.13.html#asyncio

<!-- practical advantage of AnyIO being a pip-installable package. in Python 3.13 important TaskGroup bugfixes landed - like fixing deadlocks when nested task groups both have failing children. but these were considered breaking changes and weren't backported to 3.11 or 3.12. -->

> Improve the behavior of
> [TaskGroup](https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup)
> when an external cancellation collides with an internal cancellation.
> For example, when two task groups are nested and both experience an
> exception in a child task simultaneously, it was possible that the
> outer task group would hang, because its internal cancellation was
> swallowed by the inner task group.

---

# The Advantage of Being on PyPI (continued)
* you need to use the latest version of Python for fixed asyncio
* Because AnyIO is hosted on PyPI you get bugfixes on all supported python versions
* AnyIO supports Python 3.10+ (dropped EOL 3.9 in v4.13.0)

<!-- with asyncio you need to upgrade your entire Python version for bugfixes. with AnyIO you just pip install the latest and get fixes on every supported Python version. AnyIO dropped EOL Python 3.9 in v4.13.0 — minimum is now 3.10. that's still the power of being on PyPI: bugfixes ship independently of Python releases. -->

---

# Asyncio is not bad

* it's better than Twisted (I once spent a week fixing a missing `six` call
  - asyncio is Python 3 only so this class of bug can't exist)
* but try making an LDAP server without Twisted!
* *some* of the mistakes Twisted made were copied into asyncio
* Curio is good! Unfortunately it's archived
* Trio isn't perfect: it's slower than asyncio, especially with uvloop
  * but better abstractions mean you're *more likely* to use async correctly — e.g. `anyio.Path` instead of blocking pathlib — so your real-world throughput may actually be higher
* AnyIO gives you options and batteries to play with

<!-- I want to be fair: asyncio is not bad. it's a huge improvement over Twisted - I once spent a week debugging a missing `six` call, a whole class of bug that can't exist with asyncio. but try making an LDAP server without Twisted! Curio was great but it's archived. Trio is excellent but slower than asyncio. AnyIO gives you options. -->

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

<style scoped>section { font-size: 22px; }</style>

# Any questions?

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

**Further reading:**
- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO documentation
- [graingert.co.uk/trio-sc](https://graingert.co.uk/trio-sc) - Go statement considered harmful (njs)
- [graingert.co.uk/dijkstra68](https://graingert.co.uk/dijkstra68) - Go To Statement Considered Harmful (1968)
- [graingert.co.uk/dabeaz-gen](https://graingert.co.uk/dabeaz-gen) - Generator Tricks for Systems Programmers
- [graingert.co.uk/dabeaz-coro](https://graingert.co.uk/dabeaz-coro) - A Curious Course on Coroutines and Concurrency
- [graingert.co.uk/dabeaz-final](https://graingert.co.uk/dabeaz-final) - Generators: The Final Frontier
- [docs.python.org/3/whatsnew/3.13.html#asyncio](https://docs.python.org/3/whatsnew/3.13.html#asyncio) - Python 3.13 asyncio changes
- [github.com/python-trio/trio/issues/796](https://github.com/python-trio/trio/issues/796) - Provide standard mechanism for splitting a stream into lines
- [github.com/groove-x/trio-util/issues/22](https://github.com/groove-x/trio-util/issues/22) - Add a LineReader?
- [github.com/python-trio/trio/issues/562](https://github.com/python-trio/trio/issues/562) - Get N items from Channel

<!-- thanks! happy to take questions. I'm graingert on GitHub. -->
