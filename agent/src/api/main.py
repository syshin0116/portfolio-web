"""FastAPI application entry point — LangGraph Platform-compatible API."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from agent.graph import create_graph
from api.logging_config import setup_logging
from api.middleware import RequestLoggingMiddleware
from api.routes.assistants import router as assistants_router
from api.routes.crons import router as crons_router
from api.routes.models import router as models_router
from api.routes.runs import router as runs_router
from api.routes.store import router as store_router
from api.routes.threads import router as threads_router
from api.run_manager import RunManager
from api.run_manager_base import RunManagerBase
from db import DB

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/postgres"
    )

    async with AsyncConnectionPool(
        conninfo=database_url,
        max_size=20,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()

        db = DB(pool)
        await db.setup()

        compiled_graphs = {
            "agent": create_graph(checkpointer=checkpointer),
        }

        redis_url = os.environ.get("REDIS_URL")
        run_manager: RunManagerBase
        if redis_url:
            from api.arq_run_manager import ArqRunManager

            arq_manager = ArqRunManager(db, checkpointer, compiled_graphs, redis_url)
            await arq_manager.setup()
            run_manager = arq_manager
            logger.info("Using ArqRunManager (Redis: %s)", redis_url)
        else:
            run_manager = RunManager(db, checkpointer, compiled_graphs)
            logger.info("Using asyncio RunManager (no Redis)")

        app.state.checkpointer = checkpointer
        app.state.db = db
        app.state.graphs = compiled_graphs
        app.state.run_manager = run_manager

        logger.info("Application started — graphs: %s", list(compiled_graphs))
        yield

        if redis_url and hasattr(run_manager, "close"):
            await run_manager.close()
        logger.info("Application shutting down")


app = FastAPI(title="LangGraph Agent API", lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/ok")
async def ok():
    """Health check — matches LangGraph Platform convention."""
    return {"ok": True}


@app.get("/info")
async def info():
    return {"version": "0.1.0", "graphs": ["agent"]}


app.include_router(assistants_router)
app.include_router(threads_router)
app.include_router(runs_router)
app.include_router(store_router)
app.include_router(crons_router)
app.include_router(models_router)
