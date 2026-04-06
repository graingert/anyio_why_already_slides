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
- AnyIO works on both asyncio and Trio - like `six` for async frameworks

<!-- async/await is NOT asyncio. it's just syntax built on top of the generator protocol. any framework can drive coroutines - Twisted, Trio, Curio all do it with completely different event loops. AnyIO works on both asyncio and Trio, doing the right thing automatically. -->

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

# The Problems with `asyncio.create_task()`

## It's a "go statement" - and go statements break everything

```python
asyncio.create_task(myfunc())  # Fire and forget!
# Control returns immediately, myfunc() runs in background
# No guaranteed reunion point
```

**Key problem:** Control flow splits with **one-way jump**

- ❌ Functions aren't black boxes - hidden background tasks survive returns
- ❌ Resource cleanup breaks - `async with` can't track orphaned tasks
- ❌ Errors silently drop - no stack to propagate up

<!-- asyncio.create_task is what njs calls a "go statement". it's a one-way jump that splits control flow. parent spawns a child and immediately moves on. child runs off unsupervised. no guaranteed reunion point. functions stop being black boxes, resource cleanup breaks, and errors get silently dropped. -->

---

# Problem: Resource Cleanup Breaks

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

<!-- concrete example. you open a file in an async with block, pass the handle to process_file, block exits, file closes. but if process_file secretly spawned a background task still reading from that handle - boom, error on a closed file. context managers are broken. -->

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

# Two most important reasons to use AnyIO
* incrementally adoptable - drop into an existing asyncio codebase, and your code automatically works on Trio too
* cancellations are level-triggered

<!-- two biggest selling points. first: it's additive - you can sprinkle it into an existing asyncio codebase and optionally add Trio support later. second, and this is the one I really care about: cancellations are level-triggered. this is subtle but it prevents real bugs. -->

---

# Level-Triggered Cancellation

With level cancellation every async operation in a cancelled CancelScope (a scoped
region of code that can be cancelled or given a deadline) will fail with a `CancelledError`

```python
import anyio

async def example():
    with anyio.fail_after(0):
        try:
            await anyio.sleep(1)  # raises CancelledError
        finally:
            await anyio.sleep(1000)  # also raises CancelledError
    # raises TimeoutError as you leave the scope

anyio.run(example)
# Note: not anyio.run(example()) - anyio.run takes a callable, not a coroutine
```

<!-- with level cancellation, once a CancelScope is cancelled, EVERY await inside it raises CancelledError. even in the finally block. the cancellation is a state, not an event. so fail_after(0) means every single await in that scope fails immediately. predictable and safe. note: anyio.run takes a callable, not a coroutine - so no parentheses on example. -->

---

# Edge-Triggered Cancellation (asyncio)

With edge cancellation, `CancelledError` is a one-shot event - once consumed, the next await succeeds even inside a cancelled scope.

```python
import asyncio

async def example():
    async with asyncio.timeout(0):
        try:
            await asyncio.sleep(1)   # raises CancelledError
        finally:
            await asyncio.sleep(1000)  # waits 1000 seconds
    # raises TimeoutError.... eventually

asyncio.run(example())
# Note: not asyncio.run(example) - asyncio.run takes a coroutine, not a callable
```

<!-- now look at the same thing with asyncio. the first await raises CancelledError as expected. but in the finally block the cancellation has been consumed - it was edge-triggered, a one-shot event. so await asyncio.sleep(1000) actually waits 1000 seconds. your timeout of 0 becomes a timeout of 1000. this is a real class of bug. -->

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
<!-- edge cancellation doesn't just cause slowdowns - it can deadlock. here's a real example that hangs forever. crash_soon raises, the TaskGroup cancels task_with_finally, but because cancellation is edge-triggered the finally block's `await never` is NOT cancelled - it just hangs. you have to Ctrl+C multiple times to kill it. with AnyIO's level-triggered cancellation the `await never` is immediately cancelled too. no hang. -->

---

# Shielding from Cancellation

Sometimes you can cancel the work, but you **must wait for it to finish dying**:

- Subprocesses: you can `terminate()` but must still `wait()` to join - otherwise zombie processes
- Threads: can't be interrupted at all - must wait for completion
- Windows IOCP: must wait for cancellation acknowledgement before freeing memory

<!-- sometimes you can cancel the work but you can't just walk away. subprocesses: terminate then join. threads: can't cancel at all. this is where shielding comes in. -->

---

# `asyncio.shield` - The Duct-Tape Approach

```python
try:
    await asyncio.shield(process.wait())
    # ⚠️ If cancelled, shield absorbs the cancel...
    # ... but process.wait() keeps running as a detached task
except asyncio.CancelledError:
    process.terminate()
    # ⚠️ Edge cancellation: this await might be cancelled again
    # before the process exits - leaving it un-joined
    await process.wait()
    raise
```

- ❌ Wraps ONE `await`, orphans the inner task
- ❌ Edge-triggered: cleanup can be interrupted again
- ❌ Can't compose terminate + join as a single logical unit

<!-- asyncio.shield wraps one await and creates an orphaned task. edge cancellation means the process.wait() in the except block can be cancelled again before the process exits, leaving it un-joined. -->

---

# AnyIO Shielded Cancel Scopes

```python
try:
    await process.wait()
    return process.returncode
except anyio.get_cancelled_exc_class():
    process.terminate()
    # Shield the join: we MUST wait for the process to exit
    with anyio.CancelScope(shield=True):
        await process.wait()  # shielded - always completes
    raise
# Pending cancellation reliably re-raised after the shielded scope
```

