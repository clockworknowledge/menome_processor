from celery import Celery
from celery.result import AsyncResult

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores.neo4j_vector import Neo4jVector
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import TokenTextSplitter
from langchain.document_loaders import telegram
from langchain.prompts import ChatPromptTemplate
from langchain.pydantic_v1 import BaseModel, Field
from langchain.chat_models import ChatOpenAI

import uuid
import logging 
from typing import List
from dotenv import load_dotenv
import time
from kombu.exceptions import OperationalError
import threading

from config import AppConfig
from .processing_functions import generate_questions, generate_summaries


# Initialize environment variables if needed
AppConfig.initialize_environment_variables()
logging.info(f"Starting worker")

# Assuming you have a global variable to track the number of active tasks
active_tasks_lock = threading.Lock()
active_tasks_count = 0
MAX_CONCURRENT_TASKS = 2  # Set your maximum concurrent tasks


def create_celery_app(broker_url, result_backend, max_retries=5, wait_seconds=5):
    """
    Create and configure a Celery app, ensuring that the broker is available.
    """
    # Wait for the RabbitMQ broker to be ready
    for _ in range(max_retries):
        try:
            # Try to establish a connection to the broker
            celery_temp = Celery(broker=broker_url)
            celery_temp.connection().ensure_connection(max_retries=1)
            print("Successfully connected to the broker!")
            break
        except OperationalError:
            print(f"Broker connection failed. Retrying in {wait_seconds} seconds...")
            time.sleep(wait_seconds)
    else:
        raise Exception("Failed to connect to the broker after several attempts.")

    # Create the Celery app
    celery_app = Celery("worker", broker=broker_url, result_backend=result_backend)
    celery_app.conf.task_routes = {"celery_worker.test_celery": "celery"}
    celery_app.conf.update(task_track_started=True)

    return celery_app

# Define your broker and result backend URLs
broker_url = AppConfig.CELERY_BROKER_URL
result_backend_url = AppConfig.CELERY_RESULT_BACKEND_URL


# Create the Celery app
celery_app = create_celery_app(broker_url, result_backend_url)
# Set a lower acknowledgment timeout, for example, 300 seconds (5 minutes)
celery_app.conf.broker_transport_options = {'confirm_publish': True, 'acknowledgement_timeout': 300}
# Set heartbeat interval and prefetch count
celery_app.conf.broker_heartbeat = 10  # seconds
celery_app.conf.worker_prefetch_multiplier = 1


from celery.result import AsyncResult
from celery.exceptions import TimeoutError, CeleryError

from celery.app.control import Inspect

def purge_celery_queue():
    i = Inspect(app=celery_app)
    active_queues = i.active_queues()
    if active_queues:
        for queue in active_queues.keys():
            celery_app.control.purge()


def get_task_info(task_id: str):
    try:
        task = AsyncResult(task_id)

        # Task Not Ready
        if not task.ready():
            return {"task_id": str(task_id), "status": task.status}

        # Task done: return the value
        task_result = task.get(timeout=10)  # Set a timeout for task.get() if needed
        return {
            "task_id": str(task_id),
            "result": task_result,
            "status": task.status
        }

    except TimeoutError:
        # Handle timeout exceptions
        return {
            "task_id": str(task_id),
            "error": "Timeout while retrieving the task result",
            "status": "TIMEOUT"
        }

    except CeleryError as e:
        # Handle general Celery errors
        return {
            "task_id": str(task_id),
            "error": str(e),
            "status": "ERROR"
        }

    except Exception as e:
        # Handle other exceptions
        return {
            "task_id": str(task_id),
            "error": f"An error occurred: {e}",
            "status": "FAILURE"
        }

# Set up Neo4j driver (replace with your actual connection details)
driver = GraphDatabase.driver(AppConfig.NEO4J_URI, auth=(AppConfig.NEO4J_USER, AppConfig.NEO4J_PASSWORD))
llm = ChatOpenAI(temperature=0, model="gpt-4-1106-preview")

## Worker tasks

@celery_app.task(name="celery_worker.test_celery")
def divide(x, y):
    import time
    print("Starting divide task")
    time.sleep(5)
    return x / y

