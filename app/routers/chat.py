import os
import sys
from fastapi import APIRouter, Body
from config import AppConfig
from app.routers.utils import fetch_node_properties_by_uuid, setup_graph_db
from pydantic import BaseModel
import json

from langchain.vectorstores import Neo4jVector
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from langchain.chains.summarize import load_summarize_chain
from langchain.chains import RetrievalQAWithSourcesChain
from langchain.chat_models import ChatOpenAI
import openai

from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.pydantic_v1 import BaseModel
from models import User

from fastapi import Depends
from app.routers.utils import get_current_user, get_user_from_db, neo4j_datetime_to_python_datetime

import logging 
import time

from fastapi import Query

router = APIRouter()

# Inside chat.py
print("Chat routes imported")


# Set the logging level
logging.basicConfig(level=logging.INFO)
# Enable logging for Langchain
logging.getLogger("langchain").setLevel(logging.INFO)


# Initialze environment:
os.environ["OPENAI_API_KEY"] =AppConfig.OPENAI_API_KEY
openai.api_key =  AppConfig.OPENAI_API_KEY

# Initialize Neo4j driver (do this once, e.g., at the top of your file or in another module)
uri = AppConfig.NEO4J_URI

# Add typing for input
class Question(BaseModel):
    question: str



# Try initializing the parent_retriever vector store
try:
    # setup Parent retriever for advanced RAG pattern
    parent_query = """
    MATCH (node)<-[:HAS_CHILD]-(parent)
    WITH parent, max(score) AS score 
    RETURN parent.uuid as uuid, parent.uuid as source, parent.text AS text, score, {} AS metadata LIMIT 5
    """

    parent_vectorstore = Neo4jVector.from_existing_index(
        OpenAIEmbeddings(openai_api_key=AppConfig.OPENAI_API_KEY),
        index_name="parent_document",
        url=AppConfig.NEO4J_URI,
        username=AppConfig.NEO4J_USER,
        password=AppConfig.NEO4J_PASSWORD,
        retrieval_query=parent_query,
        #text_node_property="text",
        #node_label="Child",
    )
except ServiceUnavailable as e:
    if "Index not found" in str(e):  # Replace with the appropriate error message for your setup
        setup_graph_db()  # If the index does not exist, set it up
    else:
        raise e  # If the error is due to another reason, raise the exception


# Try initializing the vector store
try:
    # setup Parent retriever for advanced RAG pattern
    parent_query = """
    MATCH (node)<-[:HAS_CHILD]-(parent)
    WITH parent, max(score) AS score 
    RETURN parent.uuid as uuid, parent.uuid as source, parent.text AS text, score, {} AS metadata LIMIT 5
    """

    typical_vectorstore = Neo4jVector.from_existing_index(
        OpenAIEmbeddings(openai_api_key=AppConfig.OPENAI_API_KEY),
        index_name="typical_rag",
        url=AppConfig.NEO4J_URI,
        username=AppConfig.NEO4J_USER,
        password=AppConfig.NEO4J_PASSWORD,
        #retrieval_query=parent_query,
        text_node_property="text",
        node_label="Child",
        
    )
except ServiceUnavailable as e:
    if "Index not found" in str(e):  # Replace with the appropriate error message for your setup
        setup_graph_db()  # If the index does not exist, set it up
    else:
        raise e  # If the error is due to another reason, raise the exception


class ChatRequest(BaseModel):
    question: str


@router.get("/chatSources",
             summary="Chat with source references",
             description="This endpoint provides a chat response along with sources of information. It uses the ChatOpenAI model for generating responses.",
             tags=["Chat", "Sources"])
def chatSourcesquestion(question: str = Query(..., description="The question to be processed"), current_user: User = Depends(get_current_user)):
    driver = GraphDatabase.driver(uri, auth=(AppConfig.NEO4J_USER, AppConfig.NEO4J_PASSWORD))  

    # Start measuring time
    start_time = time.time()
    request_payload = json.dumps({"question": question}).encode('utf-8')
    request_payload_size = sys.getsizeof(request_payload)

    # Generate a response in chatGPT style based on the user's question
    chain = RetrievalQAWithSourcesChain.from_chain_type(
        ChatOpenAI(temperature=1, max_tokens=4000, model_name="gpt-4-1106-preview", openai_api_key=AppConfig.OPENAI_API_KEY),
        chain_type="stuff",
        retriever=typical_vectorstore.as_retriever(search_kwargs={"k": 5, 'score_threshold': 0.5})
    )

    # Measure time after setting up the chain
    setup_time = time.time()

    langchain_response = chain({"question": question}, return_only_outputs=False)


    # Measure time after getting the response
    langchain_response_time = time.time()
    langchain_response_payload = json.dumps(langchain_response).encode('utf-8')
    langchain_response_payload_size = sys.getsizeof(langchain_response_payload)

    # Extract 'answer' and 'sources' (UUIDs) from the chain response
    answer = langchain_response.get('answer', '')
    uuids = langchain_response.get('sources', [])

    if isinstance(uuids, str):
        uuids = [uuid.strip() for uuid in uuids.split(",")]

    # Fetch node properties from Neo4j based on UUIDs
    nodes_data = fetch_node_properties_by_uuid(driver, uuids)
    nodes_data_payload = json.dumps(nodes_data).encode('utf-8')
    nodes_data_payload_size = sys.getsizeof(nodes_data_payload)

    # Measure time after fetching data from Neo4j
    neo4j_fetch_time = time.time()

    # Calculate elapsed times
    setup_duration = setup_time - start_time
    response_duration = langchain_response_time - setup_time
    fetch_duration = neo4j_fetch_time - langchain_response_time
    total_duration = neo4j_fetch_time - start_time
    
    driver.close()

    return {
        "answer": answer,
        "sources": nodes_data,
        "timings": {
            "setup_duration": setup_duration,
            "langchain_response_duration": response_duration,
            "neo4j_fetch_duration": fetch_duration,
            "total_duration": total_duration
        },
        "payload_sizes": {
            "request_size": request_payload_size,
            "response_size": langchain_response_payload_size,
            "db_response_size": nodes_data_payload_size
        }
    }


