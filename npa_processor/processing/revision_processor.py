"""Главный класс приложения для внесения изменений в НПА."""

import os
import sys
import copy
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
import traceback
import re
import json
import requests
from bs4 import BeautifulSoup

from npa_processor._bootstrap import _bootstrap_project_root

_bootstrap_project_root()

import npa_processor.constants as _constants

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
from npa_processor.processing.gui_builder import GuiBuilderMixin
from npa_processor.processing.ai_pipeline import AiPipelineMixin
from npa_processor.processing.file_ops import FileOpsMixin

class App(GuiBuilderMixin, AiPipelineMixin, FileOpsMixin):
        def __init__(self, root):
            self.root = root
            self.root.title("Внесение изменений в НПА в формате JSON на основе другого НПА")
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            self.root.geometry(f"{screen_width}x{screen_height}+0+0")
            self.root.state('zoomed')
            self.left_frame = ttk.Frame(self.root)
            self.right_frame = ttk.Frame(self.root)
            self.left_frame.grid(row=0, column=0, sticky='nsew')
            self.right_frame.grid(row=0, column=1, sticky='nsew')
            self.root.grid_rowconfigure(0, weight=1)
            self.root.grid_columnconfigure(0, weight=1)
            self.root.grid_columnconfigure(1, weight=3)
            self.original_path = tk.StringVar()
            self.change_path = tk.StringVar()
            self.law_ref = tk.StringVar(value="№ 0000-ЗС от 00.00.0000")
            self.original_law_ref = tk.StringVar(value="№ 0000-ЗС")
            self.ollama_model = tk.StringVar(value="minimax-m3:cloud")
            self.extra_options = tk.StringVar(value=json.dumps(DEFAULT_EXTRA_OPTIONS))
            self.pub_date = tk.StringVar()
            self.last_paths = load_json(LAST_PATHS_FILE, {})
            self.prompt_1 = PROMPT_1
            self.prompt_2 = PROMPT_2
            self.prompt_3 = PROMPT_3
            self.prompt_4 = PROMPT_4
            self.elementwise_mode = tk.BooleanVar(value=False)
            self.stage1_answer = tk.StringVar()
            self.stage2_answer = tk.StringVar()
            self.stage3_answer = tk.StringVar()
            self.use_stage1_answer = tk.BooleanVar(value=False)
            self.use_stage2_answer = tk.BooleanVar(value=False)
            self.use_stage3_answer = tk.BooleanVar(value=False)
            self.load_stage_answers()
            self.ollama_models = []
            self.model_params_cache = {}
            self.stop_event = threading.Event()
            self.thread = None
            self.current_dialog = None
            self.manual_mapping_cache = {}
            self.message_queue = queue.Queue()
            self.answer_queue = queue.Queue()
            self.create_widgets()
            self.check_queue()
            threading.Thread(target=self._fetch_ollama_models, daemon=True).start()
            _constants._user_retry_callback = self._ask_user_retry

        def _ask_user_retry(self, error_message):
            event = threading.Event()
            choice = {'value': 'stop'}
            def show_dialog():
                dialog = tk.Toplevel(self.root)
                dialog.title("Ошибка запроса к модели")
                dialog.geometry("500x200")
                dialog.transient(self.root)
                dialog.grab_set()
                msg = tk.Label(dialog, text=error_message, wraplength=450, justify=tk.LEFT)
                msg.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
                btn_frame = tk.Frame(dialog)
                btn_frame.pack(pady=10)
                def on_retry():
                    choice['value'] = 'retry'
                    dialog.destroy()
                    event.set()
                def on_stop():
                    choice['value'] = 'stop'
                    dialog.destroy()
                    event.set()
                tk.Button(btn_frame, text="Повторить", command=on_retry, width=15).pack(side=tk.LEFT, padx=10)
                tk.Button(btn_frame, text="Остановить", command=on_stop, width=15).pack(side=tk.LEFT, padx=10)
                dialog.protocol("WM_DELETE_WINDOW", on_stop)
            self.root.after(0, show_dialog)
            event.wait()
            return choice['value']

        def _fetch_ollama_models(self):
            try:
                import requests
                url = f"{_ollama_base_url}/api/tags"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    models = [m['name'] for m in data.get('models', [])]
                    self.root.after(0, self.log, f"Получено {len(models)} моделей от Ollama", 'info')
                    models.sort()
                    self.ollama_models = models
                    if self.ollama_models:
                        current = self.ollama_model.get()
                        if current not in self.ollama_models:
                            self.root.after(0, lambda: self.ollama_model.set(self.ollama_models[0]))
                    else:
                        self.root.after(0, self.log, "Нет моделей в локальном Ollama. Убедитесь, что сервер запущен.", 'warning')
                else:
                    self.root.after(0, self.log, f"Ошибка загрузки списка моделей: {response.status_code}", 'error')
            except Exception as e:
                self.root.after(0, self.log, f"Ошибка подключения к Ollama: {e}. Убедитесь, что сервер запущен.", 'error')
                self.ollama_models = []

        def fetch_model_parameters(self, model_name):
            try:
                response = requests.post(f"{_ollama_base_url}/api/show", json={"name": model_name}, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    modelfile = data.get("modelfile", "")
                    params = {}
                    for line in modelfile.split("\n"):
                        if line.startswith("PARAMETER"):
                            parts = line.split()
                            if len(parts) >= 3:
                                key = parts[1]
                                value = parts[2]
                                try:
                                    if '.' in value:
                                        value = float(value)
                                    else:
                                        value = int(value)
                                except:
                                    pass
                                params[key] = value
                    model_lower = model_name.lower()
                    if 'deepseek' in model_lower or 'r1' in model_lower:
                        if 'think' not in params:
                            params['think'] = "low"
                    return params
                else:
                    self.log(f"Ошибка получения параметров модели: HTTP {response.status_code}", 'error')
                    return {}
            except requests.exceptions.RequestException as e:
                self.log(f"Не удалось подключиться к Ollama для загрузки параметров: {e}", 'error')
                return {}

        def load_model_params(self):
            model = self.ollama_model.get().strip()
            if not model:
                self.log("Сначала выберите модель", 'warning')
                return
            self.log(f"Загрузка параметров модели {model}...", 'info')
            params = self.fetch_model_parameters(model)
            if params:
                params_json = json.dumps(params, ensure_ascii=False, indent=None)
                self.extra_options.set(params_json)
                self.log(f"Параметры модели загружены: {params_json}", 'result')
            else:
                self.log(f"Не удалось загрузить параметры модели {model}. Поле не изменено.", 'warning')

        def _validate_html_marker(self, html, item_type, item_number, change_info):
            if item_type not in ('point', 'subpoint', 'part'):
                return html, True
            if not item_number:
                return html, True
            expected_marker = str(item_number).strip()
            if expected_marker.endswith(')'):
                expected_marker = expected_marker[:-1]
            soup = BeautifulSoup(html, 'html.parser')
            first_text = soup.get_text(strip=True)
            if not first_text:
                return html, True
            marker_match = re.match(r'^([0-9а-яА-Яё]+)\s*[.)]', first_text)
            if marker_match:
                actual_marker = marker_match.group(1)
                if actual_marker != expected_marker:
                    msg = f"Несоответствие маркера: ожидается '{expected_marker}', фактически '{actual_marker}' для изменения {change_info}"
                    self.log(msg, 'warning')
                    return html, False
            return html, True

        def resolve_ambiguous_element(self, item_type, item_number, candidates, structural_path, revision_number=None, change_info=None, target_element_id=None):
            evt = threading.Event()
            result = {'item_id': None}
            temp_change_data = {'npa_items_revision': candidates}
            display_rev = revision_number if revision_number else structural_path
            def show_dialog():
                try:
                    dialog = SourceMappingDialog(
                        parent=self.root,
                        revision_number=display_rev,
                        change_data=temp_change_data,
                        evt=evt,
                        result_dict=result,
                        type_to_russian=TYPE_TO_RUSSIAN,
                        find_item_by_id_func=find_item_by_id,
                        stop_event=self.stop_event,
                        change_info=change_info,
                        target_element_id=target_element_id,
                        is_ambiguity=True
                    )
                    self.current_dialog = dialog
                except Exception as e:
                    self.log(f"Ошибка при открытии диалога: {e}", 'error')
                    evt.set()
                finally:
                    self.current_dialog = None
            self.root.after(0, show_dialog)
            evt.wait()
            if self.stop_event.is_set():
                self.log(f"  Процесс остановлен, выбор для {item_type} {item_number} отменён", 'warning')
                return None
            if result['item_id']:
                self.log(f"  Выбран элемент {result['item_id']} для {item_type} {item_number}", 'result')
                return result['item_id']
            else:
                self.log(f"  Выбор отменён для {item_type} {item_number}. Изменение будет пропущено.", 'warning')
                return None

        def _extract_parent_for_paragraph(self, structural):
            if 'абзац' not in structural.lower():
                return None, None
            match = re.search(r'(.*?)\s+абзац\s+(\d+|первый|второй|третий|четвертый|пятый|шестой|седьмой|восьмой|девятый|десятый)\s*$', structural, re.IGNORECASE)
            if not match:
                return None, None
            parent_structural = match.group(1).strip()
            para_num_str = match.group(2)
            if para_num_str.isdigit():
                para_num = int(para_num_str)
            else:
                numbers = {
                    'первый': 1, 'второй': 2, 'третий': 3, 'четвертый': 4, 'пятый': 5,
                    'шестой': 6, 'седьмой': 7, 'восьмой': 8, 'девятый': 9, 'десятый': 10
                }
                para_num = numbers.get(para_num_str.lower(), None)
            return parent_structural, para_num

        def resolve_revision_manually(self, revision_number, change_data, log_callback, stop_event=None, change_info=""):
            if stop_event and stop_event.is_set():
                return None
            evt = threading.Event()
            result = {'item_id': None}
            def show_dialog():
                try:
                    if stop_event and stop_event.is_set():
                        evt.set()
                        return
                    dialog = SourceMappingDialog(
                        parent=self.root,
                        revision_number=revision_number,
                        change_data=change_data,
                        evt=evt,
                        result_dict=result,
                        type_to_russian=TYPE_TO_RUSSIAN,
                        find_item_by_id_func=find_item_by_id,
                        stop_event=stop_event,
                        change_info=change_info,
                        is_ambiguity=False
                    )
                    self.current_dialog = dialog
                except Exception as e:
                    log_callback(f"Ошибка при открытии диалога: {e}", 'error')
                    evt.set()
                finally:
                    self.current_dialog = None
            self.root.after(0, show_dialog)
            while not evt.wait(0.1):
                if stop_event and stop_event.is_set():
                    if self.current_dialog:
                        self.root.after(0, self.current_dialog.destroy)
                    return None
            return result['item_id']

        def resolve_target_element_manually(self, change_data, stop_event=None):
            if stop_event and stop_event.is_set():
                return None
            evt = threading.Event()
            result = {'element': None}
            def show_dialog():
                if stop_event and stop_event.is_set():
                    evt.set()
                    return
                dialog = tk.Toplevel(self.root)
                dialog.title("Выбор целевого элемента в изменяющем законе")
                dialog.geometry("600x500")
                dialog.transient(self.root)
                dialog.grab_set()
                tree = ttk.Treeview(dialog, columns=("id", "type", "number"), show="tree headings")
                tree.heading("#0", text="Путь")
                tree.heading("id", text="ID")
                tree.heading("type", text="Тип")
                tree.heading("number", text="Номер")
                tree.column("#0", width=300)
                tree.column("id", width=150)
                tree.column("type", width=100)
                tree.column("number", width=100)
                scroll_y = ttk.Scrollbar(dialog, orient="vertical", command=tree.yview)
                scroll_x = ttk.Scrollbar(dialog, orient="horizontal", command=tree.xview)
                tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
                tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
                scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
                scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
                def add_items(parent_item, items, path=""):
                    for item in items:
                        item_id = item.get('item_id', '')
                        item_type = item.get('item_type', '')
                        item_number = item.get('item_number', '')
                        type_rus = TYPE_TO_RUSSIAN.get(item_type, item_type)
                        node_name = f"{type_rus} {item_number}" if item_number else type_rus
                        full_path = f"{path}/{node_name}" if path else node_name
                        node = tree.insert(parent_item, "end", text=full_path, values=(item_id, type_rus, item_number))
                        add_items(node, item.get('item_children', []), full_path)
                root_items = change_data.get('npa_items_revision', [])
                add_items("", root_items)
                btn_frame = tk.Frame(dialog)
                btn_frame.pack(fill=tk.X, pady=10)
                def on_ok():
                    selected = tree.selection()
                    if not selected:
                        messagebox.showwarning("Выбор", "Пожалуйста, выберите элемент.")
                        return
                    item = tree.item(selected[0])
                    item_id = item['values'][0]
                    result['element'] = find_item_by_id(change_data, item_id)
                    evt.set()
                    dialog.destroy()
                def on_cancel():
                    result['element'] = None
                    evt.set()
                    dialog.destroy()
                tk.Button(btn_frame, text="Выбрать", command=on_ok, width=15).pack(side=tk.LEFT, padx=10)
                tk.Button(btn_frame, text="Отмена", command=on_cancel, width=15).pack(side=tk.LEFT, padx=10)
                dialog.protocol("WM_DELETE_WINDOW", on_cancel)
            self.root.after(0, show_dialog)
            while not evt.wait(0.1):
                if stop_event and stop_event.is_set():
                    if 'dialog' in locals() and dialog.winfo_exists():
                        dialog.destroy()
                    return None
            return result['element']

        def load_stage_answers(self):
            data = load_json(STAGE_ANSWERS_FILE, {})
            self.stage1_answer.set(data.get('stage1_answer', ''))
            self.stage2_answer.set(data.get('stage2_answer', ''))
            self.stage3_answer.set(data.get('stage3_answer', ''))
            self.use_stage1_answer.set(data.get('use_stage1_answer', False))
            self.use_stage2_answer.set(data.get('use_stage2_answer', False))
            self.use_stage3_answer.set(data.get('use_stage3_answer', False))

        def _normalize_text(self, text):
            if not text:
                return ""
            text = safe_re_sub(r'<[^>]+>', '', text)
            text = ' '.join(text.split())
            text = text.lower()
            text = safe_re_sub(r'[^\w\s]', '', text)
            return text

        def _extract_paragraphs_from_html(self, html):
            from bs4 import BeautifulSoup
            if not html:
                return []
            soup = BeautifulSoup(html, 'html.parser')
            paragraphs = []
            for p in soup.find_all('p'):
                html_str = str(p)
                text = p.get_text(' ', strip=True)
                if text.strip():
                    normalized = self._normalize_text(text)
                    paragraphs.append({'html': html_str, 'normalized': normalized})
            return paragraphs

        def _split_ai_answer_into_paragraphs(self, ai_answer_text):
            if not ai_answer_text:
                return []
            from bs4 import BeautifulSoup
            import re
            soup = BeautifulSoup(ai_answer_text, 'html.parser')
            paragraphs = soup.find_all('p')
            if paragraphs:
                return [p.decode_contents().strip() for p in paragraphs if p.get_text(strip=True)]
            blocks = re.split(r'\n\s*\n', ai_answer_text)
            result = []
            for block in blocks:
                block = block.strip()
                if block:
                    result.append(block)
            return result

        def _assemble_html_from_ai_answer(self, source_element, ai_answer_text, log_callback):
            if not ai_answer_text:
                return None
            ai_answer_text = extract_html_from_json_response(ai_answer_text, log_callback)
            full_html = get_full_element_html(source_element, use_original_structure=False)
            if not full_html:
                if log_callback:
                    log_callback(f"  Не удалось получить HTML для элемента {source_element.get('item_id')}", 'error')
                return None
            soup = BeautifulSoup(full_html, 'html.parser')
            paragraphs = soup.find_all(['p', 'div', 'li'])
            if not paragraphs:
                if log_callback:
                    log_callback(f"  В исходном элементе {source_element.get('item_id')} нет абзацев", 'error')
                return None
            source_paragraphs = []
            for p in paragraphs:
                html_str = str(p)
                clean_text = get_clean_text_from_block({'html_text': html_str})
                source_paragraphs.append({'html': html_str, 'clean': clean_text})
            ai_paragraphs = self._split_ai_answer_into_paragraphs(ai_answer_text)
            if not ai_paragraphs:
                if log_callback:
                    log_callback(f"  Ответ ИИ не содержит текста, используем как есть", 'warning')
                    return ai_answer_text
            n = len(ai_paragraphs)
            src_count = len(source_paragraphs)
            if log_callback:
                log_callback(f"  Абзацев ИИ: {n}, абзацев в источнике: {src_count}", 'debug')
            if n > src_count:
                if log_callback:
                    log_callback(f"  Абзацев ИИ ({n}) больше, чем абзацев в источнике ({src_count})", 'error')
                return None
            start_idx = -1
            for i, p in enumerate(source_paragraphs):
                clean = p['clean'].lstrip()
                if clean.startswith('«'):
                    start_idx = i
                    if log_callback:
                        preview = clean[:50].replace('\n', ' ')
                        log_callback(f"  Найден начальный абзац с '«' на позиции {i+1}: '{preview}...'", 'debug')
                    break
            if start_idx == -1:
                if log_callback:
                    log_callback(f"  Не найден абзац, начинающийся с '«' в элементе-источнике", 'error')
                return None
            if start_idx + n > src_count:
                if log_callback:
                    log_callback(f"  Не хватает абзацев: нужно {n}, доступно {src_count - start_idx}. Возьмём сколько есть.", 'warning')
                n = src_count - start_idx
                if n <= 0:
                    return None
            result_paragraphs = []
            for k in range(n):
                original_html = source_paragraphs[start_idx + k]['html']
                soup_p = BeautifulSoup(original_html, 'html.parser')
                tag = soup_p.find()
                if tag:
                    tag.clear()
                    tag.append(BeautifulSoup(ai_paragraphs[k], 'html.parser'))
                    result_paragraphs.append(str(tag))
                else:
                    result_paragraphs.append(f"<p>{ai_paragraphs[k]}</p>")
            if log_callback:
                log_callback(f"  Взяты абзацы {start_idx+1}–{start_idx+n} (всего {n})", 'result')
            return '\n'.join(result_paragraphs)

        def resolve_change_manually(self, change, original_data, stop_event=None):
            if stop_event and stop_event.is_set():
                self.log(f"resolve_change_manually: процесс остановлен, диалог не открывается", 'warning')
                return None, None, None, None
            evt = threading.Event()
            result = {'target_id': None, 'structural': None, 'description': None, 'type': None}
            is_title_change = change.get('structural_element', '').lower().startswith('наименование')
            def show_dialog():
                try:
                    if stop_event and stop_event.is_set():
                        evt.set()
                        return
                    dialog = ManualMappingDialog(
                        parent=self.root,
                        change=change,
                        original_data=original_data,
                        evt=evt,
                        result_dict=result,
                        is_title_change=is_title_change,
                        type_to_russian=TYPE_TO_RUSSIAN,
                        find_item_by_id_func=find_item_by_id,
                        stop_event=stop_event
                    )
                    self.current_dialog = dialog
                    self.root.wait_window(dialog.window)
                except Exception as e:
                    self.log(f"Ошибка при открытии диалога: {e}", 'error')
                    evt.set()
                finally:
                    self.current_dialog = None
            self.root.after(0, show_dialog)
            while not evt.wait(0.1):
                if stop_event and stop_event.is_set():
                    if self.current_dialog:
                        self.root.after(0, self.current_dialog.destroy)
                    return None, None, None, None

            if result['target_id'] is not None:
                change['_resolved_item_id'] = result['target_id']
                if result['structural']:
                    change['structural_element'] = result['structural']
                if result['description'] is not None:
                    change['description'] = result['description']
                if result['type'] is not None:
                    change['type'] = result['type']
                self.log(f"  → Установлен _resolved_item_id = {result['target_id']}", 'result')
            else:
                self.log("  → Пользователь отменил выбор", 'warning')

            return (result['target_id'], result['structural'], result['description'], result['type'])

        def check_queue(self):
            try:
                while True:
                    msg = self.message_queue.get_nowait()
                    self.process_message(msg)
            except queue.Empty:
                pass
            finally:
                self.root.after(100, self.check_queue)

        def _copy_to_clipboard(self, text):
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            messagebox.showinfo("Скопировано", "HTML скопирован в буфер обмена")

        def _show_full_html(self, html):
            if not html:
                messagebox.showinfo("Информация", "HTML отсутствует")
                return
            win = tk.Toplevel(self.root)
            win.title("Полный HTML")
            win.geometry("800x600")
            win.transient(self.root)
            frame = ttk.Frame(win, padding="10")
            frame.pack(fill=tk.BOTH, expand=True)
            text_widget = tk.Text(frame, wrap=tk.WORD, font=("Consolas", 9))
            scrollbar = ttk.Scrollbar(frame, command=text_widget.yview)
            text_widget.config(yscrollcommand=scrollbar.set)
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            text_widget.insert('1.0', html)
            text_widget.config(state=tk.DISABLED)
            btn_frame = ttk.Frame(win)
            btn_frame.pack(pady=5)
            ttk.Button(btn_frame, text="Копировать", command=lambda: self._copy_to_clipboard(html)).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="Закрыть", command=win.destroy).pack(side=tk.LEFT, padx=5)

        def process_message(self, msg):
            try:
                while True:
                    msg = self.message_queue.get_nowait()
                    if isinstance(msg, dict) and msg.get('type') == 'question_appendix_title':
                        appendix_title = msg.get('appendix_title', '')
                        question_id = msg.get('question_id')
                        has_title = self.ask_appendix_title_confirmation(appendix_title)
                        if self.answer_queue:
                            self.answer_queue.put({'question_id': question_id, 'has_title': has_title})
                    elif isinstance(msg, dict) and msg.get('type') == 'question':
                        candidate_text = msg.get('candidate_text', '')
                        adjacent_text = msg.get('adjacent_text', '')
                        question_id = msg.get('question_id')
                        change_info = msg.get('change_info', '')
                        target_element_id = msg.get('target_element_id', '')
                        source_revision = msg.get('source_revision', '')
                        full_html = msg.get('full_html', '')
                        dialog = tk.Toplevel(self.root)
                        dialog.title("Неоднозначная структура")
                        dialog.geometry("700x600")
                        dialog.transient(self.root)
                        dialog.grab_set()
                        dialog.lift()
                        dialog.focus_force()
                        frame = ttk.Frame(dialog, padding="10")
                        frame.pack(fill=tk.BOTH, expand=True)
                        ttk.Label(frame, text="Парсер не может определить иерархию:").pack(anchor=tk.W, pady=(0,5))
                        info_text = (
                            f"Изменение: {change_info if change_info else 'не указано'}\n"
                            f"Целевой элемент: {target_element_id if target_element_id else 'не указан'}\n"
                            f"Источник: revision_number = {source_revision if source_revision else 'не указан'}"
                        )
                        ttk.Label(frame, text=info_text, wraplength=650, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
                        ttk.Label(frame, text=f"Предыдущий элемент: {adjacent_text[:100] if adjacent_text else '(пусто)'}", wraplength=650).pack(anchor=tk.W, pady=2)
                        ttk.Label(frame, text=f"Текущий элемент: {candidate_text[:100] if candidate_text else '(пусто)'}", wraplength=650).pack(anchor=tk.W, pady=2)
                        html_frame = ttk.Frame(frame)
                        html_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                        show_html_var = tk.BooleanVar(value=False)
                        def toggle_html():
                            if show_html_var.get():
                                html_text_widget.pack_forget()
                                show_html_btn.config(text="Показать полный HTML")
                                show_html_var.set(False)
                            else:
                                html_text_widget.pack(fill=tk.BOTH, expand=True, pady=5)
                                show_html_btn.config(text="Скрыть полный HTML")
                                show_html_var.set(True)
                            dialog.update()
                        show_html_btn = ttk.Button(html_frame, text="Показать полный HTML", command=toggle_html)
                        show_html_btn.pack(anchor=tk.W, pady=2)
                        html_text_widget = tk.Text(html_frame, wrap=tk.WORD, height=10, font=("Consolas", 9))
                        html_text_widget.insert('1.0', full_html if full_html else "(HTML отсутствует)")
                        html_text_widget.config(state=tk.DISABLED)
                        ttk.Label(frame, text="Должен ли текущий элемент быть дочерним по отношению к предыдущему или находиться на том же уровне?").pack(pady=10)
                        result = tk.StringVar()
                        def set_child():
                            result.set('child')
                            dialog.destroy()
                        def set_sibling():
                            result.set('sibling')
                            dialog.destroy()
                        def set_skip():
                            result.set('skip')
                            dialog.destroy()
                        def set_edit():
                            edit_dialog = tk.Toplevel(dialog)
                            edit_dialog.title("Редактирование HTML")
                            edit_dialog.geometry("600x400")
                            edit_dialog.transient(dialog)
                            edit_dialog.grab_set()
                            text_widget = tk.Text(edit_dialog, wrap=tk.WORD)
                            text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                            text_widget.insert('1.0', full_html if full_html else "")
                            def save_edit():
                                new_html = text_widget.get('1.0', tk.END).strip()
                                result.set('edit')
                                result.new_html = new_html
                                edit_dialog.destroy()
                                dialog.destroy()
                            ttk.Button(edit_dialog, text="Сохранить и применить", command=save_edit).pack(pady=5)
                            ttk.Button(edit_dialog, text="Отмена", command=edit_dialog.destroy).pack(pady=5)
                        btn_frame = ttk.Frame(frame)
                        btn_frame.pack(pady=10)
                        ttk.Button(btn_frame, text="Дочерний", command=set_child).pack(side=tk.LEFT, padx=5)
                        ttk.Button(btn_frame, text="Тот же уровень", command=set_sibling).pack(side=tk.LEFT, padx=5)
                        ttk.Button(btn_frame, text="Пропустить", command=set_skip).pack(side=tk.LEFT, padx=5)
                        ttk.Button(btn_frame, text="Исправить HTML", command=set_edit).pack(side=tk.LEFT, padx=5)
                        dialog.protocol("WM_DELETE_WINDOW", set_skip)
                        self.root.wait_window(dialog)
                        relation = result.get()
                        if relation == 'edit' and hasattr(result, 'new_html'):
                            if self.answer_queue:
                                self.answer_queue.put({'question_id': question_id, 'relation': 'edit', 'new_html': result.new_html})
                        elif relation:
                            if self.answer_queue:
                                self.answer_queue.put({'question_id': question_id, 'relation': relation})
                    elif isinstance(msg, tuple) and len(msg) >= 3:
                        _, text, level = msg
                        self.log(text, level)
                    else:
                        msg_type = msg.get('type') if isinstance(msg, dict) else None
                        if msg_type == 'status':
                            self.status_var.set(msg.get('text', ''))
                            self.log(msg.get('text', ''))
                        elif msg_type == 'log':
                            self.log(msg.get('text', ''), msg.get('level', 'INFO'))
                        elif msg_type == 'done':
                            self.processing_done(msg.get('success', False))
                        elif msg_type == 'load_complete':
                            self.load_resources_complete(msg.get('resources'), msg.get('error'))
                        elif msg_type == 'error':
                            self.log(msg.get('text', ''), 'ERROR')
                            self.status_var.set("Ошибка")
            except queue.Empty:
                pass

        def ask_appendix_title_confirmation(self, appendix_title):
            return messagebox.askyesno(
                "Подтверждение заголовка приложения",
                f"Найден заголовок приложения:\n\n{appendix_title}\n\nСчитать этот текст заголовком приложения?"
            )

        def ask_ambiguity(self, candidate_text, adjacent_text):
            dialog = tk.Toplevel(self.root)
            dialog.title("Неоднозначная структура")
            dialog.geometry("600x250")
            dialog.transient(self.root)
            dialog.grab_set()
            ttk.Label(dialog, text="Парсер не может определить иерархию:").pack(pady=5)
            ttk.Label(dialog, text=f"Предыдущий элемент: {adjacent_text[:100]}", wraplength=550).pack(pady=2)
            ttk.Label(dialog, text=f"Текущий элемент: {candidate_text[:100]}", wraplength=550).pack(pady=2)
            ttk.Label(dialog, text="Должен ли текущий элемент быть дочерним по отношению к предыдущему или находиться на том же уровне?").pack(pady=10)
            result = tk.StringVar()
            def set_child():
                result.set('child')
                dialog.destroy()
            def set_sibling():
                result.set('sibling')
                dialog.destroy()
            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=10)
            ttk.Button(btn_frame, text="Дочерний (увеличить отступ)", command=set_child).pack(side=tk.LEFT, padx=10)
            ttk.Button(btn_frame, text="Тот же уровень", command=set_sibling).pack(side=tk.LEFT, padx=10)
            dialog.protocol("WM_DELETE_WINDOW", set_sibling)
            self.root.wait_window(dialog)
            return result.get() or 'sibling'

        def processing_done(self, success):
            self.run_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)
            if success:
                self.status_var.set("Обработка завершена успешно")
                self.log("Обработка завершена успешно")
            else:
                self.status_var.set("Обработка завершена с ошибками")
                self.log("Обработка завершена с ошибками", 'WARNING')

        def load_resources_complete(self, resources, error):
            self.is_loading_resources = False
            self.load_button.config(state=tk.NORMAL)
            self.status_var.set("Готов к работе")
            if error:
                self.log(f"Ошибка при загрузке списка ресурсов: {error}", 'ERROR')
                return
            if resources is not None:
                self.all_resources = resources
                years = sorted(set([r['year'] for r in self.all_resources if r['year']]), reverse=True)
                self.year_filter['values'] = ["Все"] + years
                self.display_resources()
                self.log(f"Загружено {len(resources)} ресурсов")

        def cancel(self):
            self.stop_event.set()
            self.cancel_btn.config(state='disabled')
            if self.current_dialog:
                self.root.after(0, self.current_dialog.destroy)
                self.current_dialog = None
            self.log("Отмена запрошена...", 'warning')

def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
