import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.rabbitmq import connect_rabbitmq, close_rabbitmq

app = FastAPI(title="event-service")

cors_origins = os.getenv("CORS_ORIGINS", "*")
allow_origins = [o.strip() for o in cors_origins.split(",")] if cors_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False if allow_origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/events")

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "event-service"}

@app.on_event("startup")
async def startup():
    await connect_rabbitmq()

@app.on_event("shutdown")
async def shutdown():
    await close_rabbitmq()
