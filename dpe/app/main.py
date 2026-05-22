from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(title="DPE", version="0.1.0", description="Document Processing Engine")
app.include_router(router)
