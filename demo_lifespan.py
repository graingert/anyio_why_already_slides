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


class Done(Exception):
    pass


async def background_job(data: str) -> None:
    print(f"Processing: {data}")
    await anyio.sleep(1)
    print(f"Done: {data}")


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
