import os
from decouple import Config, RepositoryEnv

class AppConfig:
    DOTENV_FILE = '/code/config/.env'
    config = Config(RepositoryEnv(DOTENV_FILE))

    # Database Configurations
    NEO4J_URI = config.get('NEO4J_URI', default='bolt://localhost:7687')
    NEO4J_USER = config.get('NEO4J_USER', default='neo4j')
    NEO4J_PASSWORD = config('NEO4J_PASSWORD')
    NEO4J_INDEX_NAME = config('NEO4J_INDEX_NAME', default='typical_rag')
    NEO4J_CHUNK_LABEL = config('NEO4J_CHUNK_LABEL', default='Child')
    NEO4J_CHUNK_TEXT_PROPERTY = config('NEO4J_CHUNK_TEXT_PROPERTY', default='text')
    NEO4J_CHUNK_EMBEDDING_PROPERTY = config('NEO4J_CHUNK_EMBEDDING_PROPERTY', default='embedding')

    # DEFAULT USER:
    DEFAULT_USER_UUID = config('DEFAULT_USER_UUID', default='00000000-0000-0000-0000-000000000000')
    DEFAULT_USER_USERNAME = config('DEFAULT_USER_USERNAME', default='admin')
    DEFAULT_USER_EMAIL = config('DEFAULT_USER_EMAIL',
                                default='test@test.com')
    DEFAULT_USER_NAME = config('DEFAULT_USER_NAME', default='Admin')
    DEFAULT_USER_PASSWORD = config('DEFAULT_USER_PASSWORD', default='test')

    # OpenAI Configuration
    OPENAI_API_KEY = config('OPENAI_API_KEY')
    EMBEDDING_DIMENSION = config('EMBEDDING_DIMENSION', cast=int, default=1536)
    OPENAI_CHAT_MODEL = config('OPENAI_CHAT_MODEL', default='gpt-4-1106-preview')

    RABBITMQ_HOST = config('RABBMITMQ_HOST', default='localhost')
    RABBITMQ_PORT = config('RABBMITMQ_PORT', cast=int, default=5672)
    RABBITMQ_USER = config('RABBITMQ_USER', default='admin')
    RABBITMQ_PASSWORD = config('RABBITMQ_PASSWORD', default='brier23glrefy!')

    # Celery Configuration
    CELERY_BROKER_URL = config.get('CELERY_BROKER_URL', default='amqp://guest:guest@rabbit:5672//')
    CELERY_RESULT_BACKEND_URL = config.get('CELERY_RESULT_BACKEND_URL', default='rpc://')


    # State processing messages:
    # Task states and celery configuration 
    PROCESSING_DOCUMENT = 'PROCESSING_DOCUMENT'
    PROCESSING_QUESTIONS = 'PROCESSING_QUESTIONS'
    PROCESSING_SUMMARY = 'PROCESSING_SUMMARY'
    PROCESSING_DONE = 'PROCESSING_DONE'
    PROCESSING_FAILED = 'PROCESSING_FAILED'
    PROCESSING_PAGES = 'PROCESSING_PAGES'

    # Other Configurations
    MAX_QUESTIONS_PER_PAGE = config('MAX_QUESTIONS_PER_PAGE', cast=int, default=2)
    SECRET_KEY=config('SECRET_KEY')
    ALGORITHM=config('ALGORITHM')
    TEST_DOCUMENT_URL = "https://en.wikipedia.org/wiki/As_We_May_Think"
    ACCESS_TOKEN_EXPIRE_MINUTES = config('ACCESS_TOKEN_EXPIRE_MINUTES', cast=int, default=30)

    @staticmethod
    def initialize_environment_variables():
        os.environ["OPENAI_API_KEY"] = AppConfig.OPENAI_API_KEY
        os.environ["NEO4J_URI"] = AppConfig.NEO4J_URI
        os.environ["NEO4J_USERNAME"] = AppConfig.NEO4J_USER
        os.environ["NEO4J_PASSWORD"] = AppConfig.NEO4J_PASSWORD
