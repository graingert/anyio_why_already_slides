---
marp: true
---

# Why you should use AnyIO and why you might already have it installed 

---

https://graingert.co.uk/why-anyio-already
![graingert](https://avatars.githubusercontent.com/u/413772)

---

- I am a core developer of AnyIO, Twisted and Trio (and a few non-async libraries)
- I have made contributions to the asyncio happy eyeballs support and fixes to
  TaskGroup
- Years of teaching async experience, never actually deployed anything myself

---

* misconception: `asyncio` == `async`/`await`
* the problems with `asyncio.create_task`
* why you should use structured concurrency
* edge cancellation vs level cancellation
* `asyncio.shield` vs shielded CancelScopes
* more anyio features
    * channels (memory object streams) > `asyncio.Queue`
    * `BufferedByteReceiveStream` AnyIO > Trio
    * `anyio.Path`
    * pytest plugin built in
* The advantages of being pip installable
* why you already have AnyIO installed

---


# asyncio != async/await

- Coroutines are generator-based in Python
- not just asyncio can use them because `async`/`await` is totally decoupled from `asyncio`.
- Twisted, Trio, and Curio can support async functions while being completely unrelated to asyncio.
- You can even use `async`/`await` to make your own generators:

---

```python
>>> import types
>>> @types.coroutine
... def _async_yield(v):
...     return (yield v)
...     
>>> async def coro_fn():
...     await _async_yield(1)
...     await _async_yield(2)
...     await _async_yield(3)
...     
>>> coro = coro_fn()
>>> gen = coro.__await__()
>>> list(gen)
[1, 2, 3]
>>> 
```

---

For more generator tricks see also:

- [Generator Tricks for Systems Programmers](https://graingert.co.uk/dabeaz-gen) — `graingert.co.uk/dabeaz-gen`
- [A Curious Course on Coroutines and Concurrency](https://graingert.co.uk/dabeaz-coro) — `graingert.co.uk/dabeaz-coro`
- [Generators: The Final Frontier](https://graingert.co.uk/dabeaz-final) — `graingert.co.uk/dabeaz-final`

---

This means libraries like AnyIO can call either the asyncio API or the
Trio API depending on what library is currently in use:

This is similar in approach to libraries like `six` which let you write
code compatible with Python 2 and Python 3

---

```python
from sniffio import current_async_library
async def sleep_for_one_loop_cycle():
    if current_async_library() == "asyncio":
        fut = asyncio.Future()
        asyncio.create_task(set_fut_result_soon(fut))
        await fut  # calls fut.__await__().send(None)
    elif current_async_library() == "trio":
        event = trio.Event()
        trio.lowlevel.spawn_system_task(set_event_soon, event)
        await event
        """
        this call calls
            (
                _async_yield(
                    WaitTaskRescheduled(abort_func)
                )
                .__await__()
                .send(outcome.Value(None))
            )
        """
    else:  # Twisted?
        raise RuntimeError("unsupported async framework")
```
---

# The Problem with `asyncio.create_task()`

## It's a "go statement" - and go statements break everything

------------------------------------------------------------------------

## What's a "go statement"?

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

------------------------------------------------------------------------

## Problem 1: Functions Aren't Black Boxes Anymore

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

------------------------------------------------------------------------

## Problem 2: Resource Cleanup Breaks

```python
# This LOOKS safe...
async with open("data.csv") as f:
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

------------------------------------------------------------------------

## Problem 3: Error Handling Breaks

```python
async def background_task():
    raise ValueError("Something went wrong!")
# Start background task
task = asyncio.create_task(background_task())
# Error happens... but where does it go?
# Answer: NOWHERE! It's silently dropped!
# (Maybe printed to console if you're lucky)
```

---

**Exceptions can't propagate because there's no stack to unwind**

Compare to regular Python:

```python
def my_function():
    raise ValueError("Something went wrong!")
my_function()  # Exception propagates to caller automatically
```

------------------------------------------------------------------------

## Problem 4: You Can't Tell If Code Is Finished

``` python
async def mystery_function():
    await do_something()
    return "done"

result = await mystery_function()
# Is mystery_function actually done?
# Or did it spawn tasks that are still running?
# NO WAY TO KNOW!
```

**The "return" statement lies to you**

------------------------------------------------------------------------

## The Root Cause: Unstructured Concurrency

![create_task running off on its own](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/6c6ab6845286b6353242edd194cf2e68a2e3bd3f/asyncio_create_task.svg)
**One-way jump = no guaranteed cleanup, no error propagation, no
completion tracking**

------------------------------------------------------------------------

## Real-World Consequences

### In asyncio programs:

❌ **Backpressure problems** - Can't tell how many tasks are running\
❌ **Resource leaks** - Files/sockets stay open because cleanup is
manual\
❌ **Silent failures** - Errors in background tasks get dropped\
❌ **Shutdown hangs** - Can't wait for "done" because tasks are
invisible\
❌ **Race conditions** - Tasks outlive the data they operate on

---

### In data pipelines specifically:

❌ **Timeouts don't work** - Can't cancel tasks you've lost track of\
❌ **Parallel processing breaks** - No way to collect results safely\
❌ **Can't reason about code** - Every function is a potential landmine

------------------------------------------------------------------------

## The Solution: Structured Concurrency with Task Groups

``` python
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

**Task groups enforce: tasks must complete before you can continue**

---

![anyio create task group](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/f613be233c079ba88ae65632da95777a55d0b362/anyio_create_task_group.svg)

------------------------------------------------------------------------

## Dijkstra Was Right (Again)

In 1968, Dijkstra showed that **goto statements break abstraction**

In 2018, we learned that **go statements do the same thing**

| goto (1960s) | asyncio.create_task() (2010s) |
|--------------|-------------------------------|
| One-way jump | One-way jump |
| Breaks function boundaries | Breaks function boundaries |
| No automatic cleanup | No automatic cleanup |
| No error propagation | No error propagation |
| Makes code impossible to reason about | Makes code impossible to reason about |

---

* **Solution then:** Remove goto, add structured control flow
(if/while/functions)
* **Solution now:** Remove create_task, add structured concurrency (task
groups)

------------------------------------------------------------------------

## Key Takeaway

**`asyncio.create_task()` is the `goto` of concurrency**

-   It's powerful
-   It seems convenient
-   **It breaks everything**

**AnyIO task groups are the `if/while/for` of concurrency**

-   They're structured
-   They preserve abstractions
-   They make the language features work again
-   **They let you reason about your code**

------------------------------------------------------------------------

## Further Reading 

**Nathaniel J. Smith (Trio author):**\
["Notes on structured concurrency, or: Go statement considered harmful"](https://graingert.co.uk/trio-sc)\
`graingert.co.uk/trio-sc`

**Original Dijkstra paper:**\
["Go To Statement Considered Harmful" (1968)](https://graingert.co.uk/dijkstra68)\
`graingert.co.uk/dijkstra68`

------------------------------------------------------------------------

# Two most important reasons to use AnyIO
* you can mix it with asyncio and optionally/incrementally add Trio
support
* cancellations are level-triggered.

---

with level cancellation every async operation in a CancelScope will fail
with a CancelledError

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
```

---

# in asyncio
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
```

---

## Edge cancellation can result in deadlocks on asyncio

For example, the following program hangs:

---

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

---

output:

```sh
$ python demo.py
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL HANG)
```

---

After hitting Ctrl+C a few times:
```sh
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL HANG)
^C^Cunhandled exception during asyncio.run() shutdown
task: <Task finished name='Task-1' coro=<main() done, defined at /home/graingert/projects/django/demo.py:4> exception=ExceptionGroup('unhandled errors in a TaskGroup', [RuntimeError('boom')])>
  + Exception Group Traceback (most recent call last):
  |   File "/home/graingert/projects/django/demo.py", line 22, in main
  |     async with asyncio.TaskGroup() as tg:
  |   File "/usr/lib/python3.12/asyncio/taskgroups.py", line 145, in __aexit__
  |     raise me from None
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/home/graingert/projects/django/demo.py", line 20, in crash_soon
    |     raise RuntimeError("boom")
    | RuntimeError: boom
    +------------------------------------
Traceback (most recent call last):
  File "/home/graingert/projects/django/demo.py", line 27, in <module>
    asyncio.run(main())
  File "/usr/lib/python3.12/asyncio/runners.py", line 194, in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/asyncio/runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/asyncio/base_events.py", line 674, in run_until_complete
    self.run_forever()
  File "/usr/lib/python3.12/asyncio/base_events.py", line 641, in run_forever
    self._run_once()
  File "/usr/lib/python3.12/asyncio/base_events.py", line 1949, in _run_once
    event_list = self._selector.select(timeout)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/selectors.py", line 468, in select
    fd_event_list = self._selector.poll(timeout, max_ev)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/asyncio/runners.py", line 157, in _on_sigint
    raise KeyboardInterrupt()
KeyboardInterrupt
```

---

example with anyio

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
            print("awaiting never-completing future (WILL HANG)")
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

---

output:
```sh
$ python demo_anyio.py
task_with_finally running
crash_soon raising
task_with_finally in finally
awaiting never-completing future (WILL NOT HANG)
  + Exception Group Traceback (most recent call last):
  |   File "/home/graingert/projects/django/demo.py", line 27, in <module>
  |     asyncio.run(main())
  |   File "/usr/lib/python3.12/asyncio/runners.py", line 194, in run
  |     return runner.run(main)
  |            ^^^^^^^^^^^^^^^^
  |   File "/usr/lib/python3.12/asyncio/runners.py", line 118, in run
  |     return self._loop.run_until_complete(task)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/usr/lib/python3.12/asyncio/base_events.py", line 687, in run_until_complete
  |     return future.result()
  |            ^^^^^^^^^^^^^^^
  |   File "/home/graingert/projects/django/demo.py", line 22, in main
  |     async with anyio.create_task_group() as tg:
  |   File "/home/graingert/.virtualenvs/anyio_pipdeptree/lib/python3.12/site-packages/anyio/_backends/_asyncio.py", line 783, in __aexit__
  |     raise BaseExceptionGroup(
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/home/graingert/projects/django/demo.py", line 20, in crash_soon
    |     raise RuntimeError("boom")
    | RuntimeError: boom
    +------------------------------------
```

---

This is still a problem when using WebSockets over TLS

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

---

# Shielding from Cancellation

## When you *can't* cancel — even if you want to

Some I/O operations are **uncancellable by nature**, or you must wait for the
cancel to be processed by the OS:

- Waiting for a thread to finish (`loop.run_in_executor`, `anyio.to_thread.run_sync`)
- On Windows IOCP (Proactor)
    - To cancel pending I/O operations in an IOCP (I/O Completion Port) server, use `CancelIoEx` to target specific operations, or `closesocket(handle)`
    to cancel all pending I/O on a socket. Canceled operations complete with `ERROR_OPERATION_ABORTED`, and you must wait for the completion packet before freeing memory.

---

The async framework can raise `CancelledError` in your coroutine, but the **underlying thread keeps running** or **something still needs to wait to be able to clear memory**

You're not cancelling the work — you're just *abandoning* the future that was watching it. 👻

---

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

---

# `asyncio.shield` — The Duct-Tape Approach

```python
async def save_to_db(data):
    # We don't want cancellation to interrupt this
    await asyncio.shield(db.execute(INSERT, data))
    # ⚠️ If cancelled, shield absorbs the cancel...
    # ... but db.execute() keeps running as an orphaned task
    # ⚠️ Edge cancellation means the *next* await might
    # succeed even though we're "cancelled"
```

---

### Problems

❌ **Edge-triggered**: a `CancelledError` sneaks through on the *next* checkpoint after the shield exits  
❌ **Orphaned inner task**: the shielded work keeps running with no owner  
❌ **No scope**: shield applies to one `await`, not a logical block of work  
❌ **Thread can't be shielded**: `run_in_executor` inside a shield still abandons the thread

---

# AnyIO Shielded Cancel Scopes — The Structured Approach

```python
async def save_to_db(data):
    # Level-triggered: cancellation is *held* until we exit the shield
    with anyio.CancelScope(shield=True):
        await anyio.to_thread.run_sync(db_blocking_write, data)
        # Thread runs to completion — no orphan, no abandonment
        await anyio.to_thread.run_sync(db_blocking_flush, data)
        # Still shielded — the *whole scope* is protected
    # Pending cancellation is re-raised here, reliably
# Works correctly even when called inside a task group under timeout:
async def example():
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(save_to_db, important_data)
```

---

### Why it works

✅ **Level-triggered**: cancellation is *deferred*, not lost — re-fires when you leave the scope  
✅ **Thread-aware**: `run_sync` joins the thread; the shield keeps the join alive  
✅ **Scoped**: protect a whole logical block, not just one `await`  
✅ **No orphans**: structured concurrency means every task has an owner

---

# Shielding in Detail

---

## asyncio.shield
![asyncio.shield()](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/65582c063d39717daf957ac203f7bdc54efd841a/asyncio_shield.svg)

---
## CancelScope(shield=True)
![CancelScope(shield=True)](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/65582c063d39717daf957ac203f7bdc54efd841a/anyio_shield.svg)

---

**asyncio.shield is a one-way valve. AnyIO's shield is a pressure vessel** — it holds the cancellation until you're ready to handle it safely.

---

# Comparison

| | `asyncio.shield` | `anyio.CancelScope(shield=True)` |
|---|---|---|
| Cancellation model | Edge (one-shot) | Level (persistent, deferred) |
| Scope | Single `await` | Entire `with` block |
| Thread safety | ❌ Abandons thread | ✅ Joins thread to completion |
| Cancellation after exit | ⚠️ Maybe (edge, unreliable) | ✅ Always re-raised |
| Orphaned tasks | ❌ Yes | ✅ Never |
| Composable | ❌ Not really | ✅ Nests with task groups |

------------------------------------------------------------------------

# More AnyIO Features

---

# Backpressure by Default. Structured. Composable.

* AnyIO provides `MemoryObjectSendStream` and `MemoryObjectReceiveStream`
* like `asyncio.Queue` but you don't need to keep a count of how many producer/consumers you have
  * you just make a clone for each producer/consumer
  * use a `with` or `async with` to close the clones.
  * Once all the clones of one end of the memory object stream are closed
  iterating the other end will raise StopAsyncIteration.

---

```python
import anyio
async def consume_ws(url, stream):
    async with stream, await connect_ws(url) as ws:
        async for msg in ws:
            await stream.send(msg)
async def news_and_weather():
    tx, rx = anyio.create_memory_object_stream[bytes]()  # default buffer size = 0
    async with tx, rx, anyio.create_task_group() as tg:
        tg.start_soon(consume_ws, "ws://example.com/news", tx.clone())
        tg.start_soon(consume_ws, "ws://example.com/weather", tx.clone())
        tx.close()
        async for item in rx:
            print(item)
anyio.run(news_and_weather)
```

---

### Key properties

-   ✅ **Buffer size defaults to 0** → automatic backpressure

-   ✅ `async for` works naturally

-   ✅ `aclose()` signals end-of-stream

-   ✅ `clone()` enables multiple consumers safely

-   ✅ Structured shutdown

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

---

### Problems

-   ❌ Unbounded by default (no backpressure)

-   ❌ No async iteration

-   ❌ No built-in structured close (historically)

-   ❌ No clone() so requires sentinel values or custom shutdown logic

------------------------------------------------------------------------

# asyncio.Queue.shutdown() (3.13+)

Python 3.13 introduces:

```python
q.shutdown()
```

But:

-   Only on *new* Python

-   Not widely deployed yet

-   Still no cloning

-   Still no structured fan-out

------------------------------------------------------------------------
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

------------------------------------------------------------------------
# "If I'm already using Trio, I don't need AnyIO."

Most people assume this.

But AnyIO adds real value even on the Trio backend.

- Trio gives you structured concurrency.
- AnyIO gives you portability + batteries included.

---

### What AnyIO adds on top of Trio

-   ✅ Backend portability (asyncio, Trio)

-   ✅ A stable public API for libraries

-   ✅ High-level stream utilities

-   ✅ Memory object streams

-   ✅ Buffered byte streams

-   ✅ Stapled streams

-   ✅ Thread/subprocess helpers

------------------------------------------------------------------------

# Trio vs AnyIO

- Trio is a minimal framework
    - only gives you what is mandatory of a network framework
- AnyIO is a portability + abstraction layer with batteries included.

---

If you write a library directly against Trio:

-   You lock out asyncio users.

If you write against AnyIO:

-   Trio users still get full Trio semantics.

-   asyncio users can incrementally adopt
    level cancellation or structured concurrency.

-   You get a bunch of cool extra tools

------------------------------------------------------------------------

# Buffered Byte Streams (AnyIO Feature Trio Lacks)

Trio provides `SendStream` / `ReceiveStream`.

But it does **not** provide:

-   Buffered reads

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Automatic read buffering

AnyIO does.

------------------------------------------------------------------------

# Demo --- AnyIO Buffered Byte Streams

```python
import anyio
async def main():
    send, receive = anyio.create_memory_object_stream[bytes]()
    async def producer():
        await send.send(b"hello\nworld\n")
        await send.aclose()
    async def consumer():
        buffered = anyio.streams.buffered.BufferedByteReceiveStream(receive)
        line1 = await buffered.receive_until(b"\n", 4096)
        print("line1:", line1)
        line2 = await buffered.receive_until(b"\n", 4096)
        print("line2:", line2)
    async with anyio.create_task_group() as tg:
        tg.start_soon(producer)
        tg.start_soon(consumer)
anyio.run(main)
```

---

### Output

```sh
$ python demo_buffered_bytes.py
line1: b'hello'
line2: b'world'
```

------------------------------------------------------------------------

### What Just Happened?

-   The producer sent both lines in one chunk.

-   The consumer parsed them cleanly by delimiter.

-   No manual buffering.

-   No partial read bookkeeping.

------------------------------------------------------------------------

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


---
Example (simplified):

I asked ChatGPT and it gave me this, can you spot the bug?

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
        buffer = bytearray(rest)
```
---

## Quadratic performance in the inner loop

Every iteration of `while b"\n" in buffer` does `buffer = bytearray(rest)`,
copying the remaining data each time. If you receive a chunk with many
newlines, this is O(n²) in the number of bytes.

------------------------------------------------------------------------

# What AnyIO Adds Here

`BufferedByteReceiveStream` gives you:

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Proper EOF semantics

-   Efficient internal buffering

-   Works on both Trio and asyncio backends

This is a real ergonomic upgrade.

---
- Trio gives you safety.
- AnyIO gives you safety **plus portability and batteries included.**

---

citation:

-   https://github.com/python-trio/trio/issues/796
-   https://github.com/groove-x/trio-util/issues/22
-   https://github.com/python-trio/trio/issues/562

------------------------------------------------------------------------

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

---

## The Solution: anyio.Path

```python
import anyio
async def amain():
    # ✅ All truly async - doesn't block!
    path = anyio.Path("data.txt")
    await path.write_text("Hello!")    # Async
    content = await path.read_text()  # Async
    exists = await path.exists()      # Async
```

### Same API as pathlib, but async-native

------------------------------------------------------------------------

## Real Power: Parallel File Operations

```python
# Process multiple files in parallel
data_dir = anyio.Path("training_data")
results = []
async def process_and_append(p):
    content = await p.read_text()
    results.append(parse_csv(content))
async with anyio.create_task_group() as tg:
    async for path in data_dir.iterdir():
        if await path.is_file() and path.suffix == '.csv':
            tg.start_soon(process_and_append, path)
# All files processed concurrently!
```

------------------------------------------------------------------------

## Key Features

| Feature | pathlib | anyio.Path |
|---------|---------|------------|
| Async operations | ❌ Blocks | ✅ async with threads |
| Parallel I/O | ❌ Sequential | ✅ Works with task groups |
| Event loop friendly | ❌ Blocks | ✅ Non-blocking |
| API compatibility | ✅ Standard | ✅ Same interface but async |
| Type hints | ✅ Yes | ✅ Yes |

**Key Takeaway:** Drop-in replacement for pathlib that actually respects
async/await

------------------------------------------------------------------------

# pytest plugin

* AnyIO ships with a pytest plugin that it uses to test itself.
* This means if you already depend on AnyIO you don't need pytest-asyncio as well.

```python
@pytest.mark.anyio
async def test_something():
    assert await something() == "result"
```

---
By default the plugin runs your tests under both asyncio and Trio, so if you're still gradually migrating to AnyIO and still require asyncio support, you can run your tests in asyncio mode only by adding the following to your root `conftest.py`

```python
@pytest.fixture
def anyio_backend():
    return 'asyncio'
```
---

# The Advantage of Being on PyPI

In Python 3.13, a number of bug-fixes were applied to asyncio.TaskGroup
but they were considered breaking changes so were not backported to 3.11
or 3.12:

---

https://docs.python.org/3/whatsnew/3.13.html#asyncio

> Improve the behavior of
> [TaskGroup](https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup)
> when an external cancellation collides with an internal cancellation.
> For example, when two task groups are nested and both experience an
> exception in a child task simultaneously, it was possible that the
> outer task group would hang, because its internal cancellation was
> swallowed by the inner task group.

---

* you need to use the latest version of Python for fixed asyncio
* Because AnyIO is hosted on PyPI you get bugfixes on all supported python versions
* AnyIO is currently still supporting the EOL Python 3.9 (as of v4.12.1)

---

# Asyncio is not bad

* it's better than Twisted (I spent a week fixing a missing `six` call
  that wouldn't have happened on Python 3.6 with asyncio)
* but try making an LDAP server without Twisted!
* *some* of the mistakes Twisted made were copied into asyncio
* Curio is good! Unfortunately it's archived
* Trio isn't perfect: it's slower than asyncio, especially with uvloop
* AnyIO gives you options and batteries to play with

------------------------------------------------------------------------

Normally at this stage of my talk I'd ask you to go run

# ~~pip install anyio~~

but if you're in this room you probably already have it in your virtual
environments!

---

```sh
$ pip install httpx fastapi jupyter mcp pipdeptree
$ pipdeptree -p anyio -r  # reverse dependencies (dependants) of anyio
```

Watch the tree unfold: loads of packages you use daily depend on AnyIO

---

output:
```
anyio==4.12.1
├── starlette==0.52.1 [requires: anyio>=3.6.2,<5]
│   ├── fastapi==0.129.0 [requires: starlette>=0.40.0,<1.0.0]
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

------------------------------------------------------------------------

* I've given you a whistle-stop tour of some of my favourite features, there's loads more
   * and more being added all the time
* I hope I've persuaded you to give AnyIO a try
* you might as well give it a go if you already have it installed
---

# Any questions?
