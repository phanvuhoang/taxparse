from fastapi.staticfiles import StaticFiles
import os

# Mount frontend static files — add to main.py after app creation
# app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
