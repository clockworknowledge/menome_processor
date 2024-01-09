from fastapi import APIRouter, Query, Depends
from fastapi import Depends, HTTPException, status, APIRouter
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from models import User,UserIn  # Import your User model
from neo4j import GraphDatabase  # Import Neo4j driver
import logging
from datetime import datetime,  timedelta

from worker.tasks import process_text_task, get_task_info, purge_celery_queue

from config import AppConfig

from config import AppConfig
from dotenv import load_dotenv

# Assuming your .env file is in /code/config/.env inside the container
dotenv_path = '/code/config/.env'
load_dotenv(dotenv_path)

# Initialize environment variables if needed
AppConfig.initialize_environment_variables()

# Initialize environment variables if needed
AppConfig.initialize_environment_variables()

class Token(BaseModel):
    access_token: str
    token_type: str

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Verify hashed password
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Create an access token
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, AppConfig.SECRET_KEY, algorithm=AppConfig.ALGORITHM)
    return encoded_jwt

# Authenticate a user (This function might need the get_user_from_db function, which should be imported from user_management.py)
def authenticate_user(username: str, password: str):
    user = get_user_from_db(username)
    if user and verify_password(password, user.password):
        return user
    return None

# Helper function to convert Neo4j datetime to Python datetime
def neo4j_datetime_to_python_datetime(neo4j_dt_str: str) -> datetime:
    truncated_str = neo4j_dt_str[:26] + neo4j_dt_str[29:]
    return datetime.fromisoformat(truncated_str)

# Get user from database
def get_user_from_db(username: str):
    with driver.session() as session:
        result = session.run("MATCH (u:User {username: $username}) RETURN u", username=username)
        user_data = result.single()
        if user_data:
            date_created_str = str(user_data['u']['datecreated'])
            date_created = neo4j_datetime_to_python_datetime(date_created_str)
            return UserIn(
                username=user_data['u']['username'], 
                password=user_data['u']['password'], 
                uuid=user_data['u']['uuid'], 
                email=user_data['u']['email'], 
                name=user_data['u']['name'], 
                disabled=user_data['u']['disabled'],
                datecreated=date_created
            )
    return None


# Define the dependency function to get the current user
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, AppConfig.SECRET_KEY, algorithms=[AppConfig.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        # Here you should get the user from your Neo4j database using the username
        # and convert it to the UserInDB model.  
        user = get_user_from_db(username)
        if user is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return user


router = APIRouter()

# Assuming you have a Neo4j driver instance
driver = GraphDatabase.driver(AppConfig.NEO4J_URI, auth=(AppConfig.NEO4J_USER, AppConfig.NEO4J_PASSWORD))

from fastapi import APIRouter, Query, Depends

router = APIRouter()

@router.post("/process-documents/", tags=["Content", "Documents"])
async def process_documents(
    document_limit: int = Query(default=None, description="Limit on number of documents to process"),
    generateQuestions: bool = Query(default=False, description="Flag to generate questions"),
    generateSummaries: bool = Query(default=False, description="Flag to generate summaries"),
    current_user: User = Depends(get_current_user)):
    logging.basicConfig(level=logging.INFO)

    query = "MATCH (a:Document) WHERE NOT (a)-[:HAS_PAGE]->(:Page) and a.text <> '' and a.process=True RETURN a.uuid as uuid"
    if document_limit is not None:
        query += f" LIMIT {document_limit}"
    
    logging.info("Querying for documents to process.")
    document_ids = []
    with driver.session() as session:
        result = session.run(query)
        document_ids = [record['uuid'] for record in result]

    logging.info(f"Found {len(document_ids)} documents to process.")
    
    task_ids = []
    for document_id in document_ids:
        try:
            logging.info(f"Queueing document {document_id} for processing.")
            with driver.session() as session:
                result = session.run("MATCH (a:Document {uuid: $uuid}) RETURN a", {"uuid": document_id})
                document_data = result.single().value()
                text = document_data['text']
                # Pass the generateQuestions and generateSummaries flags to the task
                task = process_text_task.delay(text, document_id, generateQuestions, generateSummaries)
                task_ids.append(task.id)
                logging.info(f"Queued document {document_id} with task ID {task.id}")
        except Exception as e:
            logging.error(f"Failed to queue document {document_id}: {e}")

    return {
        "message": f"Processing started for {len(document_ids)} documents",
        "task_ids": task_ids
    }

@router.post("/token", response_model=Token, description="Returns an access token", summary="Returns an access token", tags=["Users"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=AppConfig.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/divide/")
async def divide(x: int, y: int):
    from worker.tasks import divide
    result = divide.delay(x, y)
    return {"task_id": result.id}


@router.get("/task/{task_id}")
async def get_task_status(task_id: str): 
    """
    Return the status of the submitted Task
    """
    return get_task_info(task_id)


@router.post("/purge-queue/", tags=["Queue Management"])
async def purge_queue(current_user: User = Depends(get_current_user)):
    """
    Purge all tasks in the Celery queue.
    Only accessible to authenticated users.
    """
    if not current_user:  # Add your own authentication checks
        raise HTTPException(status_code=403, detail="Not authorized to purge queue")

    try:
        purge_celery_queue()
        return {"status": "success", "message": "Celery queue purged successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}