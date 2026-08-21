import os
import sys
import tkinter as tk


def bootstrap_project_root():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


bootstrap_project_root()


def run_revision_app():
    from npa_processor.processing.revision_processor import App

    root = tk.Tk()
    app = App(root)
    root.mainloop()


def run_html_to_json_app():
    from npa_processor.core.html_parser import main

    main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--html-to-json":
        run_html_to_json_app()
    else:
        run_revision_app()


if __name__ == "__main__":
    main()
