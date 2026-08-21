import os
from collections import namedtuple
from dotenv import load_dotenv

load_dotenv()

_ModxSettings = namedtuple(
    '_ModxSettings',
    [
        'modx_ssh_host',
        'modx_ssh_port',
        'modx_ssh_username',
        'modx_ssh_password',
        'modx_base_path',
        'default_ollama_model',
        'ollama_base_url',
    ],
)


def get_settings():
    return _ModxSettings(
        modx_ssh_host=os.environ.get('MODX_SSH_HOST'),
        modx_ssh_port=int(os.environ.get('MODX_SSH_PORT', '22')),
        modx_ssh_username=os.environ.get('MODX_SSH_USERNAME'),
        modx_ssh_password=os.environ.get('MODX_SSH_PASSWORD'),
        modx_base_path=os.environ.get('MODX_BASE_PATH'),
        default_ollama_model=os.environ.get('OLLAMA_DEFAULT_MODEL', 'gemini-1.5-flash'),
        ollama_base_url=os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434'),
    )


def get_modx_db_config():
    return {
        'host': os.environ.get('MODX_DB_HOST'),
        'port': int(os.environ.get('MODX_DB_PORT', '3306')),
        'user': os.environ.get('MODX_DB_USER'),
        'password': os.environ.get('MODX_DB_PASSWORD'),
        'database': os.environ.get('MODX_DB_NAME'),
        'charset': os.environ.get('MODX_DB_CHARSET', 'utf8'),
    }
