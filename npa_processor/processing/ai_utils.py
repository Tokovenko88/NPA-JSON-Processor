"""Утилиты для взаимодействия с Ollama API."""

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

import npa_processor.constants as _constants

from npa_processor.constants import (
    PROMPTS_DIR,
    LAST_PATHS_FILE,
    STAGE_ANSWERS_FILE,
    DEFAULT_EXTRA_OPTIONS,
    TYPE_TO_RUSSIAN,
    PLURAL_TO_SINGULAR,
    DEFAULT_OLLAMA_MODEL,
    _ollama_base_url,
    load_prompt_from_file,
    PROMPT_1,
    PROMPT_2,
    PROMPT_3,
    PROMPT_4,
)

from npa_processor.processing.text_utils import strip_thinking_tags


def ask_ollama(prompt, model, log_callback, extra_options=None, stop_event=None, max_retries=3, retry_delay=30, change_info=None):
    if stop_event and stop_event.is_set():
        if log_callback:
            log_callback("  Запрос к Ollama отменён", 'warning')
        return None
    if not model or not model.strip():
        try:
            resp = requests.get(f"{_ollama_base_url}/api/tags", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                models = [m['name'] for m in data.get('models', [])]
                if models:
                    model = models[0]
                else:
                    model = DEFAULT_OLLAMA_MODEL
            else:
                model = DEFAULT_OLLAMA_MODEL
        except Exception:
            model = DEFAULT_OLLAMA_MODEL
    else:
        model = model.strip()
    if log_callback:
        log_callback(f"  Запрос к Ollama (модель: {model})", 'info')
        input_match = re.search(r'<(?:input_data|input_document|change_doc)>(.*?)</(?:input_data|input_document|change_doc)>', prompt, re.DOTALL | re.IGNORECASE)
        if input_match:
            input_content = input_match.group(1).strip()
            log_callback(f"  ВХОДНЫЕ ДАННЫЕ (полностью):\n{input_content}", 'input')
        else:
            log_callback(f"  (Входные данные не найдены в промпте)", 'warning')
        log_callback(f"  Параметры: temperature={extra_options.get('temperature', 0.0) if extra_options else 0.0}, top_p={extra_options.get('top_p', 0.1) if extra_options else 0.1}", 'info')
    temperature = extra_options.get("temperature", 0.0) if extra_options else 0.0
    top_p = extra_options.get("top_p", 0.1) if extra_options else 0.1
    url = f"{_ollama_base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
        }
    }
    attempt = 0
    while True:
        try:
            response = requests.post(url, json=payload, timeout=900)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            data = response.json()
            answer = data.get("response", "").strip()
            if not answer:
                raise ValueError("Ollama вернул пустой текст")
            if log_callback:
                log_callback(f"  Получен ответ (длина {len(answer)} символов):\n{answer}", 'result')
            cleaned_answer = strip_thinking_tags(answer)
            if cleaned_answer != answer:
                if log_callback:
                    log_callback(f"  ⚠ Обнаружены и удалены <thinking>-теги из ответа ИИ (было {len(answer)} симв. → стало {len(cleaned_answer)} симв.)", 'warning')
                answer = cleaned_answer
            if answer.startswith("```json") and answer.endswith("```"):
                answer = answer[7:-3].strip()
            elif answer.startswith("```") and answer.endswith("```"):
                answer = answer[3:-3].strip()
            return answer
        except Exception as e:
            attempt += 1
            if log_callback:
                msg = f"  Ollama ошибка (попытка {attempt}/{max_retries}): {e}"
                if change_info:
                    msg += f" [изменение: {change_info}]"
                log_callback(msg, 'error')
            if attempt < max_retries:
                if log_callback:
                    log_callback(f"  Повтор через {retry_delay} секунд...", 'info')
                if stop_event and stop_event.is_set():
                    if log_callback:
                        log_callback("  Запрос отменён во время ожидания повторной попытки", 'warning')
                    return None
                for _ in range(retry_delay):
                    if stop_event and stop_event.is_set():
                        return None
                    time.sleep(1)
                continue
            else:
                retry_cb = _constants._user_retry_callback
                if retry_cb is not None and not (stop_event and stop_event.is_set()):
                    if log_callback:
                        log_callback(f"  Все попытки ({max_retries}) исчерпаны. Запрос к пользователю...", 'warning')
                    user_choice = retry_cb(
                        f"Модель {model} не отвечает после {max_retries} попыток.\n"
                        f"Последняя ошибка: {e}"
                        + (f"\n\nИзменение: {change_info}" if change_info else "")
                        + "\n\nПовторить запрос?"
                    )
                    if user_choice == 'retry':
                        attempt = 0
                        if log_callback:
                            log_callback("  Пользователь выбрал повтор", 'info')
                        continue
                    else:
                        if log_callback:
                            log_callback("  Пользователь остановил процесс", 'warning')
                        if stop_event is not None:
                            stop_event.set()
                        return None
                else:
                    if log_callback:
                        log_callback(f"  Все попытки ({max_retries}) исчерпаны, callback не установлен", 'error')
                    return None
