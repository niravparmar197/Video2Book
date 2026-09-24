from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.checkpointer import ensure_checkpoint_tables
from api.error_tracking import capture_exception_with_context, init_error_tracking
from api.logging import configure_logging, get_logger
from api.routers.books import router as books_router
from api.routers.health import router as health_router
from api.routers.outline import router as outline_router
from api.routers.users import router as users_router

configure_logging()
init_error_tracking()
ensure_checkpoint_tables()

app = FastAPI(title="Video2Book API")
app.include_router(books_router)
app.include_router(health_router)
app.include_router(outline_router)
app.include_router(users_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catches anything a route/dependency raises that isn't an
    HTTPException (which FastAPI's own, more specific handler already
    covers) -- logs it, reports it to Sentry if configured, and still
    returns a normal 500 instead of leaking a traceback to the client."""
    logger = get_logger(step="unhandled_exception")
    logger.error("unhandled exception", extra={"path": request.url.path, "error": str(exc)})
    capture_exception_with_context(exc, path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/")
def root() -> dict:
    return {"service": "video2book-backend"}
