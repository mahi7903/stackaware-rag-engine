# Main entry point for the FastAPI backend.
# I start with a small health endpoint and gradually add real features
# like authentication and RAG APIs as the project evolves.

from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session

import logging #to get the logs for the api guards file 
from app.database.db import get_db
from app.models.user import User
from app.schemas.schemas import UserRegister, UserResponse
from app.auth.security import hash_password
from app.routers.users import router as users_router

from app.routers import stack #slug
from app.routers import stack_tools #for endpoints like id, query history , and document upload
from app.routers import admin_documents #for admin documents route
from app.routers import rag_modes #for 2 different modes


app = FastAPI(title="StackAware RAG Engine")

#to show the clearer logs of files in the terminal 
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s: %(message)s",
)

logging.getLogger("stackaware.api").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

app.include_router(users_router, prefix="/auth", tags=["auth"]) #route for the user.py file
app.include_router(stack.router, prefix="/stack", tags=["stack"]) #route for the item slugs 
app.include_router(stack_tools.router, prefix="/stack") #stack management tools 
app.include_router(admin_documents.router) #expose admin document management endpoints separately
app.include_router(rag_modes.router) #different mode options 


@app.get("/health")
def health():
    return {"status": "ok"}


