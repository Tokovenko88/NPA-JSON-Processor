"""JSON-утилиты: загрузка, сохранение."""

import os
import sys
import re
import json
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import requests
import threading
import copy
from datetime import datetime, timedelta, date
import traceback
from collections import defaultdict
from bs4 import BeautifulSoup
import json5
import queue
import difflib
from json_repair import repair_json

from npa_processor.constants import (
    DEFAULT_OLLAMA_MODEL,
    _ollama_base_url,
    _user_retry_callback,
)

from npa_processor.processing.text_utils import strip_thinking_tags

def load_json(file_path, default):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(file_path, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_html_from_json_response(text, log_callback=None):
    if not text:
        return text
    text = strip_thinking_tags(text)
    text = text.strip()
    if text.startswith('```json') and text.endswith('```'):
        text = text[7:-3].strip()
    elif text.startswith('```') and text.endswith('```'):
        text = text[3:-3].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and 'html' in parsed:
            html = parsed['html']
            if log_callback:
                log_callback("  Извлечён HTML из JSON-объекта", 'info')
            return html
    except json.JSONDecodeError:
        pass
    return text
