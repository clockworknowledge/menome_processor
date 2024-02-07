from fastapi import FastAPI
from .routers import processing  
from .routers import document  
from .routers import chat  

app = FastAPI()

# Include the router from the processing module
app.include_router(processing.router)
app.include_router(document.router)
app.include_router(chat.router)

@app.get("/")
async def read_root():
    return {"message": "Welcome to Menome Processor API!"}
