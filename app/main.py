"""
Store Intelligence API — FastAPI entrypoint.
Starts all routers, sets up DB on startup, configures structured logging.
"""
import time
import uuid
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db.database import engine, Base
from routers import events, metrics, funnel, heatmap, anomalies, health

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Lifespan: create tables on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_ready", message="Tables created / verified")
    yield
    logger.info("shutdown", message="API shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Apex Retail — Store Intelligence API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    store_id = request.path_params.get("store_id", "N/A")
    start = time.perf_counter()

    request.state.trace_id = trace_id

    try:
        response: Response = await call_next(request)
    except Exception as exc:
        logger.error(
            "unhandled_exception",
            trace_id=trace_id,
            path=request.url.path,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "trace_id": trace_id},
        )

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        trace_id=trace_id,
        store_id=store_id,
        endpoint=request.url.path,
        method=request.method,
        status_code=response.status_code,
        latency_ms=latency_ms,
    )
    response.headers["X-Trace-Id"] = trace_id
    return response


# ---------------------------------------------------------------------------
# Exception handlers — no raw stack traces in responses
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    logger.error("exception", trace_id=trace_id, error=str(exc), path=str(request.url))
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "trace_id": trace_id},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(events.router, prefix="/events", tags=["Events"])
app.include_router(metrics.router, prefix="/stores", tags=["Metrics"])
app.include_router(funnel.router, prefix="/stores", tags=["Funnel"])
app.include_router(heatmap.router, prefix="/stores", tags=["Heatmap"])
app.include_router(anomalies.router, prefix="/stores", tags=["Anomalies"])
app.include_router(health.router, tags=["Health"])
