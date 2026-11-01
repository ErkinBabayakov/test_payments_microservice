from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.payments import router as payments_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Payment Service", lifespan=lifespan)
app.include_router(payments_router)


@app.get("/", response_class=HTMLResponse, tags=["Главная страница документации"])
def home():
    return """
    <h1>Выберите тип документации</h1>
    <h2><a href="/docs">Swagger UI</a><br></h2>
    <h2><a href="/redoc">ReDoc</a></h2>
    """


if __name__ == "__main__":
    uvicorn.run("app.main:app", reload=True, host="0.0.0.0", port=8000)