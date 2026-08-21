"""Mixin для создания графического интерфейса приложения."""

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
import json

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

class GuiBuilderMixin:
        def create_widgets(self):
            row = 0
            self.left_frame.grid_columnconfigure(1, weight=1)
            tk.Label(self.left_frame, text="Оригинальный JSON файл закона:").grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.entry_orig = tk.Entry(self.left_frame, textvariable=self.original_path)
            self.entry_orig.grid(row=row, column=1, padx=10, pady=8, sticky='ew')
            add_context_menu(self.entry_orig, allow_edit=True)
            add_hotkeys(self.entry_orig, allow_edit=True)
            tk.Button(self.left_frame, text="Выбрать", command=self.browse_original).grid(row=row, column=2, padx=5, pady=8)
            row += 1
            tk.Label(self.left_frame, text="JSON файл с изменениями:").grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.entry_change = tk.Entry(self.left_frame, textvariable=self.change_path)
            self.entry_change.grid(row=row, column=1, padx=10, pady=8, sticky='ew')
            add_context_menu(self.entry_change, allow_edit=True)
            add_hotkeys(self.entry_change, allow_edit=True)
            tk.Button(self.left_frame, text="Выбрать", command=self.browse_change).grid(row=row, column=2, padx=5, pady=8)
            row += 1
            tk.Label(self.left_frame, text="Реквизиты изменяющего закона:").grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.entry_law_ref = tk.Entry(self.left_frame, textvariable=self.law_ref)
            self.entry_law_ref.grid(row=row, column=1, padx=10, pady=8, sticky='ew', columnspan=2)
            add_context_menu(self.entry_law_ref, allow_edit=True)
            add_hotkeys(self.entry_law_ref, allow_edit=True)
            row += 1
            tk.Label(self.left_frame, text="Номер оригинального закона:").grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.entry_original_law = tk.Entry(self.left_frame, textvariable=self.original_law_ref)
            self.entry_original_law.grid(row=row, column=1, padx=10, pady=8, sticky='ew', columnspan=2)
            add_context_menu(self.entry_original_law, allow_edit=True)
            add_hotkeys(self.entry_original_law, allow_edit=True)
            row += 1
            tk.Label(self.left_frame, text="Дата публикации изменяющего закона:").grid(row=row, column=0, padx=10, pady=8, sticky='e')
            self.entry_pub_date = tk.Entry(self.left_frame, textvariable=self.pub_date, width=20, state='readonly')
            self.entry_pub_date.grid(row=row, column=1, padx=10, pady=8, sticky='w', columnspan=2)
            row += 1
            tk.Label(self.left_frame, text="Модель:").grid(row=row, column=0, padx=10, pady=8, sticky='e')
            frame_model = tk.Frame(self.left_frame)
            frame_model.grid(row=row, column=1, columnspan=2, sticky='ew', padx=10, pady=8)
            self.model_entry = tk.Entry(frame_model, textvariable=self.ollama_model)
            self.model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
            add_context_menu(self.model_entry, allow_edit=True)
            add_hotkeys(self.model_entry, allow_edit=True)
            self.model_dropdown_btn = tk.Button(frame_model, text="▼", width=3, command=self.show_model_dropdown)
            self.model_dropdown_btn.pack(side=tk.LEFT, padx=(0,5))
            self.model_refresh_btn = tk.Button(frame_model, text="⟲", width=3, command=self.refresh_models)
            self.model_refresh_btn.pack(side=tk.LEFT, padx=(0,5))
            self.model_params_btn = tk.Button(frame_model, text="Загрузить параметры модели", command=self.load_model_params)
            self.model_params_btn.pack(side=tk.LEFT, padx=(5,0))
            row += 1
            tk.Label(self.left_frame, text="Дополнительные параметры (JSON):").grid(row=row, column=0, padx=10, pady=8, sticky='e')
            frame_params = tk.Frame(self.left_frame)
            frame_params.grid(row=row, column=1, columnspan=2, sticky='ew', padx=10, pady=8)
            self.entry_extra_options = tk.Entry(frame_params, textvariable=self.extra_options)
            self.entry_extra_options.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
            add_context_menu(self.entry_extra_options, allow_edit=True)
            add_hotkeys(self.entry_extra_options, allow_edit=True)
            tk.Button(frame_params, text="Сбросить параметры", command=self.reset_extra_options).pack(side=tk.LEFT, padx=(0,5))
            tk.Label(frame_params, text="Напр.: {\"temperature\": 0.5, \"top_p\": 0.9}", fg="gray").pack(side=tk.LEFT)
            row += 1
            chk_frame = tk.Frame(self.left_frame)
            chk_frame.grid(row=row, column=0, columnspan=3, sticky='w', padx=10, pady=5)
            tk.Label(chk_frame, text="Режим анализа этапа 3:").pack(side=tk.LEFT, padx=(0,10))
            tk.Radiobutton(chk_frame, text="Целый документ", variable=self.elementwise_mode, value=False).pack(side=tk.LEFT, padx=5)
            tk.Radiobutton(chk_frame, text="Поэлементно", variable=self.elementwise_mode, value=True).pack(side=tk.LEFT, padx=5)
            row += 1
            notebook = ttk.Notebook(self.left_frame)
            notebook.grid(row=row, column=0, columnspan=3, sticky='nsew', padx=10, pady=5)
            self.left_frame.grid_rowconfigure(row, weight=1)
            frame1 = tk.Frame(notebook)
            notebook.add(frame1, text="Этап 1 (утрата силы)")
            tk.Label(frame1, text="Вставьте ответ ИИ для этапа 1 (JSON):").pack(anchor='w', padx=5, pady=2)
            self.stage1_answer_text = tk.Text(frame1, height=10, wrap='word')
            self.stage1_answer_text.pack(fill='both', expand=True, padx=5, pady=2)
            self.stage1_answer_text.insert('1.0', self.stage1_answer.get())
            add_context_menu(self.stage1_answer_text, allow_edit=True)
            add_hotkeys(self.stage1_answer_text, allow_edit=True)
            self.use_stage1_check = tk.Checkbutton(frame1, text="Использовать вставленный ответ (вместо запроса к ИИ)",
                                                    variable=self.use_stage1_answer)
            self.use_stage1_check.pack(anchor='w', padx=5, pady=5)
            tk.Button(frame1, text="Сохранить введённый ответ", command=self.save_stage_answers).pack(pady=5)
            frame2 = tk.Frame(notebook)
            notebook.add(frame2, text="Этап 2 (даты/правоотношения)")
            tk.Label(frame2, text="Вставьте ответ ИИ для этапа 2 (JSON):").pack(anchor='w', padx=5, pady=2)
            self.stage2_answer_text = tk.Text(frame2, height=10, wrap='word')
            self.stage2_answer_text.pack(fill='both', expand=True, padx=5, pady=2)
            self.stage2_answer_text.insert('1.0', self.stage2_answer.get())
            add_context_menu(self.stage2_answer_text, allow_edit=True)
            add_hotkeys(self.stage2_answer_text, allow_edit=True)
            self.use_stage2_check = tk.Checkbutton(frame2, text="Использовать вставленный ответ (вместо запроса к ИИ)",
                                                    variable=self.use_stage2_answer)
            self.use_stage2_check.pack(anchor='w', padx=5, pady=5)
            tk.Button(frame2, text="Сохранить введённый ответ", command=self.save_stage_answers).pack(pady=5)
            frame3 = tk.Frame(notebook)
            notebook.add(frame3, text="Этап 3 (изменения из статьи)")
            tk.Label(frame3, text="Вставьте ответ ИИ для этапа 3 (JSON):").pack(anchor='w', padx=5, pady=2)
            self.stage3_answer_text = tk.Text(frame3, height=10, wrap='word')
            self.stage3_answer_text.pack(fill='both', expand=True, padx=5, pady=2)
            self.stage3_answer_text.insert('1.0', self.stage3_answer.get())
            add_context_menu(self.stage3_answer_text, allow_edit=True)
            add_hotkeys(self.stage3_answer_text, allow_edit=True)
            self.use_stage3_check = tk.Checkbutton(frame3, text="Использовать вставленный ответ (вместо запроса к ИИ)",
                                                    variable=self.use_stage3_answer)
            self.use_stage3_check.pack(anchor='w', padx=5, pady=5)
            tk.Button(frame3, text="Сохранить введённый ответ", command=self.save_stage_answers).pack(pady=5)
            row += 1
            btn_frame = tk.Frame(self.left_frame)
            btn_frame.grid(row=row+1, column=0, columnspan=3, pady=10)
            self.run_btn = tk.Button(btn_frame, text="Запустить", command=self.run_all, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
            self.run_btn.pack(side=tk.LEFT, padx=5)
            self.cancel_btn = tk.Button(btn_frame, text="Отмена", command=self.cancel, bg="#f44336", fg="white", font=("Arial", 10, "bold"), state='disabled')
            self.cancel_btn.pack(side=tk.LEFT, padx=5)
            self.status_var = tk.StringVar(value="Готов к работе")
            log_frame = ttk.Frame(self.right_frame)
            log_frame.pack(fill='both', expand=True, padx=5, pady=5)
            scrollbar = ttk.Scrollbar(log_frame)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self.log_text = tk.Text(log_frame, height=12, wrap='word', font=("Consolas", 9), yscrollcommand=scrollbar.set)
            self.log_text.pack(side=tk.LEFT, fill='both', expand=True)
            scrollbar.config(command=self.log_text.yview)
            add_context_menu(self.log_text, allow_edit=False)
            add_hotkeys(self.log_text, allow_edit=False)
            self.log_text.tag_config('error', foreground='red')
            self.log_text.tag_config('warning', foreground='orange')
            self.log_text.tag_config('info', foreground='gray')
            self.log_text.tag_config('input', foreground='blue')
            self.log_text.tag_config('result', foreground='green')
            self.log_text.tag_config('source', foreground='purple')

        def save_stage_answers(self):
            self.stage1_answer.set(self.stage1_answer_text.get('1.0', tk.END).strip())
            self.stage2_answer.set(self.stage2_answer_text.get('1.0', tk.END).strip())
            self.stage3_answer.set(self.stage3_answer_text.get('1.0', tk.END).strip())
            data = {
                'stage1_answer': self.stage1_answer.get(),
                'stage2_answer': self.stage2_answer.get(),
                'stage3_answer': self.stage3_answer.get(),
                'use_stage1_answer': self.use_stage1_answer.get(),
                'use_stage2_answer': self.use_stage2_answer.get(),
                'use_stage3_answer': self.use_stage3_answer.get(),
            }
            save_json(STAGE_ANSWERS_FILE, data)

        def reset_extra_options(self):
            self.extra_options.set(json.dumps(DEFAULT_EXTRA_OPTIONS))
            self.log("Параметры сброшены к стандартным", 'info')

        def show_model_dropdown(self):
            if not self.ollama_models:
                self.log("Список моделей пуст. Нажмите кнопку обновления.", 'warning')
                return
            menu = tk.Menu(self.root, tearoff=0)
            for model in self.ollama_models:
                menu.add_command(label=model, command=lambda m=model: self.on_model_selected(m))
            x = self.model_dropdown_btn.winfo_rootx()
            y = self.model_dropdown_btn.winfo_rooty() + self.model_dropdown_btn.winfo_height()
            menu.post(x, y)

        def on_model_selected(self, model):
            self.ollama_model.set(model)

        def refresh_models(self):
            self.log("Обновление списка моделей...", 'info')
            threading.Thread(target=self._fetch_ollama_models, daemon=True).start()

        def browse_original(self):
            path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
            if path:
                self.original_path.set(path)
                self.last_paths['original'] = path
                save_json(LAST_PATHS_FILE, self.last_paths)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    npa_number = data.get('npa_number', '')
                    if npa_number:
                        self.original_law_ref.set(npa_number)
                        self.log(f"Номер оригинального закона: {npa_number}", 'info')
                    else:
                        self.log("Не удалось извлечь номер оригинального закона.", 'warning')
                except Exception as e:
                    self.log(f"Ошибка при чтении JSON: {e}", 'error')

        def browse_change(self):
            if not self.original_path.get().strip():
                messagebox.showwarning("Внимание", "Сначала выберите оригинальный JSON файл закона.")
                return
            path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
            if path:
                self.change_path.set(path)
                self.last_paths['change'] = path
                save_json(LAST_PATHS_FILE, self.last_paths)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        change_data = json.load(f)
                    npa_number = change_data.get('npa_number', '').strip()
                    date_signed = change_data.get('date_signed', '').strip()
                    if npa_number:
                        if date_signed:
                            self.law_ref.set(f"№ {npa_number} от {date_signed}")
                        else:
                            self.law_ref.set(npa_number)
                    else:
                        self.log("Не удалось извлечь номер закона из JSON изменений.", 'warning')
                    pub_date_str = change_data.get('date_pub', '').strip()
                    if not pub_date_str:
                        pub_date_str = change_data.get('date_signed', '').strip()
                    if not pub_date_str:
                        pub_date_str = change_data.get('valid_from', '').strip()
                    if pub_date_str:
                        self.pub_date.set(pub_date_str)
                        self.log(f"Установлена дата публикации изменяющего закона: {pub_date_str}", 'info')
                    else:
                        self.log("В JSON изменений не найдено поле с датой (date_pub, date_signed, valid_from).", 'warning')
                except Exception as e:
                    self.log(f"Ошибка при обработке файла изменений: {e}", 'error')

        def log(self, message, tag=None):
            def _log():
                self.log_text.config(state='normal')
                if tag:
                    self.log_text.insert(tk.END, message + '\n', tag)
                else:
                    if 'ошибка' in message.lower() or '❌' in message or 'failed' in message.lower():
                        self.log_text.insert(tk.END, message + '\n', 'error')
                    elif '⚠' in message or 'warning' in message.lower():
                        self.log_text.insert(tk.END, message + '\n', 'warning')
                    else:
                        self.log_text.insert(tk.END, message + '\n', 'info')
                self.log_text.see(tk.END)
                self.log_text.config(state='normal')
            self.root.after(0, _log)
