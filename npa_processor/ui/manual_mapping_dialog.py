import tkinter as tk
from tkinter import ttk, messagebox
import re
from bs4 import BeautifulSoup

class ManualMappingDialog:
    def __init__(self, parent, change, original_data, evt, result_dict,
                 is_title_change=False, type_to_russian=None,
                 find_item_by_id_func=None, stop_event=None):
        self.parent = parent
        self.change = change
        self.original_data = original_data
        self.evt = evt
        self.result = result_dict
        self.is_title_change = is_title_change
        self.type_to_russian = type_to_russian or {}
        self.find_item_by_id = find_item_by_id_func or (lambda d, i: None)
        self.stop_event = stop_event

        self.window = tk.Toplevel(parent)
        self.window.title("Ручное сопоставление изменения")
        self.window.geometry("950x800")
        self.window.minsize(850, 700)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self._on_ignore)

        main_canvas = tk.Canvas(self.window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=main_canvas.yview)
        self.scrollable_frame = ttk.Frame(main_canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)

        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        info_frame = ttk.LabelFrame(self.scrollable_frame, text="Исходное изменение")
        info_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(info_frame, text=f"Элемент: {self.change.get('structural_element', '')}",
                  wraplength=900).pack(anchor='w', padx=5, pady=2)
        ttk.Label(info_frame, text=f"Описание: {self.change.get('description', '')}",
                  wraplength=900).pack(anchor='w', padx=5, pady=2)
        ttk.Label(info_frame, text=f"Тип: {self.change.get('type', 'change')}",
                  wraplength=900).pack(anchor='w', padx=5, pady=2)

        tree_frame = ttk.LabelFrame(self.scrollable_frame, text="Выберите целевой элемент (кликните для выбора)")
        tree_frame.pack(fill='both', expand=True, padx=10, pady=5)

        tree_container = ttk.Frame(tree_frame)
        tree_container.pack(fill='both', expand=True, padx=5, pady=5)

        self.tree = ttk.Treeview(tree_container, columns=("id", "info"), show="tree headings")
        self.tree.heading("#0", text="Структурный путь")
        self.tree.heading("id", text="ID")
        self.tree.heading("info", text="Тип / Номер")
        self.tree.column("#0", width=450)
        self.tree.column("id", width=200)
        self.tree.column("info", width=200)

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        self.tree.bind('<<TreeviewSelect>>', self._on_select)

        path_frame = ttk.LabelFrame(self.scrollable_frame, text="Выбранный путь (подтверждение только по кнопке ниже)")
        path_frame.pack(fill='x', padx=10, pady=(0,5))
        self.path_var = tk.StringVar(value="(не выбран)")
        path_label = tk.Label(path_frame, textvariable=self.path_var,
                              font=('Arial', 11, 'bold'), bg='#ffffcc', fg='#000000',
                              wraplength=900, justify='left', anchor='w')
        path_label.pack(fill='x', padx=5, pady=5)

        struct_frame = ttk.LabelFrame(self.scrollable_frame, text="Редактирование структурного пути (при необходимости)")
        struct_frame.pack(fill='x', padx=10, pady=5)
        self.structural_var = tk.StringVar()
        self.structural_entry = ttk.Entry(struct_frame, textvariable=self.structural_var, width=100)
        self.structural_entry.pack(fill='x', padx=5, pady=5)
        ttk.Label(struct_frame, text="Путь будет автоматически сформирован при выборе в дереве, но вы можете отредактировать его вручную.", 
                  font=('Arial', 8, 'italic')).pack(anchor='w', padx=5)

        edit_frame = ttk.LabelFrame(self.scrollable_frame, text="Редактирование изменения")
        edit_frame.pack(fill='x', padx=10, pady=5)

        type_frame = ttk.Frame(edit_frame)
        type_frame.pack(fill='x', padx=5, pady=5)
        ttk.Label(type_frame, text="Тип:").pack(side='left', padx=5)
        self.type_var = tk.StringVar(value=self.change.get('type', 'change'))
        type_combo = ttk.Combobox(type_frame, textvariable=self.type_var,
                                  values=['change', 'new_redaction', 'add', 'delete'],
                                  state='readonly', width=20)
        type_combo.pack(side='left', padx=5)

        desc_frame = ttk.Frame(edit_frame)
        desc_frame.pack(fill='both', expand=True, padx=5, pady=5)
        ttk.Label(desc_frame, text="Описание:").pack(anchor='w')
        self.desc_text = tk.Text(desc_frame, height=6, wrap='word')
        desc_scroll = ttk.Scrollbar(desc_frame, orient="vertical", command=self.desc_text.yview)
        self.desc_text.configure(yscrollcommand=desc_scroll.set)
        self.desc_text.pack(side='left', fill='both', expand=True)
        desc_scroll.pack(side='right', fill='y')
        self.desc_text.insert('1.0', self.change.get('description', ''))
        self._add_hotkeys(self.desc_text)

        btn_frame = ttk.Frame(self.scrollable_frame)
        btn_frame.pack(fill='x', padx=10, pady=10)
        for i in range(3):
            btn_frame.columnconfigure(i, weight=1)

        ttk.Button(btn_frame, text="Применить и продолжить", command=self._on_choose).grid(row=0, column=0, padx=5, sticky='ew')
        ttk.Button(btn_frame, text="Игнорировать изменение", command=self._on_ignore).grid(row=0, column=1, padx=5, sticky='ew')
        ttk.Button(btn_frame, text="Остановить процесс", command=self._on_stop).grid(row=0, column=2, padx=5, sticky='ew')

        self._populate_tree()
        self._select_first_item()

        self.window.update_idletasks()

    def destroy(self):
        if self.window:
            self.window.destroy()

    def _add_hotkeys(self, w):
        w.bind('<Control-c>', lambda e: w.event_generate('<<Copy>>') or 'break')
        w.bind('<Control-v>', lambda e: w.event_generate('<<Paste>>') or 'break')
        w.bind('<Control-x>', lambda e: w.event_generate('<<Cut>>') or 'break')
        w.bind('<Control-a>', lambda e: w.tag_add('sel', '1.0', 'end') or 'break')

    def _is_item_active(self, item):
        revisions = item.get('revisions', [])
        if not revisions:
            return True
        return any(rev.get('valid_to') in (None, '') for rev in revisions)

    def _get_paragraphs_for_element(self, element):
        paragraphs = []
        revisions = element.get('revisions', [])
        active_rev = None
        for rev in reversed(revisions):
            if rev.get('valid_to') in (None, ''):
                active_rev = rev
                break
        if not active_rev:
            return paragraphs
        body = active_rev.get('body', [])
        order = 1
        for block in body:
            if block.get('type') == 'paragraph':
                html = block.get('html_text', '')
                soup = BeautifulSoup(html, 'html.parser')
                text = soup.get_text(strip=True)
                if len(text) > 80:
                    text = text[:80] + '...'
                paragraphs.append({
                    'order': order,
                    'html_text': html,
                    'preview_text': text
                })
                order += 1
        return paragraphs

    def _populate_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        self.tree.insert("", "end", iid="__name__", text="Наименование документа",
                         values=("__name__", "наименование"))
        if self.change.get('type') == 'add':
            self.tree.insert("", "end", iid="__npa_root__", text="НПА (добавление в корень)",
                             values=("__npa_root__", "корень документа"))

        items = self.original_data.get('npa_items_revision', [])
        if not items:
            items = self.original_data.get('npa_items', [])
        if items:
            self._add_items(items, "")
        else:
            self.tree.insert("", "end", iid="__empty__", text="Нет структурных элементов",
                             values=("", ""))

        for child in self.tree.get_children():
            self.tree.item(child, open=True)

    def _add_items(self, items, parent, path_sofar=""):
        for item in items:
            if not self._is_item_active(item):
                continue
            item_id = item.get('item_id', '')
            itype = item.get('item_type', '')
            inum = item.get('item_number', '')
            ru = self.type_to_russian.get(itype, itype).capitalize()
            if itype == 'preamble':
                display = "Преамбула"
            elif itype == 'structured_table':
                display = f"Таблица {inum}" if inum else "Структурированная таблица"
            else:
                display = f"{ru} {inum}" if inum else ru
            full_path = f"{path_sofar}/{display}" if path_sofar else display
            node = self.tree.insert(parent, "end", text=full_path,
                                    values=(item_id, f"{ru} {inum}".strip()))
            children = item.get('item_children', [])
            if children:
                self._add_items(children, node, full_path)
            paragraphs = self._get_paragraphs_for_element(item)
            for para in paragraphs:
                para_display = f"Абзац {para['order']}"
                if para['preview_text']:
                    para_display += f" — {para['preview_text']}"
                para_path = f"{full_path}/{para_display}"
                para_iid = f"para_{item_id}_{para['order']}"
                self.tree.insert(node, "end", iid=para_iid, text=para_path,
                                 values=(f"para_{item_id}_{para['order']}", f"Абзац {para['order']}"))

    def _select_first_item(self):
        for child in self.tree.get_children():
            val = self.tree.item(child, "values")[0]
            if val not in ("__name__", "__npa_root__", "__empty__"):
                self.tree.selection_set(child)
                self.tree.focus(child)
                self._on_select()
                return
        if self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
            self._on_select()

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self.path_var.set("(не выбран)")
            self.structural_var.set("")
            return
        node = sel[0]
        full_path = self.tree.item(node, "text")
        if node.startswith("para_"):
            parts = node.split('_')
            if len(parts) >= 3:
                parent_node = self.tree.parent(node)
                parent_path = self.tree.item(parent_node, "text") if parent_node else ""
                clean_parent = re.sub(r'[📄📌📜📊⚠️└─]', '', parent_path).strip()
                order = parts[-1]
                structural = f"{clean_parent} абзац {order}"
                self.structural_var.set(structural)
            else:
                self.structural_var.set(full_path)
        else:
            self.structural_var.set(full_path)
        self.path_var.set(full_path)

    def _on_choose(self):
        sel = self.tree.selection()
        if not sel:
            return
        node = sel[0]
        values = self.tree.item(node, "values")
        if not values:
            return
        raw_id = values[0]
        if raw_id == "__name__":
            target_id = "__наименование__"
            structural = "наименование"
        elif raw_id == "__npa_root__":
            target_id = None
            structural = "нпа"
        elif raw_id.startswith("para_"):
            parts = raw_id.split('_')
            if len(parts) >= 3:
                item_id = '_'.join(parts[1:-1])
                order = parts[-1]
                target_id = item_id
                user_structural = self.structural_var.get().strip()
                if user_structural:
                    structural = user_structural
                else:
                    parent_node = self.tree.parent(node)
                    parent_path = self.tree.item(parent_node, "text") if parent_node else ""
                    clean_parent = re.sub(r'[📄📌📜📊⚠️└─]', '', parent_path).strip()
                    structural = f"{clean_parent} абзац {order}"
            else:
                messagebox.showerror("Ошибка", "Некорректный идентификатор абзаца")
                return
        elif raw_id == "__empty__":
            return
        else:
            target_id = raw_id
            user_structural = self.structural_var.get().strip()
            structural = user_structural if user_structural else self.tree.item(node, "text")
        self.result['target_id'] = target_id
        self.result['structural'] = structural
        self.result['description'] = self.desc_text.get('1.0', tk.END).strip()
        self.result['type'] = self.type_var.get().strip()
        self.evt.set()
        self.window.destroy()

    def _on_ignore(self):
        self.result['target_id'] = None
        self.result['structural'] = None
        self.result['description'] = None
        self.result['type'] = None
        self.evt.set()
        self.window.destroy()

    def _on_stop(self):
        if self.stop_event:
            self.stop_event.set()
        self.result['target_id'] = None
        self.result['structural'] = None
        self.result['description'] = None
        self.result['type'] = None
        self.evt.set()
        self.window.destroy()