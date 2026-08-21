import tkinter as tk
from tkinter import ttk, messagebox
from collections import defaultdict

class SourceMappingDialog(tk.Toplevel):
    def __init__(self, parent, revision_number, change_data, evt, result_dict,
                 type_to_russian=None, find_item_by_id_func=None, stop_event=None,
                 change_info="", is_ambiguity=False, target_element_id=None):
        super().__init__(parent)
        self.revision_number = revision_number
        self.change_data = change_data
        self.evt = evt
        self.result = result_dict
        self.type_to_russian = type_to_russian or {}
        self.find_item_by_id = find_item_by_id_func or (lambda d, i: None)
        self.stop_event = stop_event
        self.change_info = change_info
        self.is_ambiguity = is_ambiguity
        self.target_element_id = target_element_id

        if is_ambiguity:
            self.title("Неоднозначность – выберите правильный элемент")
        else:
            self.title("Выбор источника изменения")

        self.geometry("800x600")
        self.minsize(600, 400)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        if self.stop_event and self.stop_event.is_set():
            self._on_cancel()
            return

        self._create_widgets()
        self._populate_tree()

    def _is_item_active(self, item):
        revisions = item.get('revisions', [])
        if not revisions:
            return True
        return any(rev.get('valid_to') in (None, '') for rev in revisions)

    def _create_widgets(self):
        info_frame = ttk.LabelFrame(self, text="Информация об изменении")
        info_frame.pack(fill='x', padx=10, pady=5)

        if self.revision_number and str(self.revision_number) not in ('null', 'None', ''):
            ttk.Label(info_frame, text=f"Номер ревизии / revision_number: {self.revision_number}",
                      wraplength=750, foreground="blue").pack(anchor='w', padx=5, pady=2)

        if self.is_ambiguity:
            ttk.Label(info_frame, text="Не удалось однозначно определить целевой элемент для изменения:",
                      wraplength=750, foreground="red").pack(anchor='w', padx=5, pady=2)
            if self.change_info:
                ttk.Label(info_frame, text=f"Изменение: {self.change_info}",
                          wraplength=750, foreground="blue").pack(anchor='w', padx=5, pady=2)
            ttk.Label(info_frame,
                      text="В структуре закона найдено несколько элементов с одинаковым типом и номером. Пожалуйста, выберите тот, к которому относится изменение.",
                      wraplength=750).pack(anchor='w', padx=5, pady=2)
        else:
            ttk.Label(info_frame, text=f"Не удалось найти элемент по revision_number: {self.revision_number}",
                      wraplength=750).pack(anchor='w', padx=5, pady=2)
            if self.change_info:
                ttk.Label(info_frame, text=f"Изменение: {self.change_info}",
                          wraplength=750, foreground="blue").pack(anchor='w', padx=5, pady=2)
            ttk.Label(info_frame,
                      text="Пожалуйста, выберите элемент в изменяющем законе, который является источником изменения.",
                      wraplength=750).pack(anchor='w', padx=5, pady=2)

        tree_frame = ttk.LabelFrame(self, text="Структура изменяющего закона")
        tree_frame.pack(fill='both', expand=True, padx=10, pady=5)

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient='vertical')
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient='horizontal')
        self.tree = ttk.Treeview(tree_frame, columns=("id", "type", "number"),
                                 show="tree headings",
                                 yscrollcommand=tree_scroll_y.set,
                                 xscrollcommand=tree_scroll_x.set)
        self.tree.heading("#0", text="Путь")
        self.tree.heading("id", text="ID элемента")
        self.tree.heading("type", text="Тип")
        self.tree.heading("number", text="Номер")
        self.tree.column("#0", width=300)
        self.tree.column("id", width=150)
        self.tree.column("type", width=100)
        self.tree.column("number", width=80)

        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)

        self.tree.grid(row=0, column=0, sticky='nsew')
        tree_scroll_y.grid(row=0, column=1, sticky='ns')
        tree_scroll_x.grid(row=1, column=0, sticky='ew')
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill='x', padx=10, pady=10)

        ttk.Button(btn_frame, text="Выбрать", command=self._on_choose).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Игнорировать", command=self._on_ignore).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Остановить процесс", command=self._on_stop).pack(side='left', padx=5)

    def _populate_tree(self):
        root_items = self.change_data.get('npa_items_revision', [])
        def add_items(parent_node, items, path_prefix=""):
            key_to_indices = defaultdict(list)
            for idx, item in enumerate(items):
                if not self._is_item_active(item):
                    continue
                key = (item.get('item_type'), item.get('item_number'))
                key_to_indices[key].append(idx)

            for idx, item in enumerate(items):
                if not self._is_item_active(item):
                    continue
                item_id = item.get('item_id', '')
                item_type = item.get('item_type', '')
                item_number = item.get('item_number', '')
                ru_type = self.type_to_russian.get(item_type, item_type)

                if item_type == 'preamble':
                    base_display = "Преамбула"
                else:
                    base_display = f"{ru_type} {item_number}" if item_number else ru_type

                key = (item_type, item_number)
                indices = key_to_indices.get(key, [])
                if len(indices) > 1:
                    position = indices.index(idx) + 1
                    display = f"{base_display} (позиция {position})"
                else:
                    display = base_display

                full_path = f"{path_prefix}/{display}" if path_prefix else display
                node = self.tree.insert(parent_node, 'end', text=full_path,
                                        values=(item_id, ru_type, item_number))
                children = item.get('item_children', [])
                if children:
                    add_items(node, children, full_path)

        add_items('', root_items)

    def _on_choose(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Выбор", "Пожалуйста, выберите элемент в дереве.")
            return
        item = self.tree.item(selected[0])
        item_id = item['values'][0]
        if not item_id:
            messagebox.showerror("Ошибка", "Выбранный элемент не имеет ID.")
            return
        self.result['item_id'] = item_id
        self.evt.set()
        self.destroy()

    def _on_ignore(self):
        self.result['item_id'] = None
        self.evt.set()
        self.destroy()

    def _on_cancel(self):
        self.result['item_id'] = None
        self.evt.set()
        self.destroy()

    def _on_stop(self):
        if self.stop_event:
            self.stop_event.set()
        self.result['item_id'] = None
        self.evt.set()
        self.destroy()