"""Mixin для файловых операций приложения."""

import os
import sys
import copy
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
import traceback
import json
import time
import json
import time

from npa_processor._bootstrap import _bootstrap_project_root

_bootstrap_project_root()

from npa_processor.constants import (
    settings,
    _ollama_base_url,
    DEFAULT_EXTRA_OPTIONS,
    DEFAULT_OLLAMA_MODEL,
    LAST_PATHS_FILE,
    STAGE_ANSWERS_FILE,
    PROMPT_1,
    PROMPT_2,
    PROMPT_3,
    PROMPT_4,
    TYPE_TO_RUSSIAN,
)
from npa_processor.processing.revision_utils import *
from npa_processor.processing.revision_engine import *
from npa_processor.ui.manual_mapping_dialog import ManualMappingDialog
from npa_processor.ui.source_mapping_dialog import SourceMappingDialog

class FileOpsMixin:
        def _save_result(self, result_data, orig_file, change_data):
            def clean_head_revisions_valid_from(data):
                def clean(item):
                    if 'head_revisions' in item:
                        for rev in item['head_revisions']:
                            rev.pop('valid_from', None)
                    for child in item.get('item_children', []):
                        clean(child)
                for item in data.get('npa_items_revision', []):
                    clean(item)
                if 'head_revision' in data and isinstance(data['head_revision'], list):
                    for rev in data['head_revision']:
                        rev.pop('valid_from', None)
            clean_head_revisions_valid_from(result_data)

            orig_id = result_data.get('npa_id', 'unknown')
            change_id = change_data.get('npa_id', 'unknown')
            date_signed = change_data.get('date_signed', '')
            if date_signed:
                try:
                    dt = datetime.strptime(date_signed, '%d.%m.%Y')
                    date_part = f"{dt.year:04d}_{dt.month:02d}_{dt.day:02d}"
                except:
                    date_part = datetime.now().strftime('%Y_%m_%d')
            else:
                date_part = datetime.now().strftime('%Y_%m_%d')

            orig_npa_number = result_data.get('npa_number', '')
            orig_doc_type = result_data.get('doc_type', result_data.get('npa_type', 'law'))
            orig_clean_num = clean_number_for_filename(orig_npa_number)
            orig_date = get_date_for_filename(result_data, orig_doc_type)

            change_npa_number = change_data.get('npa_number', '')
            change_doc_type = change_data.get('doc_type', change_data.get('npa_type', 'law'))
            change_clean_num = clean_number_for_filename(change_npa_number)
            change_date = get_date_for_filename(change_data, change_doc_type)

            filename = f"{orig_clean_num}_{orig_date}_izm_{change_clean_num}_{change_date}.json"
            out_dir = os.path.dirname(orig_file)
            out_path = os.path.join(out_dir, filename)

            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                    with open(out_path, 'w', encoding='utf-8') as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)
                    self.log(f"Результат сохранён в:\n{out_path}", 'result')
                    return
                except PermissionError as e:
                    self.log(f"Ошибка доступа (попытка {attempt}/{max_attempts}): {e}", 'error')
                    if attempt < max_attempts:
                        self.log("Возможно, файл открыт в другой программе. Закройте его и подождите...", 'warning')
                        time.sleep(1.5)
                    else:
                        answer = messagebox.askyesno(
                            "Не удалось перезаписать файл",
                            f"Не удалось записать файл:\n{out_path}\n\n"
                            f"Причина: {e}\n\n"
                            "Хотите выбрать другой каталог для сохранения?"
                        )
                        if answer:
                            new_dir = filedialog.askdirectory(title="Выберите папку для сохранения")
                            if new_dir:
                                out_path = os.path.join(new_dir, filename)
                                try:
                                    with open(out_path, 'w', encoding='utf-8') as f:
                                        json.dump(result_data, f, ensure_ascii=False, indent=2)
                                    self.log(f"Результат сохранён в:\n{out_path}", 'result')
                                    return
                                except Exception as e2:
                                    self.log(f"Не удалось сохранить даже в выбранную папку: {e2}", 'error')
                                    messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e2}")
                                    return
                        else:
                            self.log("Сохранение отменено пользователем.", 'warning')
                            return
                except Exception as e:
                    self.log(f"Неожиданная ошибка при сохранении (попытка {attempt}/{max_attempts}): {e}", 'error')
                    if attempt == max_attempts:
                        messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{e}")
                    else:
                        time.sleep(0.5)
