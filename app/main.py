import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import evaluate, questions, tutor, stats, profile, webhooks, legal
from .core.rate_limit import RateLimitMiddleware

app = FastAPI(title="Edge API", version="1.0.0")

ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")

# Rate limiting — added before CORS so it runs on every request
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(evaluate.router)
app.include_router(questions.router)
app.include_router(tutor.router)
app.include_router(stats.router)
app.include_router(profile.router)
app.include_router(webhooks.router)
app.include_router(legal.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
