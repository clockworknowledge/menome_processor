import logging
import uuid
from typing import List

from langchain.pydantic_v1 import BaseModel, Field
from langchain.chains.openai_functions import create_structured_output_chain
from langchain.chains.openai_functions import create_structured_output_chain
from langchain.prompts import ChatPromptTemplate

from config import AppConfig
from  models import Question


# internal classes
#TODO: refactor this to a separate file
class Questions(BaseModel):
    """Generating hypothetical questions about text."""

    questions: List[str] = Field(
        ...,
        description=(
            "Generated hypothetical questions based on " "the information from the text"
        ),
    )

# Initialize environment variables if needed
AppConfig.initialize_environment_variables()

def generate_questions(self,llm, parent_documents, documentId, embeddings, driver):

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
        self.update_state(state=AppConfig.PROCESSING_QUESTIONS, meta={"page": i+1, "total_pages": len(parent_documents), "documentId": documentId})
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
        

def generate_summaries(self,llm, parent_documents, documentId, embeddings, driver):
    # Code for generating summaries
       
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
        self.update_state(state=AppConfig.PROCESSING_SUMMARY, meta={"page": i+1, "total_pages": len(parent_documents), "documentId": documentId})
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