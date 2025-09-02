import tkinter as tk
from tkinter import ttk, filedialog
import re
import os

class CParser:
    def __init__(self, code):
        self.original_code = code
        self.code_without_comments = self._remove_comments(code)
        self.functions = {}
        self.modules = []
        self.tables = []
        self.syntax_errors = []

    def _remove_comments(self, code):
        # Remove multi-line comments /* ... */
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        # Remove single-line comments // ...
        code = re.sub(r'//.*', '', code)
        # Remove preprocessor directives #...
        code = re.sub(r'#.*', '', code)
        return code

    def parse(self):
        self._parse_functions()
        self._parse_calls_within_functions()
        self._check_syntax()

    def _check_syntax(self):
        """Checks for balanced parentheses and braces."""
        stack = []
        line = 1
        for char in self.code_without_comments:
            if char == '\n':
                line += 1
            elif char in '({':
                stack.append((char, line))
            elif char == ')':
                if not stack or stack[-1][0] != '(':
                    self.syntax_errors.append(f"Mismatched ')' on line {line}")
                    return
                stack.pop()
            elif char == '}':
                if not stack or stack[-1][0] != '{':
                    self.syntax_errors.append(f"Mismatched '}}' on line {line}")
                    return
                stack.pop()

        for item, line in stack:
            self.syntax_errors.append(f"Unclosed '{item}' from line {line}")

    def get_call_tree(self, root_function):
        """Builds a hierarchical call tree starting from a root function."""
        if root_function not in self.functions:
            return None

        def build_node(func_name, visited):
            if func_name in visited:
                return {"name": f"{func_name} (Recursion)", "children": []}

            visited.add(func_name)

            node = {"name": func_name, "children": []}
            if func_name in self.functions:
                for called_func in self.functions[func_name]["calls"]:
                    if called_func in self.functions:
                        node["children"].append(build_node(called_func, visited.copy()))
            return node

        return build_node(root_function, set())

    def _find_closing_brace(self, code, start_index):
        depth = 1
        for i in range(start_index, len(code)):
            if code[i] == '{':
                depth += 1
            elif code[i] == '}':
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _parse_tags_from_comment(self, comment_content):
        docs = {}
        for tag_match in re.finditer(r'@(\w+)\s*:\s*(.*?)(?=\s*@|\s*\*/)', comment_content, re.DOTALL):
            tag = tag_match.group(1).upper()
            value = tag_match.group(2).strip()
            docs[tag] = value
        return docs

    def _parse_functions(self):
        for match in PATTERNS["function_def"].finditer(self.original_code):
            ret_type = match.group(1).strip().replace('\n', ' ')
            func_name = match.group(2).strip()
            params = match.group(3).strip()

            if func_name in self.functions: continue

            docs = {}
            search_start = match.end()

            # 1. Forward search for comment (new style)
            search_area = self.original_code[search_start : search_start + 2048]
            comment_match = re.search(r"/\*(.*?)\*/", search_area, re.DOTALL)
            brace_match = re.search(r"\{", search_area)

            body_start_brace_rel = brace_match.start() if brace_match else -1

            if comment_match and body_start_brace_rel != -1 and comment_match.start() < body_start_brace_rel:
                docs = self._parse_tags_from_comment(comment_match.group(1))

            # 2. If no comment found, backward search (old style)
            if not docs:
                comment_end_pos = self.original_code.rfind('*/', 0, match.start())
                if comment_end_pos != -1:
                    code_between = self.original_code[comment_end_pos + 2 : match.start()]
                    if not code_between.strip():
                        comment_start_pos = self.original_code.rfind('/*', 0, comment_end_pos)
                        if comment_start_pos != -1:
                            docs = self._parse_tags_from_comment(self.original_code[comment_start_pos + 2 : comment_end_pos])

            if body_start_brace_rel == -1: continue

            body_start_abs = search_start + body_start_brace_rel
            body_end_abs = self._find_closing_brace(self.original_code, body_start_abs + 1)

            body = ""
            if body_end_abs != -1:
                body_with_comments = self.original_code[body_start_abs + 1 : body_end_abs]
                body = self._remove_comments(body_with_comments)

            line_number = self.original_code.count('\n', 0, match.start()) + 1
            self.functions[func_name] = {
                "return_type": ret_type, "params": params, "body": body,
                "docs": docs, "calls": [], "modules": [], "tables": [],
                "line_number": line_number,
            }

    def _parse_calls_within_functions(self):
        for func_name, func_data in self.functions.items():
            body = func_data["body"]
            if not body: continue

            # Find function calls
            called_funcs = set()
            for call_match in PATTERNS["function_call"].finditer(body):
                called_func_name = call_match.group(1)
                if called_func_name != func_name:
                    called_funcs.add(called_func_name)
            func_data["calls"] = sorted(list(called_funcs))

            # Find module calls
            for module_match in PATTERNS["module_call"].finditer(body):
                module_name = module_match.group(1).split('_')[0]
                func_data["modules"].append(module_name)
                if module_name not in self.modules:
                    self.modules.append(module_name)

            # Find table calls
            for table_match in PATTERNS["table_call"].finditer(body):
                table_name = table_match.group(1)
                func_data["tables"].append(table_name)
                if table_name not in self.tables:
                    self.tables.append(table_name)

