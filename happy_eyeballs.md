---
marp: true
html: true
---

# Happy Eyeballs
### Structured Concurrency vs Callbacks

⚡ Thomas Grainger · graingert

<!-- Happy Eyeballs is a great case study in how structured concurrency simplifies a genuinely tricky algorithm. -->

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

<!-- I'm Thomas Grainger, graingert on GitHub. Core dev of AnyIO, Twisted, and Trio — which puts me in a good position to compare them. -->

---

# What is Happy Eyeballs? (RFC 6555)

`example.com` resolves to both IPv6 **and** IPv4 — which do you use?

- IPv6 is preferred — but what if the IPv6 path is broken or slow?
- Waiting for a 75-second TCP timeout is not an option

**The solution: race them**

1. Try IPv6 first
2. After **250ms**, try IPv4 in parallel
3. Use whichever connects first — cancel the rest

*Your browser does this. Chrome, Firefox, curl all implement it. So do AnyIO and Twisted.*

<!-- RFC 6555 was published in 2012. Twisted implemented it in 2013. AnyIO has it built into connect_tcp. The interesting part is HOW they implement it. -->

---

# Twisted (2013): Callbacks

```python
pending: list[Deferred] = []
failures: list[Failure] = []
checkDoneCompleted = False
checkDoneEndpointsLeft = True

@LoopingCall
def iterateEndpoint() -> None:
    endpoint = next(iterEndpoints, None)
    if endpoint is None:
        checkDoneEndpointsLeft = False; checkDone(); return
    eachAttempt = endpoint.connect(protocolFactory)
    pending.append(eachAttempt)
    eachAttempt.addBoth(noLongerPending).addCallback(succeeded).addErrback(failed)

iterateEndpoint.start(self._attemptDelay)  # 300ms — fixed interval
return winner.addBoth(cancelRemainingPending)
```

4 pieces of manual state · 5 nested closures · 1 `LoopingCall`

<!-- Twisted was ahead of its time implementing this in 2013. But the callback model forces you to manage all the bookkeeping yourself. Four boolean/list variables just to track whether you're done. -->

---

# AnyIO: Structured Concurrency

```python
async with create_task_group() as tg:
    for _af, addr in target_addrs:
        event = Event()
        tg.start_soon(try_connect, addr, event)
        with move_on_after(happy_eyeballs_delay):
            await event.wait()
```

The task group handles: **cancellation · error propagation · cleanup**

<!-- Five lines. The task group gives you all the bookkeeping for free. No manual pending lists, no boolean flags, no LoopingCall. -->

---

# A subtlety: adaptive vs fixed delay

**Twisted**: `LoopingCall` fires every 300ms regardless of what the previous attempt did

**AnyIO**: starts the next attempt when the previous one finishes *or* 250ms passes — whichever comes first

```python
async def try_connect(remote_host, event):
    try:
        stream = await connect(...)
        ...
    finally:
        event.set()  # fires immediately on success or failure

# main loop: wait up to 250ms, then move on regardless
with move_on_after(happy_eyeballs_delay):
    await event.wait()
```

Attempt 0 fails in 10ms → attempt 1 starts at 10ms, not 250ms

<!-- This is actually more correct per RFC 8305. Fast failures shouldn't penalise the user with a full delay. The Twisted LoopingCall always waits the full interval. -->

---

# Also: Twisted only reports the last failure

```python
# Twisted
def checkDone() -> None:
    if pending or checkDoneCompleted or checkDoneEndpointsLeft:
        return
    winner.errback(failures.pop())  # ← only the last one
```

```python
# AnyIO
cause = (
    oserrors[0] if len(oserrors) == 1
    else ExceptionGroup("multiple connection attempts failed", oserrors)
)
raise OSError("All connection attempts failed") from cause
```

AnyIO gives you *all* the failures.

<!-- This matters for debugging. If IPv6 and IPv4 both fail for different reasons, Twisted only tells you about the last one. AnyIO wraps them all in an ExceptionGroup. -->

---

# Twisted even warns about circular references

```python
def _canceller(cancelled: Deferred[IProtocol]) -> None:
    # This canceller must remain defined outside of
    # `startConnectionAttempts`, because Deferred should not
    # participate in cycles with their cancellers; that would
    # create a potentially problematic circular reference and
    # possibly gc.garbage.
    ...
```

AnyIO's task group handles cancellation — **no closures, no cycles, no comment needed**.

<!-- The Twisted code itself documents the footgun. Structured concurrency eliminates the whole class of problem. -->

---

# Bonus: CPython asyncio had bugs

asyncio also has Happy Eyeballs (`happy_eyeballs_delay` in `asyncio.open_connection`):

- **Reference cycles** — failed-attempt exceptions were trapped by the implementation, preventing GC (Oct 2024)
- **`staggered_race` task leaks** — tasks weren't cancelled on success, plus a `NameError` when logging unhandled errors

I found and fixed both — merged across Python 3.12, 3.13, and `main`.

AnyIO's structured approach avoids this whole class of bug.

<!-- Finding bugs in the implementation you're replacing is a good way to validate that the replacement is better. Both bugs stem from manual bookkeeping that structured concurrency eliminates. -->

---

<style scoped>section { font-size: 22px; }</style>

# Any questions?

**These slides:** [graingert.co.uk/why-anyio-already](https://graingert.co.uk/why-anyio-already)

**Further reading:**
- [anyio.readthedocs.io](https://anyio.readthedocs.io) — AnyIO docs
- [RFC 6555](https://datatracker.ietf.org/doc/html/rfc6555) — Happy Eyeballs
- [RFC 8305](https://datatracker.ietf.org/doc/html/rfc8305) — Happy Eyeballs v2
- [github.com/python/cpython/issues/124858](https://github.com/python/cpython/issues/124858) — asyncio refcycle fix
- [github.com/python/cpython/pull/128475](https://github.com/python/cpython/pull/128475) — staggered_race leak fix

<!-- thanks! happy to take questions. -->
