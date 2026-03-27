import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes_analysis import router as analysis_router
from backend.api.routes_export import router as export_router
from backend.api.routes_parcels import router as parcels_router
from backend.api.routes_utilities import router as utilities_router

_is_prod = os.environ.get("ENVIRONMENT", "dev") == "production"

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    ).split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Durham Subdividable Lots API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Content-Type"],
)

app.include_router(parcels_router)
app.include_router(analysis_router)
app.include_router(export_router)
app.include_router(utilities_router)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/")
async def root():
    return {"status": "ok", "name": "Durham Subdividable Lots API"}
