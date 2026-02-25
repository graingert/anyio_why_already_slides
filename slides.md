---
marp: true
---

# Why you should use AnyIO and why you might already have it installed 

<!-- Welcome everyone! Today I'm going to talk about AnyIO — what it is, why it's great, and why there's a good chance you've already got it sitting in your virtualenvs. -->

---

https://graingert.co.uk/why-anyio-already
![graingert](https://avatars.githubusercontent.com/u/413772)

<!-- Hi, I'm Thomas Grainger. You can find me online at graingert.co.uk. The slides for this talk are available at the link shown. -->

---

- I am a core developer of AnyIO, Twisted and Trio (and a few non-async libraries)
- I have made contributions to the asyncio happy eyeballs support and fixes to
  TaskGroup
- Years of teaching async, never actually deployed anything myself

<!-- Quick background on me — I work on the async ecosystem across multiple frameworks. I've contributed to asyncio itself, particularly the happy eyeballs implementation and TaskGroup bugfixes. I should mention that while I've spent years teaching people async Python, I'm the cobbler whose children have no shoes — I've never actually deployed an async service myself. -->

---
<style scoped>section{font-size:22px;}</style>
* misconception: `asyncio` == `async`/`await`
* the problems with `asyncio.create_task`
* why you should use structured concurrency
* edge cancellation vs level cancellation
* `asyncio.shield` vs shielded CancelScopes
* some of my favourite anyio features
    * channels (memory object streams) > `asyncio.Queue`
    * `BufferedByteReceiveStream` AnyIO > Trio
    * `anyio.Path`
    * pytest plugin built in
    * summary of features not covered so far
* The advantages of being pip installable
* why you already have AnyIO installed

<!-- Here's the roadmap for the talk. We'll start by clearing up a common misconception, then dig into why create_task is problematic, cover structured concurrency and cancellation, look at some of my favourite AnyIO features, and finish by showing that you've probably already got AnyIO installed without knowing it. -->

---


# asyncio != async/await

- Coroutines are generator-based in Python
- not just asyncio can use them because `async`/`await` is totally decoupled from `asyncio`.
- Twisted, Trio, and Curio can support async functions while being completely unrelated to asyncio.
- You can even use `async`/`await` to make your own generators:

<!-- This is the most common misconception I encounter: people think asyncio IS async/await. But the language syntax is completely decoupled from the runtime. async/await is just syntactic sugar over generators — any framework can drive them. Twisted, Trio, Curio all use the same syntax with completely different runtimes underneath. You can even abuse async/await to build plain old generators, as I'll show next. -->

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

<!-- Here's the proof. We use types.coroutine to make a raw coroutine that just yields values, then build an async function on top of it. When we grab the __await__ iterator and drain it, we get a plain list. No event loop, no asyncio, just generators all the way down. This is the fundamental mechanism that lets multiple async frameworks coexist. -->

---

For more generator tricks see also:

- [Generator Tricks for Systems Programmers](https://graingert.co.uk/dabeaz-gen) — `graingert.co.uk/dabeaz-gen`
- [A Curious Course on Coroutines and Concurrency](https://graingert.co.uk/dabeaz-coro) — `graingert.co.uk/dabeaz-coro`
- [Generators: The Final Frontier](https://graingert.co.uk/dabeaz-final) — `graingert.co.uk/dabeaz-final`

<!-- If you want to go deeper on the generator machinery underlying all of this, David Beazley's talks are the gold standard. These three talks progressively build from basic generators to full coroutine-based concurrency. Highly recommended viewing. -->

---

This means libraries like AnyIO can call either the asyncio API or the
Trio API depending on what library is currently in use:

This is similar in approach to libraries like `six` which let you write
code compatible with Python 2 and Python 3

<!-- So how does AnyIO actually work? It uses sniffio to detect which async framework is currently running, then dispatches to the right API. Think of it like the old six library for Python 2/3 compatibility — write once, run on both asyncio and Trio. -->

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

<!-- Here's a simplified view of what happens under the hood. sniffio detects which library is running, then we call the appropriate low-level API. Notice how different the internals are — asyncio uses Futures and create_task, while Trio uses Events and spawn_system_task with a completely different yield protocol. AnyIO abstracts all of this away so you don't have to care. -->
---

# The Problem with `asyncio.create_task()`

## It's a "go statement" - and go statements break everything

<!-- This is the core argument of the talk. asyncio.create_task is what Nathaniel Smith calls a "go statement" — it's a one-way jump that splits control flow. This pattern is fundamentally broken for the same reasons goto was broken, and I'm going to show you exactly why. -->

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

<!-- The pattern is the same across languages — asyncio.create_task, Go's go keyword, threading.Thread.start. The parent spawns a child and immediately moves on. The child runs off on its own with no supervision. There's no guaranteed point where parent and child meet up again. This one-way jump is the root of all the problems I'm about to show you. -->

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

<!-- This is devastating for code maintainability. When you call a function, you have no idea whether it spawned background tasks that are still running after it returns. You'd have to read every line of source code, transitively, to know if a function is truly "done." This completely breaks the abstraction of functions as black boxes. -->

------------------------------------------------------------------------

## Problem 2: Resource Cleanup Breaks

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

<!-- Here's a concrete example. You open a file in an async with block, pass the handle to process_file, and when the block exits, the file closes. But if process_file secretly spawned a background task that's still reading from that file handle — boom, you get an error on a closed file. The async with block can't protect you because it has no idea about the orphaned task. Context managers, the primary cleanup mechanism in Python, are broken. -->

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

<!-- Errors in background tasks have nowhere to go. In normal synchronous Python, exceptions propagate up the call stack automatically. But a fire-and-forget task has no parent stack to unwind — it's an orphan. The error just gets silently dropped. If you're lucky, asyncio prints a warning to the console, but your program keeps running in a broken state. -->

---

**Exceptions can't propagate because there's no stack to unwind**

Compare to regular Python:

```python
def my_function():
    raise ValueError("Something went wrong!")
my_function()  # Exception propagates to caller automatically
```

<!-- Compare: in synchronous Python, when a function raises, the exception automatically propagates to the caller. That's just how the call stack works. create_task breaks this fundamental contract. -->

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

<!-- When mystery_function returns "done", is it actually done? You have absolutely no way to know without reading every line of code it calls. The return statement, which is supposed to mean "I'm finished," now lies to you. This is the most insidious problem — it erodes trust in basic language semantics. -->

------------------------------------------------------------------------

## The Root Cause: Unstructured Concurrency

![create_task running off on its own](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/6c6ab6845286b6353242edd194cf2e68a2e3bd3f/asyncio_create_task.svg)
**One-way jump = no guaranteed cleanup, no error propagation, no
completion tracking**

<!-- This diagram shows the core problem visually. create_task launches a task that runs off on its own with no structural connection back to the parent. There's no guaranteed reunion point. This is unstructured concurrency — the concurrent equivalent of spaghetti code with gotos. -->

------------------------------------------------------------------------

## Real-World Consequences

### In asyncio programs:

❌ **Resource leaks** - Files/sockets stay open because cleanup is
manual\
❌ **Silent failures** - Errors in background tasks get dropped\
❌ **Shutdown hangs** - Can't wait for "done" because tasks are
invisible\
❌ **Operations on closed files** - Tasks outlive the data they operate on

### In data pipelines specifically:

❌ **Timeouts don't work** - Can't cancel tasks you've lost track of\
❌ **Can't reason about code** - Every function is a potential landmine

<!-- These aren't theoretical problems — they're bugs that people hit in production every day. Resource leaks, silent failures, shutdown hangs, operations on closed files. And in data pipelines specifically, timeouts become meaningless because you can't cancel tasks you've lost track of. -->

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

<!-- Here's the fix: task groups. With a task group, you can't exit the async with block until ALL child tasks have finished. Errors propagate automatically. Cleanup happens automatically. When the function returns, it's actually done. This is structured concurrency — the same revolution that if/while/for brought to control flow in the 1960s. -->

---

![anyio create task group](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/fc99a684e55e738e6cdc9eb62dc80cbafab51f5c/anyio_create_task_group.svg)

<!-- Compare this diagram with the previous one. Now the tasks are contained within the task group scope. They fan out, do their work, and then fan back in before the parent can continue. It's a structured, predictable pattern. -->

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

<!-- The parallel to Dijkstra's goto paper is striking. Every single problem with goto in the 1960s maps directly to a problem with create_task today. One-way jumps, broken function boundaries, no cleanup, no error propagation, impossible to reason about. History is rhyming. -->

---

* **Solution then:** Remove goto, add structured control flow
(if/while/functions)
* **Solution now:** Remove create_task, add structured concurrency (task
groups)

<!-- The solution is the same too. In the 60s we removed goto and replaced it with structured control flow. Now we remove create_task and replace it with task groups. Same pattern, different era. -->

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

<!-- This is the slide I want you to remember. create_task is goto. Task groups are if/while/for. If someone told you to use goto in 2025, you'd laugh. Start treating create_task the same way. -->

------------------------------------------------------------------------

## Further Reading 

**Nathaniel J. Smith (Trio author):**\
["Notes on structured concurrency, or: Go statement considered harmful"](https://graingert.co.uk/trio-sc)\
`graingert.co.uk/trio-sc`

**Original Dijkstra paper:**\
["Go To Statement Considered Harmful" (1968)](https://graingert.co.uk/dijkstra68)\
`graingert.co.uk/dijkstra68`

<!-- If you want to go deeper, Nathaniel's blog post is the definitive argument for structured concurrency. And Dijkstra's original paper is a surprisingly easy and fun read — it's only a page long. -->

------------------------------------------------------------------------

# Two most important reasons to use AnyIO
* you can mix it with asyncio and optionally/incrementally add Trio
support
* cancellations are level-triggered.

<!-- These are the two biggest selling points of AnyIO. First, it's additive — you can sprinkle it into an existing asyncio codebase and optionally add Trio support later. Second, and this is the one I really want to drive home, is level-triggered cancellation. This is a subtle but critical difference that prevents real bugs. -->

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

<!-- With level cancellation, once a CancelScope is cancelled, EVERY await inside it raises CancelledError. Even in the finally block. The cancellation is persistent — it's a state, not an event. So fail_after(0) means every single await in that scope will fail immediately. This is predictable and safe. -->

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

<!-- Now look at the same thing with asyncio. The first await raises CancelledError as expected. But in the finally block, the cancellation has already been consumed — it was edge-triggered, a one-shot event. So await asyncio.sleep(1000) actually waits 1000 seconds! The timeout of 0 becomes a timeout of 1000. This is a real class of bug that bites people in production. -->

---

## Edge cancellation can result in deadlocks on asyncio

For example, the following program hangs:

<!-- Edge cancellation doesn't just cause slowdowns — it can cause full deadlocks. Here's a real example that hangs indefinitely. -->

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

output + after hitting Ctrl+C a few times:

<!-- Walk through the code: task_with_finally sleeps, then in its finally block it awaits a Future that never completes. crash_soon raises after 1 second. The TaskGroup cancels task_with_finally, but because cancellation is edge-triggered, the finally block's "await never" is NOT cancelled — it just hangs forever. You have to Ctrl+C multiple times to kill it. -->

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

<!-- That's a lot of traceback just to say "your program hung and you had to kill it." Notice the program didn't exit cleanly — we had to interrupt it multiple times. The actual error from crash_soon only surfaces after we force-kill the process. -->

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

<!-- Now the same program with AnyIO's create_task_group. The only change is using anyio.create_task_group instead of asyncio.TaskGroup. Because AnyIO uses level-triggered cancellation, when crash_soon raises, the cancellation of task_with_finally persists into its finally block. The "await never" is immediately cancelled too. No hang! -->
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

<!-- Clean exit, clear traceback, no hanging, no Ctrl+C needed. The program terminates immediately with the actual error. Notice "WILL NOT HANG" in the output — the await never was properly cancelled by the level-triggered cancellation. -->

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

<!-- This isn't a contrived example. If you're using WebSockets over TLS, the TLS shutdown in __aexit__ involves awaiting I/O. With edge cancellation, that await succeeds even though you're in a cancelled state, so your timeout becomes meaningless. Your 10-second timeout could hang forever. -->

---

# Shielding from Cancellation

## When you *can't* cancel — even if you want to

Some I/O operations are **uncancellable by nature**, or you must wait for the
cancel to be processed by the OS:

- Waiting for a thread to finish (`loop.run_in_executor`, `anyio.to_thread.run_sync`)
- On Windows IOCP (Proactor)
    - To cancel pending I/O operations in an IOCP (I/O Completion Port) server, use `CancelIoEx` to target specific operations, or `closesocket(handle)`
    to cancel all pending I/O on a socket. Canceled operations complete with `ERROR_OPERATION_ABORTED`, and you must wait for the completion packet before freeing memory.

<!-- Sometimes you genuinely can't cancel work. Threads can't be interrupted, and on Windows IOCP you have to wait for the OS to acknowledge the cancellation before you can free memory. This is where shielding comes in — you need to protect certain operations from cancellation. But as we'll see, asyncio's approach to this is fundamentally broken. -->

---

The async framework can raise `CancelledError` in your coroutine, but the **underlying thread keeps running** or **something still needs to wait to be able to clear memory**

You're not cancelling the work — you're just *abandoning* the future that was watching it. 👻

<!-- This is a key insight. When you cancel an executor task in asyncio, the thread keeps running. You've just abandoned the Future. The work is still happening, you just stopped paying attention to it. It's like hanging up the phone on someone mid-sentence — they're still talking. -->

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

<!-- Here's a concrete Windows example. If you cancel during write_buffer_to_socket and immediately clear the buffer, the OS might still be DMA-ing from that buffer. You'd send undefined bytes over the network. You MUST wait for the cancellation to complete before freeing resources. -->

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

<!-- asyncio.shield is the standard answer to "how do I protect work from cancellation." But it's duct tape. It wraps a single await, creates an orphaned task, and because of edge cancellation, behaviour after the shield is unpredictable. -->

---

### Problems

❌ **Edge-triggered**: a `CancelledError` sneaks through on the *next* checkpoint after the shield exits  
❌ **Orphaned inner task**: the shielded work keeps running with no owner  
❌ **No scope**: shield applies to one `await`, not a logical block of work  
❌ **Thread can't be shielded**: `run_in_executor` inside a shield still abandons the thread

<!-- Four problems, all stemming from asyncio.shield being a point fix rather than a structural solution. It only shields one await, it orphans the inner task, edge cancellation makes subsequent behaviour unpredictable, and it can't protect threads at all. -->

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

<!-- AnyIO's approach is fundamentally different. CancelScope with shield=True protects an entire block, not just one await. The thread runs to completion. Pending cancellation is deferred and reliably re-raised when you exit the shield. And it composes correctly with task groups and timeouts. -->

---

### Why it works

✅ **Level-triggered**: cancellation is *deferred*, not lost — re-fires when you leave the scope  
✅ **Thread-aware**: `run_sync` joins the thread; the shield keeps the join alive  
✅ **Scoped**: protect a whole logical block, not just one `await`  
✅ **No orphans**: structured concurrency means every task has an owner

<!-- Level-triggered, thread-aware, scoped, no orphans. Every problem with asyncio.shield is solved. This is what structured concurrency gives you — the ability to compose these patterns safely. -->

---

# Shielding in Detail

---

## asyncio.shield
![asyncio.shield()](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/65582c063d39717daf957ac203f7bdc54efd841a/asyncio_shield.svg)

<!-- In this diagram you can see the orphaned inner task running off on its own — same problem as create_task. The shield just wraps a single point, and after it exits, you're back to unstructured territory. -->

---
## CancelScope(shield=True)
![CancelScope(shield=True)](https://raw.githubusercontent.com/gist/graingert/cd70c6233d03f5c84c9c8d84a25795d0/raw/65582c063d39717daf957ac203f7bdc54efd841a/anyio_shield.svg)

<!-- Compare: the AnyIO shield wraps the entire scope. Everything inside is protected. The cancellation is held at the boundary and re-raised cleanly when you exit. Structured and predictable. -->

---

## Comparison

| | `asyncio.shield` | `anyio.CancelScope(shield=True)` |
|---|---|---|
| Cancellation model | Edge (one-shot) | Level (persistent, deferred) |
| Scope | Single `await` | Entire `with` block |
| Thread safety | ❌ Abandons thread | ✅ Joins thread to completion |
| Cancellation after exit | ⚠️ Maybe (edge, unreliable) | ✅ Always re-raised |
| Orphaned tasks | ❌ Yes | ✅ Never |
| Composable | ❌ Not really | ✅ Nests with task groups |

<!-- Here's the full comparison side by side. Every row is a win for AnyIO's approach. The key insight is that shielding should be a scope, not a wrapper around a single expression. -->

------------------------------------------------------------------------

# More AnyIO Features

<!-- OK, we've covered the big conceptual stuff — structured concurrency and level-triggered cancellation. Now let me show you some of my favourite practical features that AnyIO gives you. -->

---

# Backpressure by Default. Structured. Composable.

* AnyIO provides `MemoryObjectSendStream` and `MemoryObjectReceiveStream`
* like `asyncio.Queue` but you don't need to keep a count of how many producer/consumers you have
  * you just make a clone for each producer/consumer
  * use a `with` or `async with` to close the clones.
  * Once all the clones of one end of the memory object stream are closed
  iterating the other end will raise StopAsyncIteration.

<!-- Memory object streams are like asyncio.Queue but designed right. The killer feature is clone() — each producer and consumer gets their own clone, and when all clones of one end are closed, the other end gets a clean StopAsyncIteration. No sentinel values, no manual counting, no shutdown coordination. -->

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

<!-- Look how clean this is. Two WebSocket consumers, each with a clone of the send stream, feeding into a single receive stream. When both producers finish, their clones close, the original tx is already closed, so the async for loop on rx terminates naturally. Fully structured shutdown with zero boilerplate. Default buffer size is 0, so you get automatic backpressure — if the consumer is slow, the producers wait. -->

---

### Key properties

-   ✅ **Buffer size defaults to 0** → automatic backpressure

-   ✅ `async for` works naturally

-   ✅ `aclose()` signals end-of-stream

-   ✅ `clone()` enables multiple consumers safely

-   ✅ Structured shutdown

<!-- These five properties are exactly what you want from an inter-task communication channel. And you get them all for free just by using memory object streams instead of asyncio.Queue. -->

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

<!-- Here's the equivalent with asyncio.Queue. Notice the problems right away: unbounded by default, no async iteration, and most importantly — how do you signal completion? There's no built-in mechanism. You end up using sentinel values or manual counters or some other ad-hoc shutdown protocol. -->

---

### Problems

-   ❌ Unbounded by default (no backpressure)

-   ❌ No async iteration

-   ❌ No built-in structured close (historically)

-   ❌ No clone() so requires sentinel values or custom shutdown logic

<!-- Every one of these is a footgun. Unbounded means memory can grow without limit if consumers are slow. No async iteration means you write while True loops. No structured close means you invent your own shutdown protocol. No cloning means fan-out requires manual coordination. -->

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

<!-- Python 3.13 added Queue.shutdown which is a step forward, but it's only on the latest Python, it doesn't have cloning, and it doesn't compose with structured concurrency. AnyIO gives you all of this on Python 3.9+. -->

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

<!-- The comparison table tells the story. AnyIO streams were designed with structured concurrency in mind from the start. asyncio.Queue predates structured concurrency and it shows. -->

------------------------------------------------------------------------
# "If I'm already using Trio, I don't need AnyIO."

Most people assume this. But AnyIO adds real value even on the Trio backend.

### What AnyIO adds on top of Trio

-   ✅ Backend portability (asyncio, Trio)

-   ✅ A stable public API for libraries

-   ✅ High-level stream utilities

-   ✅ Memory object streams

-   ✅ Buffered byte streams

-   ✅ Stapled streams

-   ✅ Thread/subprocess helpers

<!-- A common pushback I get: "I already use Trio, why do I need AnyIO?" AnyIO actually adds real value even if you only use Trio. It provides higher-level abstractions that Trio intentionally doesn't include — buffered streams, memory object streams, stapled streams, and more. Trio is deliberately minimal; AnyIO is batteries-included. -->

------------------------------------------------------------------------

# Trio vs AnyIO

- Trio is a minimal framework — only gives you what is mandatory of a network framework
- AnyIO is a portability + abstraction layer with batteries included.

If you write a library directly against Trio:

-   You lock out asyncio users.

If you write against AnyIO:

-   Trio users still get full Trio semantics.

-   asyncio users can incrementally adopt
    level cancellation or structured concurrency.

-   You get a bunch of cool extra tools

<!-- If you write against Trio directly, you lock out asyncio users. If you write against AnyIO, everyone benefits. Trio users get full Trio semantics, asyncio users can incrementally adopt structured concurrency, and everyone gets the extra tools. It's strictly additive. -->

------------------------------------------------------------------------

# Buffered Byte Streams (AnyIO Feature Trio Lacks)

Trio provides `SendStream` / `ReceiveStream`.

But it does **not** provide:

-   Buffered reads

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Automatic read buffering

AnyIO does.

<!-- This is one of my favourite examples of AnyIO adding value over Trio. Trio gives you raw byte streams, but if you need line-by-line reading or fixed-size reads, you're on your own. AnyIO's BufferedByteReceiveStream handles all the annoying buffering logic for you. -->

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

### Output + What Just Happened

<!-- Here's a quick demo. The producer sends both lines in a single chunk. The consumer uses receive_until to split by newline delimiter. No manual buffer management, no partial read handling. It just works. -->

```sh
$ python demo_buffered_bytes.py
line1: b'hello'
line2: b'world'
```

-   The producer sent both lines in one chunk.
-   The consumer parsed them cleanly by delimiter.
-   No manual buffering. No partial read bookkeeping.

<!-- Clean, predictable output. The buffered stream handled all the complexity of parsing delimited data from arbitrary chunk boundaries. This is the kind of ergonomic improvement that saves you from writing buggy buffer management code. -->

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

<!-- With raw Trio, you have to do all of this yourself. Accumulate into a buffer, scan for delimiters, slice, handle partial frames, handle EOF. It's not rocket science, but it's tedious and easy to get wrong. Speaking of getting it wrong... -->

---
Example (simplified):

I asked ChatGPT and it gave me this — can you spot the bug?

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

<!-- I asked ChatGPT to write this and it produced a bug. Can anyone spot it? I'll give you a moment... -->

---

## Quadratic performance in the inner loop

Every iteration of `while b"\n" in buffer` does `buffer = bytearray(rest)`,
copying the remaining data each time. If you receive a chunk with many
newlines, this is O(n²) in the number of bytes.

<!-- It's quadratic! Every iteration copies the remaining buffer into a new bytearray. If you get a large chunk with many newlines, you're doing O(n²) work. This is exactly the kind of subtle performance bug that BufferedByteReceiveStream handles correctly for you with efficient internal buffering. -->

---

# What AnyIO Adds Here

`BufferedByteReceiveStream` gives you:

-   `receive_exactly(n)`

-   `receive_until(delimiter)`

-   Proper EOF semantics

-   Efficient internal buffering

-   Works on both Trio and asyncio backends

This is a real ergonomic upgrade.

<!-- receive_exactly, receive_until, proper EOF, efficient buffering, and it works on both backends. This is a real ergonomic upgrade that saves you from writing and debugging buffer management code. -->

---
- Trio gives you safety.
- AnyIO gives you safety **plus portability and batteries included.**

<!-- To summarise the Trio vs AnyIO argument: Trio gives you safety. AnyIO gives you that same safety, plus portability across backends, plus all these extra batteries. There's no downside. -->

---

citation:

-   https://github.com/python-trio/trio/issues/796
-   https://github.com/groove-x/trio-util/issues/22
-   https://github.com/python-trio/trio/issues/562

<!-- These are the Trio issues where the buffered streams features were discussed and ultimately not added to Trio itself, which is part of why AnyIO fills this gap. -->

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

<!-- Here's another practical feature. pathlib is great, but every operation blocks the event loop. In an async application, calling path.read_text() blocks the entire loop while waiting for disk I/O. This defeats the whole point of async. -->

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

<!-- anyio.Path is a drop-in async replacement for pathlib. Same API, but every operation is awaitable and runs in a thread pool so it doesn't block the event loop. Minimal code changes, maximum benefit. -->

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

<!-- And because it's async, you can combine it with task groups for parallel file I/O. Process all CSVs in a directory concurrently, with structured concurrency ensuring everything completes before you continue. -->

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

<!-- The comparison table makes it clear — anyio.Path gives you everything pathlib does but without blocking the event loop. It's a genuine drop-in replacement. -->

------------------------------------------------------------------------

# pytest plugin

* AnyIO ships with a pytest plugin that it uses to test itself.
* This means if you already depend on AnyIO you don't need pytest-asyncio as well.

```python
@pytest.mark.anyio
async def test_something():
    assert await something() == "result"
```

<!-- AnyIO ships with its own pytest plugin, the same one it uses to test itself. If you already depend on AnyIO, you don't need to install pytest-asyncio separately. Just mark your tests with @pytest.mark.anyio and you're done. -->

---
By default the plugin runs your tests under both asyncio and Trio, so if you're still gradually migrating to AnyIO and still require asyncio support, you can run your tests in asyncio mode only by adding the following to your root `conftest.py`

```python
@pytest.fixture
def anyio_backend():
    return 'asyncio'
```

<!-- By default, the plugin runs your tests on both asyncio and Trio, which is great for catching backend-specific bugs. If you're still migrating and only need asyncio, just add this fixture to your conftest. -->
---

# But `await` there's more! — Networking & I/O

| Feature | Benefit |
|---|---|
| **TCP/UDP/UNIX sockets** | Happy Eyeballs built in; async/await UDP (no Transports/Protocols) |
| **TLS streams** | `TLSStream` wraps any byte stream with TLS, not just sockets |
| **Subprocesses** | `run_process()` / `open_process()` with async stream I/O on stdin/stdout/stderr |
| **Signal handling** | `open_signal_receiver()` — async iterator over OS signals |

<!-- But await, there's more! AnyIO has a full networking stack. TCP, UDP, Unix sockets with Happy Eyeballs built in. TLS that wraps any byte stream, not just sockets. Subprocesses with async stream I/O. And signal handling as an async iterator. -->

---

# But `await` there's more! — Streams & Concurrency

| Feature | Benefit |
|---|---|
| **`TextReceiveStream`** | Incremental UTF-8 decoding over any byte stream |
| **`StapledStream`** | Combine separate send/receive streams into one bidirectional stream |
| **`tg.start()`** | `await tg.start(server_fn)` — blocks until the task signals it's ready |
| **Synchronization primitives** | `Lock`, `Condition`, `Event`, `Semaphore`, `CapacityLimiter` — portable across backends |

<!-- More batteries: TextReceiveStream for incremental UTF-8 decoding, StapledStream for combining send and receive streams, tg.start() which blocks until a task signals it's ready — great for server startup — and all the synchronization primitives you'd expect, portable across backends. -->

---

# But `await` there's more! — Threads, Testing & Beyond

| Feature | Benefit |
|---|---|
| **`to_thread` / `from_thread`** | Bidirectional sync↔async bridging with structured cancellation |
| **Subinterpreters** | `to_interpreters` module for true parallelism (Python 3.13+) |
| **Async `functools`** | `anyio.functools.lru_cache` for async functions |

<!-- And even more: bidirectional sync/async bridging with structured cancellation, subinterpreter support for true parallelism on Python 3.13+, and async functools like lru_cache. AnyIO keeps growing. -->

---

# The Advantage of Being on PyPI

In Python 3.13, a number of bug-fixes were applied to asyncio.TaskGroup
but they were considered breaking changes so were not backported to 3.11
or 3.12:

https://docs.python.org/3/whatsnew/3.13.html#asyncio

<!-- Here's a practical advantage of AnyIO being a pip-installable package rather than part of the standard library. In Python 3.13, important TaskGroup bugfixes landed — like fixing deadlocks when nested task groups both have failing children. But these were considered breaking changes and weren't backported to 3.11 or 3.12. -->

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

<!-- With asyncio, you need to upgrade your entire Python version to get bugfixes. With AnyIO, you just pip install the latest version and get fixes on every supported Python. AnyIO even still supports Python 3.9, which is past end-of-life. That's the power of being on PyPI. -->

---

# Asyncio is not bad

* it's better than Twisted (I once spent a week fixing a missing `six` call
  — a whole class of bug that doesn't exist with asyncio)
* but try making an LDAP server without Twisted!
* *some* of the mistakes Twisted made were copied into asyncio
* Curio is good! Unfortunately it's archived
* Trio isn't perfect: it's slower than asyncio, especially with uvloop
* AnyIO gives you options and batteries to play with

<!-- I want to be fair here: asyncio is not bad. It's a huge improvement over Twisted — I once spent a week debugging a missing six call, a whole class of bug that doesn't exist with asyncio. Curio was great but it's archived. Trio is excellent but slower than asyncio. AnyIO lets you use the best of all worlds. -->

------------------------------------------------------------------------

Normally at this stage of my talk I'd ask you to go run

# ~~pip install anyio~~

but if you're in this room you probably already have it in your virtual
environments!

<!-- Normally I'd tell you to go pip install anyio, but that's the punchline of this talk — you probably already have it! If you've installed httpx, FastAPI, Jupyter, MCP, or any number of other popular packages, AnyIO is already in your virtualenv. -->

---

```sh
$ pip install httpx fastapi jupyter mcp pipdeptree
$ pipdeptree -p anyio -r  # reverse dependencies (dependants) of anyio
```

Watch the tree unfold: loads of packages you use daily depend on AnyIO

<!-- Try this yourself. Install a few common packages and run pipdeptree in reverse mode for anyio. You'll see a massive dependency tree. AnyIO is everywhere. -->

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

<!-- Look at this tree! starlette, FastAPI, MCP, httpx, Jupyter — they all depend on AnyIO. If you're using any modern Python web framework or data science tool, you already have AnyIO installed. You might as well start using it directly and get all the benefits we've talked about today. -->

------------------------------------------------------------------------

* I've given you a whistle-stop tour of some of my favourite features, there's loads more
   * and more being added all the time
* I hope I've persuaded you to give AnyIO a try
* you might as well give it a go if you already have it installed

<!-- To wrap up: AnyIO gives you structured concurrency, level-triggered cancellation, great batteries, and it works everywhere. You've probably already got it installed. So give it a try — you've got nothing to lose and a lot of headaches to avoid. -->
---

# Any questions?

<!-- Thank you! I'm happy to take questions. If you want to chat more, find me online at graingert.co.uk or on GitHub as graingert. -->
