# menome_processor

## Overview

I developed the menome_processor to experiment with the Retrieval Augmented Generation (RAG) pattern. The objective is to provide a basic, but fully functional API for processing URLs from websites into a Graph Document format that is amenable to supporting RAG using a neo4j graph database as the backing store. 

Since decomposing documents down into pages and chunks that are amenable to RAG is a long running process, I wanted to use an asyc messaging based pattern. The patterns used are influenced by the work done on the original Menome dataLink system, and by the excellent blog series on RAG by [Tomaz Bratanic](https://bratanic-tomaz.medium.com/).

The Processor uses Neo4j graph database as vectorized data store, and via [LangChain](https://langchain.com/)
 using Tomaz Bratanic's [Advanced RAG pattern as](https://neo4j.com/developer-blog/advanced-rag-strategies-neo4j/) foundation. 

It uses FASTapi for the API layer, Celery for the worker, RabbitMQ for the message broker and Flower to manage long running async processes.

The example also has a basic autentication pattern. 

## Setting up:

The example is dockerized so can be run on any standard machine using docker. Docker build files and docker-compose are provided. 

### Neo4j Database

The docker-compose file provides a default neo4j database, or neo4j Aura can be used in lieu of the docker one. 

A jupyter notebook **setup_database.ipynb** has been provided to initialize the database with default user, indexes and vector indexes needed for the application to function. Ensure you set the variables in the start of the notebook to the same ones used in the .env file when you set that up as per next section. 

## OpenAI Key 

This particular example relies on OpenAI's API - so you will need an OpenAI key. Its likely possible to replace the openAI code with another LLM provider, as this example does use langchain. 

### .env file in /config
You will need a .evn file in a /config folder with the following set:
```
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
```

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

### RAG Chat Pattern

The LLM integration relies on the Advanced Retrieval Augmented Generation pattern known as Parent. This pattern leverages the graph and the graph document structure to provide both more specific, targeted answers to questions, while also returning focused sources. It does this by leveraging the graph document combined with the neo4j vector index and cosine similarity. The 'Child' chunks contain small, overlapping tokenized chunks of text are matched based on embedding similarity with the incoming question. 

The graph is used to look back up from the Child chunks, to the page they are associated with. The pages that are 'hit' and their overall parent Document are then collected and returned as part of a JSON response. 

This allows for very rich results to be returned including the source chunks, summary of the asssociated page, and the parent document. This pattern is extremely useful for giving the user specifically targeted answers, combined with the context of those answers.


### Running the system

Start the Neo4j intance if you are using neo4j desktop locally. 

Start by running:
**docker-compose build** 

This will build images defined in the Dockerfiles for the API and the Worker provided in the docker-compose yaml file. 

**docker-compose up** will pull the rabbit and flower containers and then run them. 

The docker logs should show the four containers started. 

The following ports and endpoints are available:

* The API will be accessible at: **http://localhost:8000/docs** 
* RabbitMQ management console: **http://localhost:15762** using the username and password from the config [Documentaiton for RabbitMQ](https://www.rabbitmq.com/management.html)
* Flower is available at: **http://localhost:8888** for monitoring the worker [Documentation for flower](https://flower.readthedocs.io/en/latest/index.html)



### Running an example:

Use the **Authorize** button in the Swagger spec to login using the username and password you setup in the jupyter notebook and .env file.

The API will return a token if auth is scucessful. 

Take the following URL from the 1945 Vannevar Bush article As We May Think, which was the original vision that inspired JCR Licklider, Douglas Englebart and Alan Kay to create the foundations for the Dynamic Knowledge systems we are now seeing emerge such as RAG. 

https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/

Use the **add-document** endpoint to add the document to the graph. This procedure will trigger the async process that decomposes the document down in to a graph document. 

You will see the celery_worker_1 process gradually break the document down into pages, chunks, questions and summary. 

You can use the [neo4j browser]( http://localhost:7474) to inspect the graph that results.  

You can use the Chat endpoint to ask questions about the documents stored in the graph. 

Asking the question: 

**what is the memex?**

Should return approximately:
```
{
  "answer": "The memex is a hypothetical device envisioned by Vannevar Bush that acts as a mechanized private file and library. It is designed so that an individual can store all their books, records, and communications, which can then be consulted with great speed and flexibility. The memex would be capable of storing vast amounts of data, accessed through a device that operates using microfilm technology, with a system that allows for associative indexing, enabling items to select and pull up related items immediately.\n\n",
  "sources": [
    {
      "document": {
        "uuid": "018132c2-fc1f-489f-8c52-2bb1a037f780",
        "name": "As We May Think - The Atlantic",
        "addeddate": "2024-02-07T18:59Z",
        "imageurl": "https://cdn.theatlantic.com/_next/static/images/nav-archive-promo-5541b02ae92f1a9276249e1c6c2534ee.png",
        "publisher": "theatlantic.com",
        "thumbnail": "https://cdn.theatlantic.com/_next/static/images/nav-archive-promo-5541b02ae92f1a9276249e1c6c2534ee.png",
        "url": "https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/",
        "wordcount": 8323
      },
      "pages": [
        {
          "name": "Page 52",
          "children": [
            {
              "text": ". Selection by association, rather than indexing, may yet be mechanized. One cannot hope thus to equal the speed and flexibility with which the mind follows an associative trail, but it should be possible to beat the mind decisively in regard to the permanence and clarity of the items resurrected from storage. Consider a future device for individual use, which is a sort of mechanized private file and library. It needs a name, and, to coin one at random, “memex”",
              "name": "51-1",
              "uuid": "211c3da8-1826-4919-9a67-7c9593234c4d"
            },
            {
              "text": " private file and library. It needs a name, and, to coin one at random, “memex” will do. A memex is a device in which an individual stores all his books, records, and communications, and which is mechanized so that it may be consulted with exceeding speed and flexibility. It is an enlarged intimate supplement to his memory",
              "name": "51-2",
              "uuid": "f1f45936-7e7b-48a8-b974-f30dc1894a4d"
            }
          ],
          "questions": [
            {
              "text": "How does the memex device differ from traditional methods of storing books, records, and communications?",
              "name": "52-5",
              "uuid": "568f0b82-589b-4317-8fe5-09fe27c633d8"
            },
            {
              "text": "What is the proposed name for a future device that acts as a mechanized private file and library?",
              "name": "52-4",
              "uuid": "9e5a9a3e-e084-406c-b4fd-699f56780834"
            },
            {
              "text": "What are the limitations of the human mind in following an associative trail compared to a mechanized system?",
              "name": "52-3",
              "uuid": "4bff8199-7625-4503-9b14-c6978d6d63bf"
            },
            {
              "text": "What is the concept of selection by association in the context of information retrieval?",
              "name": "52-1",
              "uuid": "6fe81dab-1920-4fbf-b7e5-e9f91c3393da"
            },
            {
              "text": "How might mechanization potentially improve the permanence and clarity of stored information?",
              "name": "52-2",
              "uuid": "7ba9a682-490b-4669-b2fd-2a85b0548a14"
            }
          ],
          "summaries": [
            {
              "text": "The concept of a \"memex\" is introduced as a future personal device designed for storing an individual's books, records, and communications. This device would allow for quick and flexible retrieval of information, acting as a mechanical enhancement to one's memory. It aims to surpass the human mind in terms of the durability and clarity of stored information, although it may not match the mind's speed and associative capabilities.",
              "name": null,
              "uuid": "4d1e194c-6158-47b5-868c-9179bae8e846"
            }
          ],
          "uuid": "fde68a33-6fa2-4cc9-a7fa-d955c3f9c261"
        },
        {
          "name": "Page 53",
          "children": [
            {
              "text": ". The matter of bulk is well taken care of by improved microfilm. Only a small part of the interior of the memex is devoted to storage, the rest to mechanism. Yet if the user inserted 5000 pages of material a day it would take him hundreds of years to fill the repository, so he can be profligate and enter material freely. Most of the memex contents are purchased on microfilm ready for insertion",
              "name": "52-2",
              "uuid": "54bf4642-294a-4797-99cc-efb1d0a185f3"
            }
          ],
          "questions": [
            {
              "text": "What is the purpose of the slanting translucent screens on the desk?",
              "name": "53-3",
              "uuid": "bd20b747-fb42-47e2-8164-384dc920655a"
            },
            {
              "text": "Can the desk be operated remotely, and if so, is it its primary mode of operation?",
              "name": "53-2",
              "uuid": "eb2a6c20-5b30-4a16-8bb8-e1cbcfb12659"
            },
            {
              "text": "What input devices are found on the desk?",
              "name": "53-5",
              "uuid": "bb48ed49-fddf-40e0-89bf-9c4310895abc"
            },
            {
              "text": "How is information projected onto the screens for reading?",
              "name": "53-4",
              "uuid": "adf33acd-2231-4d40-ba53-3407650535fc"
            },
            {
              "text": "What is the primary function of the desk mentioned in the text?",
              "name": "53-1",
              "uuid": "98f17786-9408-4655-923e-0f688c00721b"
            }
          ],
          "summaries": [
            {
              "text": "The memex is a desk-like device that can be operated remotely but is mainly used in person. It features slanted, translucent screens for displaying reading material, a keyboard, and various buttons and levers, resembling an ordinary desk in appearance. Storage within the memex is handled efficiently through microfilm, with a small portion of its space dedicated to storing vast amounts of data. Even if a user adds 5000 pages daily, it would take centuries to fill up the storage space, allowing users to add information liberally. Much of the content for the memex is acquired pre-recorded on microfilm, ready to be inserted into the device.",
              "name": null,
              "uuid": "6ae66bc9-14ce-4734-9408-05b89d213fe2"
            }
          ],
          "uuid": "7db95520-e07c-4fcb-b206-729d503e7842"
        },
        {
          "name": "Page 54",
          "children": [
            {
              "text": ". Books of all sorts, pictures, current periodicals, newspapers, are thus obtained and dropped into place. Business correspondence takes the same path. And there is provision for direct entry. On the top of the memex is a transparent platen. On this are placed longhand notes, photographs, memoranda, all sorts of things. When one is in place, the depression of a lever causes it to be photographed onto the next blank space in a section of the memex film, dry",
              "name": "53-1",
              "uuid": "b5ad4d9f-c172-4335-a467-a54e6174bf2f"
            }
          ],
          "questions": [
            {
              "text": "What happens when an item is placed on the memex's platen and a lever is depressed?",
              "name": "54-4",
              "uuid": "b36c5902-a5c8-4b4f-ba8c-a8d44b0b3a71"
            },
            {
              "text": "What types of materials can be obtained and organized using the memex system?",
              "name": "54-1",
              "uuid": "c52a485a-fb41-4a1a-9f68-ea2079da5379"
            },
            {
              "text": "How are business correspondences handled in the memex system?",
              "name": "54-2",
              "uuid": "48174f39-e240-4511-8758-3834e7ec4d3b"
            },
            {
              "text": "What is the purpose of the transparent platen on top of the memex?",
              "name": "54-3",
              "uuid": "7f1d49a2-2637-40f2-894c-fd61b973e091"
            },
            {
              "text": "What method is used to photograph items onto the memex film?",
              "name": "54-5",
              "uuid": "3091fdb7-1163-4730-a789-351d70fcab5c"
            }
          ],
          "summaries": [
            {
              "text": "The memex system allows for the collection and organization of various types of information, including books, pictures, periodicals, newspapers, and business correspondence. Users can also directly input materials such as handwritten notes, photographs, and memoranda by placing them on a transparent platen and photographing them onto the memex film using dry photography. The system includes an indexing scheme for easy retrieval of information. When a user wants to access a specific book, they can enter its code on the keyboard, and the title page is projected onto a viewing screen for consultation.",
              "name": null,
              "uuid": "ea6ba546-7aa6-49f3-aa2c-5f2c7b7d52cf"
            }
          ],
          "uuid": "cfaa74ea-98e8-42ce-b6bc-de21b486081c"
        },
        
      ]
    }
  ],
  "timings": {
    "setup_duration": 0.0014238357543945312,
    "langchain_response_duration": 13.493005752563477,
    "neo4j_fetch_duration": 0.09334850311279297,
    "total_duration": 13.587778091430664
  },
  "payload_sizes": {
    "request_size": 67,
    "response_size": 801,
    "db_response_size": 8480
  }
}
```

Using MIT license - share and enjoy! 