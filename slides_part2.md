---
marp: true
html: true
---
# Why you should use AnyIO — Part 2 of 3

### Level-Triggered Cancellation and Shielding

https://graingert.co.uk/why-anyio-already

<!-- Part 2 of 3 -->

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

# Part 2 Contents

* `asyncio` != `async`/`await` — the most important take-away (generators all the way down)
* Two most important reasons to use AnyIO
* Level-triggered cancellation (AnyIO ✅) vs edge-triggered (asyncio ❌)
* Deadlocks in asyncio — demo with output and Ctrl+C
* The same example with AnyIO — output comparison
* Edge cancellation with WebSockets over TLS
* Shielding from cancellation
  * Cancellation abandons the work, not the task
  * Example: Windows IOCP buffer safety
  * `asyncio.shield` — the duct-tape approach and its problems
  * AnyIO shielded cancel scopes — the structured approach
  * Why it works + diagram + comparison table
  * Mixing native asyncio cancellation (gotcha!)
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

---

<style scoped>section { padding-top: 10px; }</style>

# Shielding in Detail: asyncio.shield
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 660 310" font-family="'JetBrains Mono','Fira Code','Cascadia Code',ui-monospace,monospace" width="650" style="display: block; margin: 0 auto;">
  <defs>
    <marker id="asyncio-shield-arr-red" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3z" fill="#d20f39"/></marker>
    <marker id="asyncio-shield-arr-blue" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3z" fill="#1e66f5"/></marker>
    <marker id="asyncio-shield-arr-muted" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3z" fill="#9ca0b0"/></marker>
  </defs>
  <!-- background -->
  <rect width="660" height="310" fill="#eff1f5" rx="12"/>
  <!-- title -->
  <text x="330" y="26" text-anchor="middle" font-size="13" font-weight="bold" fill="#d20f39">asyncio.shield — what happens under cancellation</text>
  <line x1="16" y1="34" x2="644" y2="34" stroke="#d20f39" stroke-width="1" opacity="0.35"/>
  <!-- column headers -->
  <text x="160" y="54" text-anchor="middle" font-size="11" fill="#6c6f85">what your code sees</text>
  <text x="490" y="54" text-anchor="middle" font-size="11" fill="#6c6f85">what happens inside shield()</text>
  <!-- divider -->
  <line x1="330" y1="44" x2="330" y2="290" stroke="#8c8fa1" stroke-width="1" stroke-dasharray="4,3"/>
  <text x="330" y="174" text-anchor="middle" font-size="18" fill="#8c8fa1" transform="rotate(-90,330,174)">one-way barrier</text>
  <!-- === LEFT SIDE === -->
  <!-- your code box -->
  <rect x="30" y="66" width="140" height="44" rx="5" fill="#dce0e8" stroke="#1e66f5" stroke-width="1.5"/>
  <text x="100" y="84" text-anchor="middle" font-size="11" fill="#6c6f85">your code</text>
  <text x="100" y="101" text-anchor="middle" font-size="12" font-weight="bold" fill="#1e66f5">await shield(f)</text>
  <!-- down arrow -->
  <line x1="100" y1="110" x2="100" y2="138" stroke="#d20f39" stroke-width="1.5" marker-end="url(#asyncio-shield-arr-red)"/>
  <text x="112" y="130" font-size="10" fill="#d20f39">cancel</text>
  <!-- CancelledError box -->
  <rect x="20" y="140" width="220" height="44" rx="5" fill="#ffd7cf" stroke="#d20f39" stroke-width="2"/>
  <text x="130" y="158" text-anchor="middle" font-size="11" fill="#6c6f85">outer Future cancelled</text>
  <text x="130" y="176" text-anchor="middle" font-size="13" font-weight="bold" fill="#d20f39">⚡ CancelledError</text>
  <!-- edge note -->
  <text x="130" y="208" text-anchor="middle" font-size="10" fill="#6c6f85">edge-triggered: cancel "used up" here</text>
  <text x="130" y="222" text-anchor="middle" font-size="10" fill="#6c6f85">next await may succeed ⚠</text>
  <!-- === RIGHT SIDE === -->
  <!-- inner Task box -->
  <rect x="350" y="66" width="270" height="44" rx="5" fill="#fff0d4" stroke="#fe640b" stroke-width="1.5" stroke-dasharray="6,3"/>
  <text x="485" y="84" text-anchor="middle" font-size="11" fill="#6c6f85">inner Task  👻</text>
  <text x="485" y="101" text-anchor="middle" font-size="12" fill="#fe640b">cancel NOT forwarded</text>
  <!-- down arrow -->
  <line x1="485" y1="110" x2="485" y2="138" stroke="#9ca0b0" stroke-width="1.5" marker-end="url(#asyncio-shield-arr-muted)"/>
  <text x="497" y="130" font-size="10" fill="#6c6f85">runs on...</text>
  <!-- result lost box -->
  <rect x="360" y="140" width="250" height="44" rx="5" fill="#eff1f5" stroke="#d20f39" stroke-width="1.5"/>
  <text x="485" y="158" text-anchor="middle" font-size="11" fill="#6c6f85">completes eventually</text>
  <text x="485" y="176" text-anchor="middle" font-size="13" font-weight="bold" fill="#d20f39">result → void ❌</text>
  <!-- orphan note -->
  <text x="485" y="208" text-anchor="middle" font-size="10" fill="#6c6f85">no owner, no supervision</text>
  <text x="485" y="222" text-anchor="middle" font-size="10" fill="#6c6f85">resource cleanup may never run</text>
  <!-- bottom summary -->
  <rect x="16" y="248" width="628" height="48" rx="6" fill="#e6e9ef" stroke="#8c8fa1" stroke-width="1"/>
  <text x="330" y="266" text-anchor="middle" font-size="11" fill="#d20f39" font-weight="bold">cancel flows in (to outer Future) but not through (to inner Task)</text>
  <text x="330" y="285" text-anchor="middle" font-size="10" fill="#6c6f85">Use CancelScope(shield=True) instead — it defers cancellation and keeps the task owned</text>
</svg>

**What's happening:** `shield()` wraps the outer Future around an inner Task. When the outer cancel arrives, the outer Future is cancelled immediately (edge-triggered ⚡). The inner Task is orphaned — it keeps running with no owner. The result is silently discarded.

<!-- in this diagram you can see the orphaned inner task running off on its own - same problem as create_task. shield wraps a single point, and after it exits you're back to unstructured territory. -->

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
