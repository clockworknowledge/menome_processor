# menome_processor
worker agent API for processing data for Menome Knowledge Vault

Menome Processor is an aysnc dockerized API that contains long running processes for the Menome Knowledge Vault. 

It uses FASTapi, Celery and Flower to manage long running async processes.

## Setting up:

### Neo4j Database

The docker-compose file provides a default neo4j database, or neo4j Aura can be used in lieu of the docker one. 

A jupyter notebook **setup_database.ipynb** has been provided to initialize the database with default user, indexes and vector indexes needed for the application to function. Ensure you set the variables in the start of the notebook to the same ones used in the .env file when you set that up as per next section. 

## OpenAI Key 

This particular example relies on OpenAI's API - so you will need an OpenAI key. Its likely possible to replace the openAI code with another LLM provider, as this example does use langchain. 

### .env file in /config
You will need a .evn file in a /config folder with the following set:

NEO4J_URI=neo4j+s://URL
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j password
OPENAI_API_KEY=openAI-key
NEO4J_INDEX_NAME=parent_document
NEO4J_CHUNK_NODE_LABEL=Child
SECRET_KEY = "secretKey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 
EMBEDDING_DIMENSION=1536
OPENAI_CHAT_MODEL=gpt-4-1106-preview
OPENAI_EMBEDDING_MODEL=ada
MAX_QUESTIONS_PER_PAGE =5

RABBITMQ_HOST="amqp://guest:guest@localhost:5672//"
RABBMITMQ_PORT=5672
RABBITMQ_USER="guest"
RABBITMQ_PASSWORD="guest"

# Celery Configuration
CELERY_BROKER_URL = "amqp://guest:guest@rabbit:5672//"
CELERY_RESULT_BACKEND_URL ="rpc://"


# Service information
VERSION="1.6.2"
SERVICE_NAME='MenomeProcessingService'
NAME="Menome Knowledge Vault Processing API"

# Environment parameters
FLOWER_HOST="localhost"

# Logging parameters.
LOG_LEVEL="debug"
LOG_DIAGNOSE=true
LOG_FORMAT="<level>{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {module}:{function}:{line} - {message}</level>"

### Graph Document Structure:

Document Knowledge Assets are a form of Published Content that is produced by Authors on a subject for a purpose. This basic structure acts as a 'backbone' for other content processes that would seek to extract additional useful information from the Knowledge Asset and generate new nodes from them. These might inclued : Named Entities such as authors, publishing dates, categories or keywords, places etc. 

The Document is a type of Knowledge Asset that represents a page based artifact that is typically written by an author for the purposes of exploring a subject. Documents can come from file based sources such as PDFs or Microsoft Office, or they can be web page based. For the purposes of this example, the Processor takes a URL of an Article source to process into a Document. 

The processor takes the URL and scrapes the source using Beautiful Soup, extracts the content into a base Document node with simple metadata. It then triggers an Async Celery Worker by registering a Message in RabbitMQ. The Task Worker then breaks the text store in the Document node down into Pages and Child nodes. The Child nodes contain 'chunks' of text that are in this simplified example broken out using Langchain into regularly sized blocks of 100 tokens using the TokenTextSplitter with a chunk overlap of 24 tokens. A more sophisticated implimentation would seek to use a semantic decomposition pattern using paragraphs, sentances, lists and other structures found in typical Documents that help inform context. 

The resulting basic Graph Document structure is as follows: 

**(a:Document)-[:HAS_PAGE]->(p:Page)-[:HAS_CHILD]->(c:Child)**

Document: 
* uuid: unique identifier for node
* name: name of document
* url: url of source
* text: full text of source 
* note: a note about the source
* imageurl: URL of image for source
* publisher: publisher of source
* addeddate: date item was added
* thumbnail: thumbnail image for source
* wordcount: count of number of words in text
* type: "Document"

Page: 
* uuid - unique identifier
* name - name of page computed from processing (Page 1... Page N)
* source - used for getting source nodes from RAG query pattern
* text - page text
* embedding - text embedding for similarity search


Child:
* uuid - unique identifier for chunk
* name - name of chunk if available
* embedding - embedding vector of chunk from OpenAI
* text - full text of chunk 
* source - uuid of document associated with chunk for secondary query


Summary: 
(p:Page)-[:HAS_SUMMARY]->(s:Summary)
* "uuid": unique identifier for summary,
* "text": summary text from LLM,
* "embedding": text embedding for similarity search
* datecreated: date summary was created

Question:
(p:Page)-[:HAS_QUESTION]->(q:Question)
* "text": question text result from LLM, 
* "uuid": unique identifier for question, 
* "name": f"{i+1}-{iq+1}", 
* "embedding": text embedding for similarity search

### Running the system

Start the Neo4j intance if you are using neo4j desktop locally. 

Start by running:
**docker-compose build** 

This should build images defined in the Dockerfiles provided in the docker-compose yaml file. 

**docker-compose up** will pull the rabbit and flower containers and then run them. 

The docker logs should show the four containers started. 

The API will be accessible at:

**http://localhost:8000/docs** 

### Running an example:

Use the **Authorize** button in the Swagger spec to login using the username and password you setup in the jupyter notebook and .env file.

The API will return a token if auth is scucessful. 

Take the following URL from the 1945 Vannevar Bush article As We May Think, which was the original vision that inspired JCR Licklider, Douglas Englebart and Alan Kay to create the foundations for the Dynamic Knowledge systems we are now seeing emerge such as RAG. 

https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/

Use the **add-document** endpoint to add the document to the graph. This procedure will trigger the async process that decomposes the document down in to a graph document. 

You will see the celery_worker_1 process gradually break the document down into pages, chunks, questions and summary. 

You can use the Chat endpoint to ask questions about the documents stored in the graph. 

Asking the question: 

**what is the memex?**

Should return approximately:

```


```

Using MIT license - share and enjoy! 