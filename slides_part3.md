---
marp: true
html: true
---
# Why you should use AnyIO — Part 3 of 3

### AnyIO Features and Why You Already Have It

https://graingert.co.uk/why-anyio-already

<!-- Part 3 of 3 -->

---

# About Me

<img src="https://avatars.githubusercontent.com/u/413772" alt="graingert" style="display: block; margin: 0 auto;" width="250">

<style scoped>section { font-size: 22px; }</style>

**Networking & async:**
- Core developer of AnyIO, Twisted, and Trio
- CPython triager — asyncio contributor
- uvloop contributor — including Python 3.14 compatibility (AbstractChildWatcher removal)

**Other open source:**
- `PyPy`, `pytest-dev`, `PyCQA`, `Dask` and others

<!-- I'm Thomas Grainger, graingert on GitHub. I'm a core dev on AnyIO, Twisted, and Trio. I've contributed to CPython asyncio itself - the happy eyeballs implementation and various TaskGroup fixes. -->

---

<style scoped>section{font-size:22px; padding-top:10px;}</style>

# Part 3 Contents

* `asyncio` != `async`/`await` — the most important take-away (generators all the way down)
* Memory object streams — backpressure by default, structured, composable
  * Full example, key properties, `async with` shortcut
  * Comparison with `asyncio.Queue` — problems and `shutdown()` (3.13+)
* "If I'm already using Trio, I don't need AnyIO" — why you do
* Writing libraries: target AnyIO, not Trio
* Buffered byte streams — `receive_until` / `receive_exactly`
  * Demo, output, and how you'd do this in Trio
  * Can you spot the performance footgun? Quadratic I/O anti-pattern
* `anyio.Path` — async drop-in for `pathlib.Path`
  * Key features + parallel file operations
* Built-in pytest plugin + limiting to asyncio
* Networking & I/O · Streams & Concurrency · Threads & Beyond
* The advantage of being on PyPI
* Asyncio is not bad
* Why you probably already have AnyIO installed


<!-- here's the plan for this part. -->

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
├── httpx==0.28.1 [requires: anyio]
│   ├── jupyterlab==4.5.6 [requires: httpx>=0.25.0,<1]
│   │   ├── jupyter==1.1.1 [requires: jupyterlab]
│   │   └── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │       └── jupyter==1.1.1 [requires: notebook]
│   └── mcp==1.27.0 [requires: httpx>=0.27.1]
├── starlette==1.0.0 [requires: anyio>=3.6.2,<5]
│   ├── fastapi==0.135.3 [requires: starlette>=0.46.0]
│   ├── sse-starlette==3.3.4 [requires: starlette>=0.49.1]
│   │   └── mcp==1.27.0 [requires: sse-starlette>=1.6.1]
│   └── mcp==1.27.0 [requires: starlette>=0.27]
├── jupyter_server==2.17.0 [requires: anyio>=3.1.0]
│   ├── jupyter-lsp==2.3.1 [requires: jupyter_server>=1.1.2]
│   │   └── jupyterlab==4.5.6 [requires: jupyter-lsp>=2.0.0]
│   │       ├── jupyter==1.1.1 [requires: jupyterlab]
│   │       └── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │           └── jupyter==1.1.1 [requires: notebook]
│   ├── notebook==7.5.5 [requires: jupyter_server>=2.4.0,<3]
│   │   └── jupyter==1.1.1 [requires: notebook]
│   ├── jupyterlab_server==2.28.0 [requires: jupyter_server>=1.21,<3]
│   │   ├── notebook==7.5.5 [requires: jupyterlab_server>=2.28.0,<3]
│   │   │   └── jupyter==1.1.1 [requires: notebook]
│   │   └── jupyterlab==4.5.6 [requires: jupyterlab_server>=2.28.0,<3]
│   │       ├── jupyter==1.1.1 [requires: jupyterlab]
│   │       └── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │           └── jupyter==1.1.1 [requires: notebook]
│   ├── notebook_shim==0.2.4 [requires: jupyter_server>=1.8,<3]
│   │   ├── notebook==7.5.5 [requires: notebook_shim>=0.2,<0.3]
│   │   │   └── jupyter==1.1.1 [requires: notebook]
│   │   └── jupyterlab==4.5.6 [requires: notebook_shim>=0.2]
│   │       ├── jupyter==1.1.1 [requires: jupyterlab]
│   │       └── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│   │           └── jupyter==1.1.1 [requires: notebook]
│   └── jupyterlab==4.5.6 [requires: jupyter_server>=2.4.0,<3]
│       ├── jupyter==1.1.1 [requires: jupyterlab]
│       └── notebook==7.5.5 [requires: jupyterlab>=4.5.6,<4.6]
│           └── jupyter==1.1.1 [requires: notebook]
├── sse-starlette==3.3.4 [requires: anyio>=4.7.0]
│   └── mcp==1.27.0 [requires: sse-starlette>=1.6.1]
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

<!-- thanks! happy to take questions. I'm graingert on GitHub. -->

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

**Further reading:**
- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO documentation
- [graingert.co.uk/dabeaz-gen](https://graingert.co.uk/dabeaz-gen) — Generator Tricks for Systems Programmers
- [graingert.co.uk/dabeaz-coro](https://graingert.co.uk/dabeaz-coro) — A Curious Course on Coroutines and Concurrency
- [graingert.co.uk/dabeaz-final](https://graingert.co.uk/dabeaz-final) — Generators: The Final Frontier
- [docs.python.org/3/whatsnew/3.13.html#asyncio](https://docs.python.org/3/whatsnew/3.13.html#asyncio) — Python 3.13 asyncio changes
- [github.com/python-trio/trio/issues/796](https://github.com/python-trio/trio/issues/796) — Provide standard mechanism for splitting a stream into lines
- [github.com/groove-x/trio-util/issues/22](https://github.com/groove-x/trio-util/issues/22) — Add a LineReader?
- [github.com/python-trio/trio/issues/562](https://github.com/python-trio/trio/issues/562) — Get N items from Channel
