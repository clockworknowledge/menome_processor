from fastapi import APIRouter, Depends, HTTPException, status
from bs4 import BeautifulSoup, Comment
from typing import List
from jose import JWTError, jwt

import uuid
from datetime import datetime
from urllib.parse import urlparse
import httpx

from config import AppConfig
from models import User, DocumentRequest, DefaultIcons, UserIn
from worker.tasks import process_text_task, get_task_info, purge_celery_queue
from app.routers.utils import get_current_user, get_user_from_db, neo4j_datetime_to_python_datetime


from langchain.chat_models import ChatOpenAI
from fastapi.security import OAuth2PasswordBearer
from neo4j import GraphDatabase, Transaction  # Import Neo4j driver

import logging

# Global Variables
router = APIRouter()
llm = ChatOpenAI(temperature=0, model="gpt-4-1106-preview")
# Initialize environment variables if needed
AppConfig.initialize_environment_variables()

# Assuming you have a Neo4j driver instance
driver = GraphDatabase.driver(AppConfig.NEO4J_URI, auth=(AppConfig.NEO4J_USER, AppConfig.NEO4J_PASSWORD))

# Inside documents.py
def extract_title(soup: BeautifulSoup, document_id: str) -> str:
    title = soup.title.string if soup.title else None
    if not title:
        title = f"Untitled Document {document_id}"
        meta_title = soup.find('meta', attrs={'property': 'og:title'})
        if meta_title:
            title = meta_title.get('content', title)
    return title


def extract_primary_image(soup: BeautifulSoup) -> str:
    default_image_url = DefaultIcons.ARTICLE_ICON_SVG
    image = soup.find('meta', property='og:image')
    if image and image.get('content'):
        return image['content']
    image = soup.find('img')
    if image and image.get('src'):
        return image['src']
    return default_image_url  # Return a default image URL if no image is found


def extract_publisher(soup: BeautifulSoup, url: str) -> str:
    publisher = soup.find('meta', property='og:site_name')
    if publisher and publisher.get('content'):
        return publisher['content']
    domain = urlparse(url).netloc
    if domain:
        return domain.replace("www.", "")
    return ''

def extract_full_text(soup: BeautifulSoup) -> str:
    # Remove unwanted tags:
    for tag in soup.find_all(['script', 'style', 'meta', 'noscript']):
        tag.extract()
    
    # Attempt to find the main document element based on common HTML structures.
    # You may need to adjust the tag name and class name based on the specific HTML structure of the pages you're working with.
    document_element = soup.find('div', {'class': 'document-content'})
    if document_element:
        return document_element.get_text(' ', strip=True)  # Use a space as the separator for text in different elements, and strip leading/trailing whitespace.

    # If the main document element wasn't found, fall back to extracting all text.
    return soup.get_text(' ', strip=True)

def normalize_whitespace(text: str) -> str:
    return ' '.join(text.split())

def tag_visible(element):
    if element.parent.name in ['style', 'script', 'head', 'title', 'meta', '[document]']:
        return False
    if isinstance(element, Comment):
        return False
    return True

def remove_html_tags(text):
    return BeautifulSoup(text, "html.parser").get_text()

def remove_non_ascii(text):
    return ''.join(character for character in text if ord(character) < 128)

def clean_text(text: str) -> str:
    text = remove_html_tags(text)
    text = normalize_whitespace(text)
    text = remove_non_ascii(text)
    return text


def extract_thumbnail(soup: BeautifulSoup) -> str:
    thumb = soup.find('meta', attrs={'name': 'thumbnail'})

    if thumb:
        return thumb.get('content', '')
    # If no thumbnail meta tag is found, try fetching the primary image as a fallback
    return extract_primary_image(soup)


# ------------------------------------------------------------------------------------------------
# REST Endpoints for documents
@router.post("/add-document",
             summary="Allows for adding an document to the graph from specified URL",
             description="Take the specified uri and add the document to the graph using beautiful soup to extract the content",
             tags=["Documents"]
            )
async def add_document(request: DocumentRequest, current_user: User = Depends(get_current_user)):
    
    headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.140 Safari/537.36 Edge/17.17134"
}
    logging.basicConfig(level=logging.INFO)

    logging.info(f"Fetching document from {request.url}")
    url_str = str(request.url)
    logging.info(f"Fetching document from {url_str}")

    async with httpx.AsyncClient() as client:
        response = await client.get(url_str, headers=headers)
        if response.status_code != 200:
            logging.error(f"Failed to fetch document from {url_str}: Status {response.status_code}")
            raise HTTPException(status_code=400, detail=f"Could not fetch document from {url_str}")

    soup = BeautifulSoup(response.content, 'html.parser')


    documentId=str(uuid.uuid4())
    title = extract_title(soup, documentId)
    text = extract_full_text(soup)
    imageurl = extract_primary_image(soup)
    publisher = extract_publisher(soup, url_str)
    thumbnail = extract_thumbnail(soup)
    wordcount = len(text.split())
    note=request.note
    logging.info(f"Document {documentId} has {wordcount} words")
    utc_now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M') + 'Z'  # No seconds or microseconds, append 'Z' for UTC
    
    query = """
    CREATE (d:Document {
        uuid: $uuid,
        name: $name,
        url: $url,
        text: $text,
        note: $note,
        imageurl: $imageurl,
        publisher: $publisher,
        addeddate: $addeddate,
        thumbnail: $thumbnail,
        wordcount: $wordcount,
        type: "Document"
    })
    with d
    MATCH (u:User {uuid: $useruuid})
    MERGE (ua:UserAction {useruuid: u.uuid}) 
    ON CREATE SET ua.name = u.username, ua.uuid=randomUUID()
    MERGE (u)-[r:HAS_ACTION]->(ua)
    MERGE (ua)-[:ADDED]-(d) set r.dateadded= datetime()
    """
    with driver.session() as session:
        def create_document(tx: Transaction):
            return tx.run(query, {
                "uuid": documentId,
                "name": title,
                "url": request.url,
                "text": text,
                "note": note,
                "imageurl": imageurl,
                "publisher": publisher,
                "addeddate": utc_now,
                "thumbnail": thumbnail,
                "wordcount": wordcount,
                "useruuid": current_user.uuid
            }).consume()
        session.write_transaction(create_document)

        #try:
        task_ids = []
        logging.info(f"Queueing document {documentId} for processing.")
        with driver.session() as session:
            result = session.run("MATCH (a:Document {uuid: $uuid}) RETURN a", {"uuid": documentId})
            document_data = result.single().value()
            text = document_data['text']
            # Pass the generateQuestions and generateSummaries flags to the task
            task = process_text_task.delay(text, documentId, True, True)
            task_ids.append(task.id)
            logging.info(f"Queued document {documentId} with task ID {task.id}")
    #except Exception as e:
        #logging.error(f"Failed to queue document {documentId}: {e}")

        return {
            "message": f"Processing started for {len(documentId)} documents",
            "task_ids": task_ids
        }