# Regular expressions for parsing C code elements
PATTERNS = {
    # Function Def: (return_type) (func_name) (params)
    "function_def": re.compile(
        r"([\w\s\*&]+?)\s+([A-Z]\d{4}_\w+)\s*\(([\s\S]*?)\)",
        re.DOTALL
    ),
    # Function Call: (func_name)
    "function_call": re.compile(r"\b([A-Z]\d{4}_\w+)\s*\("),
    # Module Call: CALLS(module_name_main) -> extract module_name
    "module_call": re.compile(r"CALLS\s*\(\s*(\w+?)(?:_Main)?\s*\)"),
    # Table Call: DBIO_...("...", "...", "TABLE_NAME", ...)
    "table_call": re.compile(r"DBIO_\w+\s*\([^,]+,[^,]+,\s*\"(C\w+)\""),
}


class CAnalyzerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("C Program Analyzer")
        self.geometry("1200x800")

        self.parser = None

        self._setup_menu()
        self._setup_main_layout()

    def _setup_menu(self):
        self.menu_bar = tk.Menu(self)
        self.config(menu=self.menu_bar)

        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open File...", command=self._open_file)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.destroy)

    def _setup_main_layout(self):
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Left Pane ---
        left_pane = ttk.Frame(main_pane, relief=tk.RIDGE)
        main_pane.add(left_pane, weight=1)

        search_frame = ttk.Frame(left_pane)
        search_frame.pack(fill=tk.X, padx=5, pady=5)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(fill=tk.X, expand=True, side=tk.LEFT, padx=(0, 5))
        search_button = ttk.Button(search_frame, text="Clear", command=lambda: self.search_var.set(""))
        search_button.pack(side=tk.RIGHT)

        notebook = ttk.Notebook(left_pane)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.function_tree = self._create_treeview(notebook, "Functions")
        self.function_tree.bind('<<TreeviewSelect>>', self._on_function_select)
        self.module_list = self._create_listbox(notebook, "Modules")
        self.table_list = self._create_listbox(notebook, "Tables")

        # --- Right Pane ---
        right_pane = ttk.PanedWindow(main_pane, orient=tk.VERTICAL)
        main_pane.add(right_pane, weight=3)

        self.source_code_view = self._create_text_widget(right_pane, weight=3, wrap="none")
        self.details_view = self._create_text_widget(right_pane, weight=1, wrap="word", state="disabled")

    def _create_treeview(self, parent, text):
        frame = ttk.Frame(parent)
        parent.add(frame, text=text)
        tree = ttk.Treeview(frame, show="tree")
        ysb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        xsb = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb.pack(side=tk.BOTTOM, fill=tk.X)
        return tree

    def _create_listbox(self, parent, text):
        frame = ttk.Frame(parent)
        parent.add(frame, text=text)
        listbox = tk.Listbox(frame)
        ysb = ttk.Scrollbar(frame, orient='vertical', command=listbox.yview)
        listbox.configure(yscrollcommand=ysb.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        return listbox

    def _create_text_widget(self, parent, weight, **kwargs):
        frame = ttk.Frame(parent)
        parent.add(frame, weight=weight)
        text_widget = tk.Text(frame, **kwargs)
        ysb = ttk.Scrollbar(frame, orient='vertical', command=text_widget.yview)
        xsb = ttk.Scrollbar(frame, orient='horizontal', command=text_widget.xview)
        text_widget.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb.pack(side=tk.BOTTOM, fill=tk.X)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return text_widget

    def _open_file(self):
        filepath = filedialog.askopenfilename(
            title="Select a C file",
            filetypes=(("C files", "*.c"), ("All files", "*.*"))
        )
        if not filepath:
            return

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()

            self.parser = CParser(code)
            self.parser.parse()
            self.title(f"C Program Analyzer - {os.path.basename(filepath)}")
            self._populate_views(code)

        except Exception as e:
            # Show error message to the user
            import tkinter.messagebox
            tkinter.messagebox.showerror("Error", f"Failed to open or parse file:\n{e}")

    def _clear_views(self):
        self.function_tree.delete(*self.function_tree.get_children())
        self.module_list.delete(0, tk.END)
        self.table_list.delete(0, tk.END)

        for view in [self.source_code_view, self.details_view]:
            view.config(state="normal")
            view.delete('1.0', tk.END)
            view.config(state="disabled")

    def _populate_views(self, code):
        self._clear_views()

        self.source_code_view.config(state="normal")
        self.source_code_view.insert('1.0', code)
        self.source_code_view.config(state="disabled")

        self._on_search() # Populate lists based on (empty) search term

        if self.parser.syntax_errors:
            errors = "\n".join(self.parser.syntax_errors)
            self.details_view.config(state="normal")
            self.details_view.insert('1.0', f"Syntax Errors Found:\n{errors}")
            self.details_view.config(state="disabled")


    def _on_search(self):
        if not self.parser: return
        term = self.search_var.get().lower()
        self._populate_function_tree(term)
        self._populate_module_list(term)
        self._populate_table_list(term)

    def _populate_module_list(self, filter_term=""):
        self.module_list.delete(0, tk.END)
        modules = sorted([m for m in self.parser.modules if filter_term in m.lower()])
        for module in modules:
            self.module_list.insert(tk.END, module)

    def _populate_table_list(self, filter_term=""):
        self.table_list.delete(0, tk.END)
        tables = sorted([t for t in self.parser.tables if filter_term in t.lower()])
        for table in tables:
            self.table_list.insert(tk.END, table)

    def _populate_function_tree(self, filter_term=""):
        self.function_tree.delete(*self.function_tree.get_children())
        if not self.parser: return

        if filter_term:
            # Show flat list if searching
            filtered_funcs = sorted([
                name for name in self.parser.functions
                if filter_term in name.lower()
            ])
            for func_name in filtered_funcs:
                self.function_tree.insert('', 'end', text=func_name)
        else:
            # Show call graph if not searching
            all_called = {c for f in self.parser.functions.values() for c in f['calls']}
            root_functions = sorted([name for name in self.parser.functions if name not in all_called])

            for root_func in root_functions:
                tree_data = self.parser.get_call_tree(root_func)
                if tree_data:
                    self._insert_tree_node('', tree_data)

    def _insert_tree_node(self, parent_id, node_data):
        node_id = self.function_tree.insert(parent_id, 'end', text=node_data['name'], open=True)
        for child_node in sorted(node_data['children'], key=lambda x: x['name']):
            self._insert_tree_node(node_id, child_node)

    def _on_function_select(self, event):
        selection = self.function_tree.selection()
        if not (selection and self.parser): return

        item_id = selection[0]
        func_name = self.function_tree.item(item_id, 'text').replace(" (Recursion)", "")

        if func_name in self.parser.functions:
            self._show_function_details(func_name)
            self._highlight_function_in_code(func_name)

    def _show_function_details(self, func_name):
        func_data = self.parser.functions[func_name]
        details = [
            f"FUNCTION: {func_name}",
            f"  Return Type: {func_data['return_type']}",
            f"  Parameters: {func_data['params']}",
            f"  Line: {func_data['line_number']}",
            "\n--- DOCS ---"
        ]
        details.extend([f"  @{tag}: {val}" for tag, val in func_data['docs'].items()])
        details.append("\n--- CALLS ---")
        details.append(f"  Functions: {', '.join(func_data['calls']) if func_data['calls'] else 'None'}")
        details.append(f"  Modules: {', '.join(func_data['modules']) if func_data['modules'] else 'None'}")
        details.append(f"  Tables: {', '.join(func_data['tables']) if func_data['tables'] else 'None'}")

        self.details_view.config(state="normal")
        self.details_view.delete('1.0', tk.END)
        self.details_view.insert('1.0', "\n".join(details))
        self.details_view.config(state="disabled")

    def _highlight_function_in_code(self, func_name):
        line_number = self.parser.functions[func_name]['line_number']

        self.source_code_view.tag_remove('highlight', '1.0', tk.END)
        self.source_code_view.tag_add('highlight', f'{line_number}.0', f'{line_number}.end+1c')
        self.source_code_view.tag_config('highlight', background='yellow')
        self.source_code_view.see(f'{line_number}.0')


if __name__ == "__main__":
    app = CAnalyzerApp()
    app.mainloop()
