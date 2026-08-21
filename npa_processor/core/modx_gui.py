"""Графический интерфейс для формирования структуры JSON из ресурсов MODX.

Содержит класс MODXProcessorGUI для браузинга ресурсов,
очереди обработки и локального сохранения результатов.
"""

import sys
import os
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, Listbox, MULTIPLE, END, filedialog
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import re
import urllib.request
import json

from npa_processor.core.modx_processor import MODXHTMLProcessor
from npa_processor.core.html_parser import NpaToJsonGenerator

class MODXProcessorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Формирование структуры JSON")
        self.root.geometry("1300x800")
        self.message_queue = queue.Queue()
        self.processor = MODXHTMLProcessor(log_queue=self.message_queue)
        self.processing_thread = None
        self.stop_event = threading.Event()
        self.all_resources = []
        self.selected_resource_ids = []
        self.is_loading_resources = False
        self.save_locally_var = tk.IntVar(value=1)
        self.local_save_dir = None
        self.answer_queue = None
        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        log_file = 'modx_processor.log'
        handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        handler.setFormatter(log_formatter)
        self.logger = logging.getLogger('MODXProcessor')
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(handler)
        self.setup_ui()
        self.check_queue()

    @staticmethod
    def _remove_empty(data):
        if isinstance(data, dict):
            new_dict = {}
            for key, value in data.items():
                cleaned = MODXProcessorGUI._remove_empty(value)
                if cleaned not in (None, '', [], {}):
                    new_dict[key] = cleaned
            return new_dict if new_dict else None
        elif isinstance(data, list):
            new_list = []
            for item in data:
                cleaned = MODXProcessorGUI._remove_empty(item)
                if cleaned not in (None, '', [], {}):
                    new_list.append(cleaned)
            return new_list if new_list else None
        else:
            return data

    def _normalize_text(self, text):
        if not text:
            return ""
        text = text.replace('\u00A0', ' ').replace('&nbsp;', ' ')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _normalize_signer_name(self, name):
        if not name:
            return ""
        name = self._normalize_text(name)
        name = re.sub(r'([А-Я]\.)\s+([А-Я]\.)', r'\1\2', name, flags=re.IGNORECASE)
        pattern = r'^([А-Я]\.(?:[А-Я]\.)?)([А-Я][а-яё]+(?:-[А-Я][а-яё]+)?)$'
        match = re.match(pattern, name, re.IGNORECASE)
        if match:
            initials = match.group(1)
            surname = match.group(2)
            if not initials.endswith('.'):
                initials += '.'
            name = f"{initials} {surname}"
        else:
            name = re.sub(r'\s+', ' ', name)
        return name

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

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Дочерний (увеличить отступ)", command=set_child).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Тот же уровень", command=set_sibling).pack(side=tk.LEFT, padx=10)

        dialog.protocol("WM_DELETE_WINDOW", set_sibling)
        self.root.wait_window(dialog)
        return result.get() or 'sibling'

    def ask_appendix_title_confirmation(self, appendix_title):
        msg = f"Найден заголовок приложения:\n\n{appendix_title}\n\nСчитать этот текст заголовком приложения?"
        return messagebox.askyesno("Подтверждение заголовка приложения", msg)

    def setup_ui(self):
        main_container = ttk.Frame(self.root, padding="5")
        main_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        control_frame = ttk.LabelFrame(main_container, text="Управление", padding="5")
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        load_filter_frame = ttk.Frame(control_frame)
        load_filter_frame.grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        ttk.Label(load_filter_frame, text="Фильтры для загрузки списка:").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(load_filter_frame, text="№ Закона:").pack(side=tk.LEFT, padx=(0, 5))
        self.law_num_filter_entry = ttk.Entry(load_filter_frame, width=12)
        self.law_num_filter_entry.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(load_filter_frame, text="№ Постановления:").pack(side=tk.LEFT, padx=(0, 5))
        self.resolution_num_filter_entry = ttk.Entry(load_filter_frame, width=12)
        self.resolution_num_filter_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.load_button = ttk.Button(load_filter_frame, text="Загрузить список", command=self.load_resources_list, width=18)
        self.load_button.pack(side=tk.LEFT)
        process_frame = ttk.Frame(control_frame)
        process_frame.grid(row=1, column=0, sticky=tk.W, pady=(0, 5))
        self.start_button = ttk.Button(process_frame, text="Обработать выбранные", command=self.start_processing_selected, width=25)
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        self.stop_button = ttk.Button(process_frame, text="Остановить", command=self.stop_processing, state=tk.DISABLED, width=15)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 10))
        self.local_save_check = ttk.Checkbutton(process_frame, text="Сохранять JSON локально (вместо загрузки на сервер)", variable=self.save_locally_var)
        self.local_save_check.pack(side=tk.LEFT, padx=(10, 0))
        status_frame = ttk.Frame(control_frame)
        status_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        self.status_var = tk.StringVar(value="Готов к работе")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)
        manual_frame = ttk.Frame(control_frame)
        manual_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        ttk.Label(manual_frame, text="ID ресурсов (через запятую):").pack(side=tk.LEFT, padx=(0, 5))
        self.manual_ids_entry = ttk.Entry(manual_frame, width=40)
        self.manual_ids_entry.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(manual_frame, text="Кастомный ID:").pack(side=tk.LEFT, padx=(10, 2))
        self.custom_id_entry = ttk.Entry(manual_frame, width=20)
        self.custom_id_entry.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(manual_frame, text="Обработать по ID", command=self.start_processing_manual, width=18).pack(side=tk.LEFT)
        resources_frame = ttk.LabelFrame(main_container, text="Список ресурсов", padding="5")
        resources_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))
        filter_frame = ttk.Frame(resources_frame)
        filter_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(filter_frame, text="Год:").pack(side=tk.LEFT, padx=(0, 2))
        self.year_filter = ttk.Combobox(filter_frame, values=[], state="readonly", width=8)
        self.year_filter.pack(side=tk.LEFT, padx=(0, 8))
        self.year_filter.bind('<<ComboboxSelected>>', self.filter_resources)
        ttk.Label(filter_frame, text="Тип:").pack(side=tk.LEFT, padx=(0, 2))
        self.type_filter = ttk.Combobox(filter_frame, values=["Все", "Законы", "Постановления"], state="readonly", width=12)
        self.type_filter.set("Все")
        self.type_filter.pack(side=tk.LEFT, padx=(0, 10))
        self.type_filter.bind('<<ComboboxSelected>>', self.filter_resources)
        ttk.Button(filter_frame, text="Сбросить", command=self.reset_filters, width=10).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(filter_frame, text="Выбрать все", command=self.select_all_resources, width=14).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(filter_frame, text="Снять выделение", command=self.deselect_all_resources, width=16).pack(side=tk.LEFT)
        list_frame = ttk.Frame(resources_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.resources_listbox = Listbox(list_frame, selectmode=MULTIPLE, width=140, height=8)
        scrollbar = ttk.Scrollbar(list_frame, command=self.resources_listbox.yview)
        self.resources_listbox.config(yscrollcommand=scrollbar.set)
        self.resources_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        log_frame = ttk.LabelFrame(main_container, text="Лог", padding="5")
        log_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 0))
        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_text_frame, height=10, width=140, wrap=tk.WORD)
        scroll_log = ttk.Scrollbar(log_text_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scroll_log.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_log.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.bind("<Control-KeyPress>", self.copy_log_selection)
        self.log_text.bind("<Button-3>", self.show_log_context_menu)
        self.log_text.bind("<Control-c>", self.copy_log_selection)
        self.log_text.bind("<Control-C>", self.copy_log_selection)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(4, weight=1)
        main_container.rowconfigure(5, weight=1)

    def copy_log_selection(self, event=None):
        try:
            selected_text = self.log_text.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
            return "break"
        except tk.TclError:
            return None

    def show_log_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Копировать", command=self.copy_log_selection)
        menu.post(event.x_root, event.y_root)

    def log_message(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if level == "ERROR":
            self.log_text.insert(tk.END, f"[{timestamp}] ERROR: {message}\n", "error")
            self.log_text.tag_config("error", foreground="red")
        elif level == "WARNING":
            self.log_text.insert(tk.END, f"[{timestamp}] WARNING: {message}\n", "warning")
            self.log_text.tag_config("warning", foreground="orange")
        elif level == "DEBUG":
            self.log_text.insert(tk.END, f"[{timestamp}] DEBUG: {message}\n", "debug")
            self.log_text.tag_config("debug", foreground="gray")
        else:
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def display_resources(self, resources=None):
        if resources is None:
            resources = self.all_resources
        self.resources_listbox.delete(0, END)
        seen_ids = set()
        for res in resources:
            if res['id'] in seen_ids:
                continue
            seen_ids.add(res['id'])
            year_display = res['year'] or "без года"
            doc_type_display = "Закон" if res['doc_type'] == 'law' else "Постановление"
            display_text = f"{doc_type_display} № {res['z_num']} ({year_display}) [ID: {res['id']}]"
            self.resources_listbox.insert(END, display_text)

    def filter_resources(self, event=None):
        year_filter = self.year_filter.get()
        type_filter = self.type_filter.get()
        filtered_resources = self.all_resources
        if year_filter and year_filter != "Все":
            filtered_resources = [r for r in filtered_resources if r['year'] == year_filter]
        if type_filter and type_filter != "Все":
            if type_filter == "Законы":
                filtered_resources = [r for r in filtered_resources if r['doc_type'] == 'law']
            elif type_filter == "Постановления":
                filtered_resources = [r for r in filtered_resources if r['doc_type'] == 'regulation']
        self.display_resources(filtered_resources)

    def reset_filters(self):
        self.year_filter.set("")
        self.type_filter.set("Все")
        self.display_resources()

    def select_all_resources(self):
        self.resources_listbox.select_set(0, END)

    def deselect_all_resources(self):
        self.resources_listbox.selection_clear(0, END)

    def get_selected_resource_ids(self):
        selected_indices = self.resources_listbox.curselection()
        selected_ids = []
        for index in selected_indices:
            item_text = self.resources_listbox.get(index)
            match = re.search(r'\[ID: (\d+)\]', item_text)
            if match:
                resource_id = int(match.group(1))
                selected_ids.append(resource_id)
        return selected_ids

    def get_manual_resource_ids(self):
        ids_text = self.manual_ids_entry.get().strip()
        if not ids_text:
            return []
        ids = []
        for id_str in ids_text.split(','):
            id_str = id_str.strip()
            if id_str:
                try:
                    resource_id = int(id_str)
                    ids.append(resource_id)
                except ValueError:
                    self.log_message(f"Некорректный ID: {id_str}", "ERROR")
        return ids

    def check_queue(self):
        try:
            while True:
                message = self.message_queue.get_nowait()
                self.process_message(message)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_queue)

    def process_message(self, message):
        if isinstance(message, tuple) and len(message) >= 3:
            _, text, level = message
            self.log_message(text, level)
            return
        if isinstance(message, dict) and message.get('type') == 'question':
            candidate_text = message.get('candidate_text', '')
            adjacent_text = message.get('adjacent_text', '')
            question_id = message.get('question_id')
            relation = self.ask_ambiguity(candidate_text, adjacent_text)
            if self.answer_queue:
                self.answer_queue.put({'question_id': question_id, 'relation': relation})
            return
        if isinstance(message, dict) and message.get('type') == 'question_appendix_title':
            appendix_title = message.get('appendix_title', '')
            question_id = message.get('question_id')
            has_title = self.ask_appendix_title_confirmation(appendix_title)
            if self.answer_queue:
                self.answer_queue.put({'question_id': question_id, 'has_title': has_title})
            return
        msg_type = message.get('type')
        if msg_type == 'status':
            self.status_var.set(message['text'])
            self.log_message(message['text'])
        elif msg_type == 'log':
            self.log_message(message['text'], message.get('level', 'INFO'))
        elif msg_type == 'done':
            self.processing_done(message.get('success', False))
        elif msg_type == 'load_complete':
            self.load_resources_complete(message.get('resources'), message.get('error'))
        elif msg_type == 'error':
            self.log_message(message['text'], "ERROR")
            self.status_var.set("Ошибка")

    def processing_done(self, success):
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        if success:
            self.status_var.set("Обработка завершена успешно")
            self.log_message("Обработка завершена успешно")
        else:
            self.status_var.set("Обработка завершена с ошибками")
            self.log_message("Обработка завершена с ошибками", "WARNING")

    def load_resources_complete(self, resources, error):
        self.is_loading_resources = False
        self.load_button.config(state=tk.NORMAL)
        self.status_var.set("Готов к работе")
        if error:
            self.log_message(f"Ошибка при загрузке списка ресурсов: {error}", "ERROR")
            return
        if resources is not None:
            self.all_resources = resources
            years = sorted(set([r['year'] for r in self.all_resources if r['year']]), reverse=True)
            self.year_filter['values'] = ["Все"] + years
            self.display_resources()
            self.log_message(f"Загружено {len(resources)} ресурсов")

    def start_processing_selected(self):
        self.selected_resource_ids = self.get_selected_resource_ids()
        if not self.selected_resource_ids:
            self.log_message("Выберите ресурсы для обработки", "WARNING")
            return
        self.start_processing_with_ids(self.selected_resource_ids)

    def start_processing_manual(self):
        manual_ids = self.get_manual_resource_ids()
        if not manual_ids:
            self.log_message("Введите ID ресурсов для обработки", "WARNING")
            return
        custom_id = self.custom_id_entry.get().strip()
        if custom_id and len(manual_ids) > 1:
            self.log_message("Кастомный ID применяется только при обработке одного ресурса. Игнорирую.", "WARNING")
            custom_id = None
        self.start_processing_with_ids(manual_ids, custom_id)

    def start_processing_with_ids(self, resource_ids, custom_id=None):
        if self.save_locally_var.get() == 1 and not self.local_save_dir:
            self.local_save_dir = filedialog.askdirectory(title="Выберите папку для сохранения JSON-файлов")
            if not self.local_save_dir:
                self.log_message("Локальное сохранение отменено пользователем", "WARNING")
                return
        self.log_text.delete(1.0, tk.END)
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.stop_event.clear()
        self.answer_queue = queue.Queue()
        self.processing_thread = threading.Thread(
            target=self.process_resources,
            args=(resource_ids, custom_id),
            daemon=True
        )
        self.processing_thread.start()
        self.log_message(f"Начата обработка {len(resource_ids)} ресурсов")

    def stop_processing(self):
        self.stop_event.set()
        self.status_var.set("Остановка...")
        self.log_message("Остановка обработки по запросу пользователя", "WARNING")
        if hasattr(self, 'processor') and self.processor:
            try:
                if self.processor.sftp:
                    self.processor.sftp.close()
                if self.processor.ssh:
                    self.processor.ssh.close()
                self.processor.close_db_pool()
                self.processor.clear_cache()
            except:
                pass
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def process_resources(self, resource_ids, custom_id=None):
        try:
            total_resources = len(resource_ids)
            self.message_queue.put({
                'type': 'status',
                'text': f"Начинаю обработку {total_resources} ресурсов..."
            })
            if not self.save_locally_var.get():
                try:
                    if not self.processor.connect_ssh():
                        self.message_queue.put({
                            'type': 'error',
                            'text': "Не удалось подключиться к SSH"
                        })
                        return False
                except Exception as e:
                    self.message_queue.put({
                        'type': 'error',
                        'text': f"Ошибка SSH подключения: {e}"
                    })
                    return False
            success_count = 0
            error_count = 0
            for resource_id in resource_ids:
                if self.stop_event.is_set():
                    self.message_queue.put({
                        'type': 'status',
                        'text': "Обработка прервана пользователем"
                    })
                    break
                try:
                    success = self.process_single_resource(resource_id, custom_id)
                    if success:
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    error_count += 1
                    self.message_queue.put({
                        'type': 'log',
                        'text': f"Критическая ошибка при обработке ресурса {resource_id}: {e}",
                        'level': 'ERROR'
                    })
                    self.logger.error(f"Critical error processing resource {resource_id}: {str(e)}")
            self.message_queue.put({
                'type': 'status',
                'text': f"Обработка завершена. Успешно: {success_count}, Ошибок: {error_count}"
            })
            if not self.save_locally_var.get():
                if self.processor.sftp:
                    self.processor.sftp.close()
                if self.processor.ssh:
                    self.processor.ssh.close()
            self.message_queue.put({
                'type': 'done',
                'success': error_count == 0
            })
            return True
        except Exception as e:
            self.message_queue.put({
                'type': 'error',
                'text': f"Непредвиденная ошибка: {e}"
            })
            self.message_queue.put({
                'type': 'done',
                'success': False
            })
            self.logger.error(f"Unexpected error in process_resources: {str(e)}")
            return False

    def format_date(self, date_str):
        if not date_str:
            return ""
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
        if match:
            return f"{match.group(3)}.{match.group(2)}.{match.group(1)}"
        match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
        if match:
            return date_str
        match = re.search(r'(\d{2})-(\d{2})-(\d{4})', date_str)
        if match:
            return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
        return ""

    def process_single_resource(self, resource_id, custom_id=None):
        generator = None
        try:
            if self.stop_event.is_set():
                return False
            resource_data = self.processor.get_resource_basic_cached(resource_id)
            if self.stop_event.is_set():
                return False
            if not resource_data:
                self.message_queue.put({
                    'type': 'log',
                    'text': f"Ресурс {resource_id} не найден в БД",
                    'level': 'ERROR'
                })
                self.logger.error(f"Resource {resource_id} not found in database")
                return False
            template = resource_data['template']
            parent_id = resource_data['parent']
            content_html = resource_data['content']
            longtitle = resource_data.get('longtitle', '')
            url_id = custom_id if custom_id else resource_id
            final_url = f"https://sevzakon.ru/index.php?id={url_id}"
            try:
                req = urllib.request.Request(final_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    final_url = response.geturl()
            except Exception as e:
                self.message_queue.put({
                    'type': 'log',
                    'text': f"Не удалось получить финальный URL для ресурса {resource_id}: {e}",
                    'level': 'WARNING'
                })
            npa_url = final_url
            if template == 12:
                resource_with_params = self.processor.get_resource_with_params_cached(resource_id)
                if not resource_with_params:
                    self.message_queue.put({
                        'type': 'log',
                        'text': f"Не удалось получить параметры для ресурса {resource_id} (template=12)",
                        'level': 'ERROR'
                    })
                    self.logger.error(f"Failed to get parameters for resource {resource_id} (template=12)")
                    return False
                z_vid = resource_with_params.get('z_vid', '')
                z_num = resource_with_params.get('z_num', '')
                z_data_v = resource_with_params.get('z_data_v', '')
                z_data_r = resource_with_params.get('z_data_r', '')
                z_data_p = resource_with_params.get('z_data_p', '')
                z_data_pg = resource_with_params.get('z_data_pg', '')
                appendix_structure_value = resource_with_params.get('appendix_structure')
                z_author = resource_with_params.get('z_author', '')
                z_komitet = resource_with_params.get('z_komitet', '')
                z_data_cons = resource_with_params.get('z_data_cons', '')
                z_data_1cht = resource_with_params.get('z_data_1cht', '')
                doc_type = 'law'
                if z_vid and "Постановление" in z_vid:
                    doc_type = 'regulation'
                year = None
                if z_data_r:
                    year_match = re.search(r'\b(\d{4})\b', str(z_data_r))
                    if year_match and 1900 <= int(year_match.group(1)) <= 2100:
                        year = year_match.group(1)
            else:
                if not parent_id:
                    resource_with_params = self.processor.get_resource_with_params_cached(resource_id)
                    if not resource_with_params:
                        self.message_queue.put({
                            'type': 'log',
                            'text': f"Не удалось получить параметры для ресурса {resource_id} (template={template}, parent отсутствует)",
                            'level': 'ERROR'
                        })
                        self.logger.error(f"Failed to get parameters for resource {resource_id} (template={template}, no parent)")
                        return False
                    z_vid = resource_with_params.get('z_vid', '')
                    z_num = resource_with_params.get('z_num', '')
                    z_data_v = resource_with_params.get('z_data_v', '')
                    z_data_r = resource_with_params.get('z_data_r', '')
                    z_data_p = resource_with_params.get('z_data_p', '')
                    z_data_pg = resource_with_params.get('z_data_pg', '')
                    appendix_structure_value = resource_with_params.get('appendix_structure')
                    z_author = resource_with_params.get('z_author', '')
                    z_komitet = resource_with_params.get('z_komitet', '')
                    z_data_cons = resource_with_params.get('z_data_cons', '')
                    z_data_1cht = resource_with_params.get('z_data_1cht', '')
                    doc_type = 'law' if z_vid and 'Закон' in z_vid else 'regulation'
                    year = None
                    if z_data_r:
                        year_match = re.search(r'\b(\d{4})\b', str(z_data_r))
                        if year_match and 1900 <= int(year_match.group(1)) <= 2100:
                            year = year_match.group(1)
                else:
                    parent_params = self.processor.get_parent_resource_params(parent_id)
                    if not parent_params:
                        self.message_queue.put({
                            'type': 'log',
                            'text': f"Не удалось получить параметры родителя {parent_id} для ресурса {resource_id}",
                            'level': 'ERROR'
                        })
                        self.logger.error(f"Failed to get parent parameters for parent {parent_id} of resource {resource_id}")
                        return False
                    z_vid = parent_params.get('z_vid', '')
                    z_num = parent_params.get('z_num', '')
                    z_data_v = parent_params.get('z_data_v', '')
                    z_data_r = parent_params.get('z_data_r', '')
                    z_data_p = parent_params.get('z_data_p', '')
                    z_data_pg = parent_params.get('z_data_pg', '')
                    appendix_structure_value = parent_params.get('appendix_structure')
                    z_author = parent_params.get('z_author', '')
                    z_komitet = parent_params.get('z_komitet', '')
                    z_data_cons = parent_params.get('z_data_cons', '')
                    z_data_1cht = parent_params.get('z_data_1cht', '')
                    doc_type = 'law'
                    if z_vid and "Постановление" in z_vid:
                        doc_type = 'regulation'
                    year = None
                    if z_data_r:
                        year_match = re.search(r'\b(\d{4})\b', str(z_data_r))
                        if year_match and 1900 <= int(year_match.group(1)) <= 2100:
                            year = year_match.group(1)
            date_reg_formatted = self.format_date(z_data_r) if z_data_r else ''
            date_1st_reading = self.format_date(z_data_1cht) if z_data_1cht else ''
            if doc_type == 'regulation':
                date_1st_reading = ''
            pub_info = ''
            pub_filepath = ''
            if doc_type == 'law' and z_num:
                number_str = z_num.replace('-ЗС', '').strip()
                try:
                    number_int = int(number_str)
                    if number_int < 176:
                        pub_info = longtitle
                    else:
                        if template == 12:
                            container_id = parent_id
                        elif template == 103:
                            container_id = resource_id
                        elif template == 102 or template == 245:
                            container_id = parent_id
                        else:
                            container_id = None
                        if container_id:
                            publish_val = self.processor.get_first_child_publish_tv(container_id)
                            if publish_val:
                                pub_filepath = "https://sevzakon.ru/" + publish_val
                except ValueError:
                    if template in (12, 102, 245):
                        container_id = parent_id
                    elif template == 103:
                        container_id = resource_id
                    else:
                        container_id = None
                    if container_id:
                        publish_val = self.processor.get_first_child_publish_tv(container_id)
                        if publish_val:
                            pub_filepath = "https://sevzakon.ru/" + publish_val
            appendix_decisions = {}
            if self.stop_event.is_set():
                return False
            doc_id_to_use = str(resource_id)
            file_id_to_use = str(resource_id)
            if (template == 102 or template == 245) and parent_id:
                doc_id_to_use = str(parent_id)
                file_id_to_use = str(parent_id)
                self.message_queue.put({
                    'type': 'log',
                    'text': f"Ресурс {resource_id} (шаблон {template}): использую ID родителя {parent_id} для JSON и имени файла",
                    'level': 'INFO'
                })
            elif custom_id:
                doc_id_to_use = custom_id
                file_id_to_use = custom_id
            generator = NpaToJsonGenerator(content_html, doc_type, appendix_decisions, document_id=doc_id_to_use, log_queue=self.message_queue, answer_queue=self.answer_queue, stop_event=self.stop_event)
            generator.logger.setLevel(logging.DEBUG)
            toc_structure, ambiguous_elements = generator.generate_toc()
            no_name_value = ",".join(generator.no_name_parents) if generator.no_name_parents else None
            if generator.collisions:
                for coll in generator.collisions:
                    self.message_queue.put({
                        'type': 'log',
                        'text': f"КОЛЛИЗИЯ: {coll['message']}",
                        'level': 'WARNING'
                    })
            if generator.errors:
                for err in generator.errors:
                    self.message_queue.put({
                        'type': 'log',
                        'text': f"Ресурс {resource_id}: {err}",
                        'level': 'ERROR'
                    })
                raise Exception(f"Ошибки при парсинге: {'; '.join(generator.errors)}")
            if self.stop_event.is_set():
                return False
            if z_author and isinstance(z_author, str):
                z_author = z_author.replace('||', ', ')
            if not year:
                year = datetime.now().strftime('%Y')
            head_revision = [{"npa_head": generator.doc_title}]
            if not generator.doc_title:
                raise Exception("Не удалось извлечь заголовок (npa_head) для постановления")
            date_cons_formatted = self.format_date(z_data_cons) if z_data_cons else ""
            date_1st_reading_formatted = self.format_date(z_data_1cht) if doc_type == 'law' and z_data_1cht else ""
            if doc_type == 'regulation':
                date_passed_formatted = generator.date_passed or self.format_date(z_data_r)
                date_signed_formatted = ""
            else:
                date_passed_formatted = generator.date_passed or self.format_date(z_data_r)
                date_signed_formatted = self.format_date(z_data_pg) if z_data_pg else generator.date_signed or ""
            date_pub_formatted = self.format_date(z_data_p) if z_data_p else ""
            valid_from_formatted = self.format_date(z_data_v) if z_data_v else ""
            npa_signer_post = self._normalize_text(generator.governor_post_html or "")
            npa_signer = self._normalize_signer_name(generator.governor_name or "")
            root_object = {
                "npa_id": doc_id_to_use,
                "npa_type": doc_type,
                "npa_number": generator.npa_number or (z_num if z_num else ""),
                "npa_author": z_author,
                "npa_npa_committee": z_komitet,
                "pub_info": pub_info or "",
                "pub_filepath": pub_filepath or "",
                "npa_url": npa_url,
                "date_reg": date_reg_formatted,
                "date_cons": date_cons_formatted,
                "date_1st_reading": date_1st_reading_formatted,
                "date_passed": date_passed_formatted,
                "date_signed": date_signed_formatted,
                "date_pub": date_pub_formatted,
                "valid_from": valid_from_formatted,
                "npa_signer_post": npa_signer_post,
                "npa_signer": npa_signer,
                "term_number": generator.term_number or "",
                "session_number": generator.session_number or "",
                "date_format": generator.date_format,
            }
            if no_name_value:
                root_object["no_name"] = no_name_value
            root_object.update({
                "head_revision": head_revision,
                "npa_items_revision": toc_structure,
            })
            root_object_clean = self._remove_empty(root_object)
            if self.save_locally_var.get() == 1:
                file_name = f"{file_id_to_use}.json"
                file_path = os.path.join(self.local_save_dir, file_name)
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(root_object_clean, f, ensure_ascii=False, indent=2)
                    self.message_queue.put({
                        'type': 'log',
                        'text': f"JSON для ресурса {resource_id} сохранён локально: {file_path}",
                        'level': 'INFO'
                    })
                    success = True
                except Exception as e:
                    self.message_queue.put({
                        'type': 'log',
                        'text': f"Ошибка записи файла {file_path}: {e}",
                        'level': 'ERROR'
                    })
                    success = False
            else:
                if not self.processor.create_structure(doc_type, year):
                    raise Exception("Ошибка создания структуры директорий")
                json_path = self.processor.upload_json_via_sftp(file_id_to_use, year, root_object_clean, doc_type)
                if not json_path:
                    raise Exception("Не удалось загрузить JSON файл")
                if not self.processor.update_tv_parameter(resource_id, json_path):
                    pass
                success = True
            log_suffix = ""
            if (template == 102 or template == 245) and parent_id:
                log_suffix = f" (использован ID родителя: {parent_id})"
            elif custom_id:
                log_suffix = f" (кастомный ID: {custom_id})"
            self.logger.info(f"Resource {resource_id} processed successfully{log_suffix}")
            self.message_queue.put({
                'type': 'log',
                'text': f"Ресурс {resource_id} обработан успешно{log_suffix}",
                'level': 'INFO'
            })
            return success
        except Exception as e:
            self.message_queue.put({
                'type': 'log',
                'text': f"Ошибка при обработке ресурса {resource_id}: {e}",
                'level': 'ERROR'
            })
            self.logger.error(f"Error processing resource {resource_id}: {str(e)}")
            return False

    def load_resources_list(self):
        if self.is_loading_resources:
            return
        law_num_filter = self.law_num_filter_entry.get().strip()
        resolution_num_filter = self.resolution_num_filter_entry.get().strip()
        self.is_loading_resources = True
        self.load_button.config(state=tk.DISABLED)
        self.status_var.set("Загрузка списка ресурсов...")
        load_thread = threading.Thread(
            target=self._load_resources_background_optimized,
            args=(law_num_filter, resolution_num_filter),
            daemon=True
        )
        load_thread.start()

    def _load_resources_background_optimized(self, law_num_filter, resolution_num_filter):
        try:
            resources = self.processor.load_resources_list_optimized(law_num_filter, resolution_num_filter)
            self.message_queue.put({
                'type': 'load_complete',
                'resources': resources,
                'error': None
            })
        except Exception as e:
            self.message_queue.put({
                'type': 'load_complete',
                'resources': None,
                'error': str(e)
            })

    def run(self):
        self.root.mainloop()

def main():
    if sys.version_info < (3, 6):
        print("Требуется Python 3.6 или выше")
        sys.exit(1)
    try:
        import tkinter
    except ImportError:
        print("Ошибка: Tkinter не установлен. Установите его:")
        print("Ubuntu/Debian: sudo apt-get install python3-tk")
        print("Windows: устанавливается вместе с Python")
        print("macOS: brew install python-tk")
        sys.exit(1)
    app = MODXProcessorGUI()
    app.run()

if __name__ == "__main__":
    main()
