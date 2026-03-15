---
marp: true
---

# Why You Should Use AnyIO (and Why You Already Have It Installed)

### ⚡ Lightning Talk Edition

<!-- hi everyone, I'm going to give you the speedrun on AnyIO. Why you should use it because you already have it installed -->

---

https://graingert.co.uk/why-anyio-already
![graingert](https://avatars.githubusercontent.com/u/413772)

- Core developer of AnyIO, Twisted, and Trio
- Contributed to asyncio happy eyeballs + TaskGroup fixes

<!-- I'm Thomas Grainger, graingert on GitHub. I work on AnyIO, Twisted, Trio, and asyncio itself. -->

---

# Misconception: `asyncio` == `async`/`await`

- `async`/`await` is **syntactic sugar over generators** — decoupled from asyncio
- Twisted, Trio, Curio all use the same syntax with different event loops
- AnyIO uses `sniffio` to detect which framework is running, dispatches to the right API

<!-- first: async/await is NOT asyncio. it's just generators. multiple frameworks use the same syntax — AnyIO detects which one you're running and does the right thing. like `six` for async frameworks. -->

---

# `asyncio.create_task()` Is the `goto` of Concurrency

```python
asyncio.create_task(myfunc())  # Fire and forget!
# Parent returns immediately, child runs unsupervised
# No guaranteed reunion point
```

**One-way jump** → same problems as `goto`:

- ❌ Functions aren't black boxes — hidden background tasks survive returns
- ❌ Resource cleanup breaks — `async with` can't track orphaned tasks
- ❌ Errors silently drop — no stack to propagate up
- ❌ Return statements lie — "done" doesn't mean done

<!-- create_task is a go statement. it's a one-way jump that breaks functions as black boxes, breaks resource cleanup, silently drops errors, and makes return statements lie. Dijkstra was right again. -->

---

# The Fix: Structured Concurrency with Task Groups

```python
# asyncio — UNSTRUCTURED 😰
async def unstructured():
    asyncio.create_task(myfunc())  # fire and forget
    asyncio.create_task(other())   # errors go nowhere
    return  # are we done? who knows!

# AnyIO — STRUCTURED 😌
async def structured():
    async with anyio.create_task_group() as tg:
        tg.start_soon(myfunc)
        tg.start_soon(other)
    # BLOCKED until ALL tasks finish
    # Errors propagate. Cleanup happens. Actually done.
```

**Task groups = `if`/`while`/`for` of concurrency**

<!-- task groups are the fix. you can't leave the block until all children complete. errors propagate, cleanup happens, and when you return, you're actually done. -->

---

# Level Cancellation vs Edge Cancellation
<table>
<tr>
<th>AnyIO — level-triggered ✅</th>
<th>asyncio — edge-triggered ❌</th>
</tr>
<tr>
<td>

```python
with anyio.fail_after(0):
    try:
        await anyio.sleep(1)
        # raises CancelledError
    finally:
        await anyio.sleep(1000)
        # ALSO raises CancelledError
```

</td>
<td>

```python
async with asyncio.timeout(0):
    try:
        await asyncio.sleep(1)
        # raises CancelledError
    finally:
        await asyncio.sleep(1000)
        # waits 1000 seconds! 😱
```

</td>
</tr>
</table>

Edge cancellation = **your 0s timeout becomes a 1000s timeout**. With level cancellation every `await` in a cancelled scope fails. No surprises.

<!-- this is the other killer feature. asyncio's edge-triggered cancellation is consumed after one catch — your finally block escapes the timeout. AnyIO's level-triggered cancellation persists. your timeouts actually mean something. -->

---

# Shielded Cancel Scopes > `asyncio.shield`

```python
# asyncio.shield — wraps ONE await, orphans process.wait(), edge-triggered 😬
await asyncio.shield(process.wait())
# can't reliably terminate + join: edge cancellation breaks the cleanup

# AnyIO — terminate the process, shield the join, no zombies 😎
process.terminate()
with anyio.CancelScope(shield=True):
    await process.wait()  # reap the process even under cancellation
# Pending cancellation reliably re-raised here
```

<!-- asyncio.shield wraps one await and orphans the task. with subprocesses you need to terminate AND join — but edge cancellation makes the join unreliable. AnyIO CancelScope shields the join, reaps the process, and defers cancellation cleanly. no zombies. -->

---

# Batteries Included

- **Memory object streams** — `asyncio.Queue` but with backpressure, `clone()`, structured shutdown, and `async for`
- **`BufferedByteReceiveStream`** — `receive_until(delimiter)`, `receive_exactly(n)` — even Trio doesn't have this
- **`anyio.Path`** — async drop-in for `pathlib` (no more blocking the event loop)
- **Built-in pytest plugin** — `@pytest.mark.anyio`, no need for `pytest-asyncio`
- **Networking** — TCP/UDP/TLS/subprocesses with Happy Eyeballs built in
- **PyPI-shipped bugfixes** — don't wait for a new Python release to fix TaskGroup

<!-- rapid fire: memory streams with backpressure, buffered byte reads Trio doesn't have, async pathlib, built-in pytest plugin, full networking stack, and bugfixes that ship on PyPI instead of waiting for a CPython release. -->

---

# ~~`pip install anyio`~~

You already have it.

```
anyio==4.12.1
├── starlette → fastapi, mcp
├── httpx → mcp, jupyterlab
├── jupyter_server → notebook, jupyterlab
├── mcp
└── sse-starlette → mcp
```

httpx? FastAPI? Jupyter? MCP? **AnyIO is already in your virtualenv.**

<!-- normally I'd say pip install anyio. but that's the punchline — if you've ever installed httpx, FastAPI, Jupyter, or MCP, you already have it. might as well `await` yourself of it. -->

---

# TL;DR

1. `asyncio.create_task()` is `goto` — use **task groups** instead
2. **Level-triggered cancellation** prevents real bugs that edge cancellation causes
3. **Batteries included** — streams, paths, pytest, networking
4. **You already have it installed** — start using it on purpose

### graingert on GitHub · `graingert.co.uk/why-anyio-already`

<!-- structured concurrency, level cancellation, great batteries, already installed. give it a go — it won't leave you hanging. thanks! -->
