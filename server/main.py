"""Vellum API entry point."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.inspiration import router as inspiration_router
from .services.model_gateway import ModelGateway, ModelGatewayError

app = FastAPI(
    title="云笺 Vellum API",
    description="将模糊的视觉想法整理成可确认的意图草稿，并转译为文生图 Prompt。",
    version="2.0.0",
)

origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inspiration_router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health():
    try:
        config = ModelGateway().config()
    except ModelGatewayError as exc:
        return {"status": "misconfigured", "error": str(exc)}
    return {"status": "ok", **config}


@app.get("/", include_in_schema=False)
def root():
    return {"product": "云笺 Vellum", "version": "2.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "3001")),
        reload=os.getenv("RELOAD", "true").lower() == "true",
    )
