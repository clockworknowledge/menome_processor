from pydantic import BaseModel
from pydantic.networks import HttpUrl
from datetime import datetime
from typing import Optional
from enum import Enum
from typing import List
from langchain.pydantic_v1 import Field

# Models
class UserIn(BaseModel):
    uuid: Optional[str] = None
    username: str
    email: str
    name: str
    disabled: Optional[bool] = None
    password: str
    datecreated: Optional[datetime] = None

class User(BaseModel):
    uuid: str
    username: str
    email: str
    name: str
    disabled: Optional[bool] = None
    datecreated: Optional[datetime] = None

class DocumentRequest(BaseModel):
    url: HttpUrl

class DocumentResponse(BaseModel):
    uuid: str
    name: str
    url: HttpUrl
    text: str
    imageurl: str
    publisher: str
    addeddate: str
    thumbnail: str
    wordcount: int

# Add typing for input
class Question(BaseModel):
    question: str

class Questions(BaseModel):
        """Generating hypothetical questions about text."""

        questions: List[str] = Field(
            ...,
            description=(
                "Generated hypothetical questions based on " "the information from the text"
            ),
        )

class DefaultIcons:
    ARTICLE_ICON_SVG="""<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                        </svg>"""