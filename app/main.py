from fastapi import FastAPI
from .routers import processing  # Import your processing module

app = FastAPI()

# Include the router from the processing module
app.include_router(processing.router)

@app.get("/")
async def read_root():
    return {"message": "Welcome to Menome Processor API!"}
