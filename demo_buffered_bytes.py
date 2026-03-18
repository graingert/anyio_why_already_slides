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
