from celery import Celery
from neo4j import GraphDatabase

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores.neo4j_vector import Neo4jVector
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import TokenTextSplitter
from langchain.document_loaders import telegram
from langchain.prompts import ChatPromptTemplate
from langchain.pydantic_v1 import BaseModel, Field
from langchain.chains.openai_functions import create_structured_output_chain
from langchain.chat_models import ChatOpenAI
from  models import Question
from celery.result import AsyncResult
from neo4j.exceptions import Neo4jError

import uuid
import logging 
from typing import List

from config import AppConfig
from dotenv import load_dotenv

from celery import Celery
import time
from kombu.exceptions import OperationalError


# Initialize environment variables if needed
AppConfig.initialize_environment_variables()
logging.info(f"Starting worker")

class Questions(BaseModel):
    """Generating hypothetical questions about text."""

    questions: List[str] = Field(
        ...,
        description=(
            "Generated hypothetical questions based on " "the information from the text"
        ),
    )


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
broker_url = "amqp://guest:guest@rabbit:5672//"
result_backend_url = "rpc://"


# Create the Celery app
celery_app = create_celery_app(broker_url, result_backend_url)


from celery.result import AsyncResult
from celery.exceptions import TimeoutError, CeleryError

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
@celery_app.task(bind=True, name="celery_worker.process_text_task")
def process_text_task(self, textToProcess: str, documentId: str):
    logging.info(f"Starting process for document {documentId}")
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
        
        # Generate Questions for page node 
        logging.info(f"Generating questions for document {documentId}")
        questions_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are generating hypothetical questions based on the information "
                        "found in the text. Make sure to provide full context in the generated "
                        "questions."
                    ),
                ),
                (
                    "human",
                    (
                        "Use the given format to generate hypothetical questions from the "
                        "following input: {input}"
                    ),
                ),
            ]
        )
     
        logging.info(f"LLM type: {type(llm)}, Prompt: {questions_prompt}")
        
        question_chain = create_structured_output_chain(Questions, llm, questions_prompt)

        for i, parent in enumerate(parent_documents):
            logging.info(f"Generating questions for page {i+1} of {len(parent_documents)} for document {documentId}")
            generated_questions = question_chain.run(parent.page_content).questions
            limited_questions = generated_questions[:AppConfig.MAX_QUESTIONS_PER_PAGE]  # Limit the number of questions

            params = {
                "parent_id": f"Page {i+1}",
                "document_uuid": documentId,
                "questions": [
                    {
                        "text": q, 
                        "uuid": str(uuid.uuid4()), 
                        "name": f"{i+1}-{iq+1}", 
                        "embedding": embeddings.embed_query(q)
                    }
                    for iq, q in enumerate(limited_questions) if q  # Iterate over limited questions
                ],
            }
            with driver.session() as session :
                session.run(
                    """
                match (d:Document)-[]-(p:Page) where d.uuid=$document_uuid and p.name=$parent_id
                WITH p
                UNWIND $questions AS question
                CREATE (q:Question {uuid: question.uuid})
                SET q.text = question.text, q.name = question.name, q.datecreated= datetime(), q.source=p.uuid
                MERGE (q)<-[:HAS_QUESTION]-(p)
                WITH q, question
                CALL db.create.setVectorProperty(q, 'embedding', question.embedding)
                YIELD node
                RETURN count(*)
                """,
                params,
            )
            
            
        # Ingest summaries

        summary_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are generating concise and accurate summaries based on the "
                        "information found in the text."
                    ),
                ),
                (
                    "human",
                    ("Generate a summary of the following input: {question}\n" "Summary:"),
                ),
            ]
        )

        summary_chain = summary_prompt | llm

        for i, parent in enumerate(parent_documents):
            logging.info(f"Generating summary for page {i+1} of {len(parent_documents)} for document {documentId}")
            
            summary = summary_chain.invoke({"question": parent.page_content}).content
            params = {
                "parent_id": f"Page {i+1}",
                "uuid": str(uuid.uuid4()),
                "summary": summary,
                "embedding": embeddings.embed_query(summary),
                "document_uuid": documentId
            }
            with driver.session() as session :
                session.run(
                    """
                match (d:Document)-[]-(p:Page) where d.uuid=$document_uuid and p.name=$parent_id
                with p
                MERGE (p)-[:HAS_SUMMARY]->(s:Summary)
                SET s.text = $summary, s.datecreated= datetime(), s.uuid= $uuid, s.source=p.uuid
                WITH s
                CALL db.create.setVectorProperty(s, 'embedding', $embedding)
                YIELD node
                RETURN count(*)
                """,
                    params,
                )
    except Exception as e:
            logging.error(f"Failed to process document {documentId}: {e}")
            return {"message": "Failed", "error": str(e), "task_id": self.request.id}

    logging.info(f"Successfully processed document {documentId}")
    return {"message": "Success", "uuid": documentId, "task_id": self.request.id}