- ✅ Level-triggered: cancellation is deferred, not lost
- ✅ Scoped: protect the whole terminate-and-join block
- ✅ No zombies: every process is joined

<!-- AnyIO's CancelScope(shield=True) protects a whole block. level-triggered cancellation is deferred and reliably re-raised after. no zombies, no orphans. -->

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

<!-- full comparison side by side. every row is a win for AnyIO. key insight: shielding should be a scope, not a wrapper around a single expression. -->

---

# More AnyIO Features: Memory Object Streams

<!-- ok we've covered the big conceptual stuff - structured concurrency and level-triggered cancellation. now let me show you some practical features. -->

* AnyIO provides `MemoryObjectSendStream` and `MemoryObjectReceiveStream`
* like `asyncio.Queue` but with backpressure, `clone()`, structured shutdown, and `async for`
  * you just make a clone for each producer/consumer
  * use a `with` or `async with` to close the clones
  * Once all the clones of one end are closed, iterating the other end will raise StopAsyncIteration

<!-- memory object streams are like asyncio.Queue but designed right. the killer feature is clone() - each producer/consumer gets their own clone, and when all clones of one end are closed the other end gets a clean StopAsyncIteration. no sentinel values, no manual counting. -->

---

# Memory Object Streams: Full Example

```python
async def consume_ws(url, stream):
    with stream:              # sync - runs before first await
        async with await connect_ws(url) as ws:
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

anyio.run(news_and_weather)
```

<!-- two WebSocket consumers, each with a clone of the send stream, feeding a single receive stream. when both producers finish their clones close, original tx is already closed, so the async for on rx terminates naturally. fully structured shutdown with zero boilerplate. -->

---

# Key Properties

- ✅ Buffer size defaults to 0 → automatic backpressure
- ✅ `clone()` + structured shutdown - unlike asyncio, AnyIO tasks always run to their first `await` before cancellation, so `with stream:` always closes the clone
- ✅ `async for` works naturally, `close()` signals end-of-stream

<!-- default buffer size is 0 so you get backpressure for free. the synchronous `with stream:` runs before any await, so __exit__ always fires and the clone is always closed. -->

---

<style scoped>section { font-size: 20px; padding-top: 10px; }</style>

# Batteries Included

| Category | Feature | Benefit |
|---|---|---|
| **Streams** | `BufferedByteReceiveStream` | `receive_until(delimiter)`, `receive_exactly(n)` - even Trio doesn't have this |
| | `TextReceiveStream` | Incremental UTF-8 decoding over any byte stream |
| | `StapledStream` | Combine separate send/receive into one bidirectional stream |
| **File I/O** | `anyio.Path` | Async drop-in for `pathlib` (no more blocking the event loop) |
| **Testing** | Built-in pytest plugin | `@pytest.mark.anyio` - no need for `pytest-asyncio` |
| **Networking** | TCP/UDP/TLS/subprocesses | Happy Eyeballs built in; async stream I/O |
| **Concurrency** | `tg.start()` | Blocks until the task signals it's ready |
| | Synchronization primitives | `Lock`, `Event`, `Semaphore`, `CapacityLimiter` - portable |
| **Threads** | `to_thread` / `from_thread` | Bidirectional sync↔async bridging with structured cancellation |
| | Subinterpreters | `anyio.to_interpreter.run_sync` for true parallelism (3.13+) |
| **Types** | Fully typed | Great IDE autocompletion and type checker support |

<!-- AnyIO is batteries included. buffered byte reads Trio doesn't have, async pathlib, built-in pytest plugin, full networking stack, bidirectional thread bridging, subinterpreters, and the whole API is fully typed. -->

---
<style scoped>section { font-size: 26px; }</style>

# The Advantage of Being on PyPI

* Python 3.13 fixed TaskGroup deadlocks — but those fixes weren't backported to 3.11/3.12

from the [Python 3.13 changelog](https://docs.python.org/3/whatsnew/3.13.html#asyncio) - `docs.python.org/3/whatsnew/3.13.html#asyncio`:

> Improve the behavior of TaskGroup when an external cancellation collides
> with an internal cancellation. For example, when two task groups are
> nested and both experience an exception in a child task simultaneously,
> it was possible that the outer task group would hang, because its
> internal cancellation was swallowed by the inner task group.

* With asyncio, you need to upgrade your **entire Python version** for bugfixes
* Because AnyIO is on PyPI, you get bugfixes on **all supported Python versions**
* AnyIO supports Python 3.10+ (dropped EOL 3.9 in v4.13.0)

<!-- practical advantage of being pip-installable. with asyncio you need to upgrade your entire Python for bugfixes. with AnyIO you just pip install the latest and get fixes everywhere. -->

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

# Wrap Up

* remember: `asyncio` != `async`/`await` - other async frameworks exist (Twisted, Trio, Curio) and AnyIO works across asyncio and Trio
* I've given you a whistle-stop tour of some of my favourite features, there's loads more
   * and more being added all the time
* I hope I've persuaded you to give AnyIO a try
* you might as well give it a go if you already have it installed

<!-- to wrap up: asyncio is not the only async framework - async/await is decoupled from any event loop and other frameworks like Twisted, Trio, and Curio all use the same syntax. AnyIO works across asyncio and Trio. structured concurrency, level-triggered cancellation, great batteries. you've probably already got it installed. give it a go. -->

---

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

<!-- thanks! happy to take questions. I'm graingert on GitHub. -->