# Celery task for processing text
@celery_app.task(bind=True, rate_limit="1/m", name="celery_worker.process_text_task")
def process_text_task(self, textToProcess: str, documentId: str, generateQuestions: bool, generateSummaries: bool):
    logging.info(f"Starting process for document {documentId}")
    self.update_state(state=AppConfig.PROCESSING_DOCUMENT, meta={"documentId": documentId})

    global active_tasks_count

    # Task Concurrency Management
    with active_tasks_lock:
        # Check if the maximum number of concurrent tasks has been reached
        if active_tasks_count >= MAX_CONCURRENT_TASKS:
            # Requeue or delay the task
            raise self.retry(countdown=60)  # Retry after 60 seconds

        # Increment the count of active tasks
        active_tasks_count += 1

    try: 
        doc = telegram.text_to_docs(textToProcess)  

        # Setup splitters 
        parent_splitter = TokenTextSplitter(chunk_size=512, chunk_overlap=24)
        child_splitter = TokenTextSplitter(chunk_size=100, chunk_overlap=24)
        parent_documents = parent_splitter.split_documents(doc)

        # Setup embeddings
        embeddings = OpenAIEmbeddings(openai_api_key=AppConfig.OPENAI_API_KEY, embedding_dimension=AppConfig.EMBEDDING_DIMENSION)

        # Iterate through parent and child chunks for document and generate structure
        for i, parent in enumerate(parent_documents):

            self.update_state(state=AppConfig.PROCESSING_PAGES, meta={"page": i+1, "total_pages": len(parent_documents), "documentId": documentId})
            logging.info(f"processing chunk {i+1} of {len(parent_documents)} for document {documentId}")
            
            child_documents = child_splitter.split_documents([parent])
            params = {
                "document_uuid": documentId,
                "parent_uuid": str(uuid.uuid4()),
                "name": f"Page {i+1}",
                "parent_text": parent.page_content,
                "parent_id": i,
                "parent_embedding": embeddings.embed_query(parent.page_content),
                "children": [
                    {
                        "text": c.page_content,
                        "id": str(uuid.uuid4()),
                        "name": f"{i}-{ic+1}",
                        "embedding": embeddings.embed_query(c.page_content),
                    }
                    for ic, c in enumerate(child_documents)
                ],
            }

            try:
                # Ingest data
                with driver.session() as session :
                    session.run(
                    """
                        MERGE (p:Page {uuid: $parent_uuid})
                        SET p.text = $parent_text,
                        p.name = $name,
                        p.type = "Page",
                        p.datecreated= datetime(),
                        p.source=$parent_uuid
                        WITH p
                        CALL db.create.setVectorProperty(p, 'embedding', $parent_embedding) YIELD node
                        WITH p
                            MATCH (d:Document {uuid: $document_uuid})
                            MERGE (d)-[:HAS_PAGE]->(p)
                        WITH p 
                        UNWIND $children AS child
                            MERGE (c:Child {uuid: child.id})
                            SET 
                                c.text = child.text,
                                c.name = child.name,
                                c.source=child.id
                            MERGE (c)<-[:HAS_CHILD]-(p)
                            WITH c, child       
                                CALL db.create.setVectorProperty(c, 'embedding', child.embedding)
                            YIELD node
                            RETURN count(*)
                        """,
                            params,
                        )
            except Neo4jError as e:
                logging.error(f"Neo4j error in document {documentId}, chunk {i+1}: {e}")
                raise    
        
        if generateQuestions:
            generate_questions(self,llm, parent_documents, documentId, embeddings, driver)

            
        if generateSummaries:
            generate_summaries(self, llm, parent_documents, documentId, embeddings, driver) 

    except Exception as e:
        logging.error(f"Failed to process document {documentId}: {e}")
        self.update_state(state=AppConfig.PROCESSING_FAILED, meta={"documentId": documentId})
        return {"message": "Failed", "error": str(e), "task_id": self.request.id}
    
    finally:
        with active_tasks_lock:
            # Decrement the count of active tasks
            active_tasks_count -= 1

    self.update_state(state=AppConfig.PROCESSING_DONE, meta={"documentId": documentId})
    logging.info(f"Successfully processed document {documentId}")
    return {"message": "Success", "uuid": documentId, "task_id": self.request.id}


