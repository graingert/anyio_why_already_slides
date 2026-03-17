import anyio


async def concurrently_chmod_all_csvs():
    data_dir = anyio.Path("training_data")
    async with anyio.create_task_group() as tg:
        async for path in data_dir.iterdir():
            if await path.is_file() and path.suffix == '.csv':
                tg.start_soon(path.chmod, 0o644)


anyio.run(concurrently_chmod_all_csvs)
# All files processed concurrently!
