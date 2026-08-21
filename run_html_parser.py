import os
import sys
import tkinter as tk

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from npa_processor.core.html_parser import main

if __name__ == "__main__":
    main()
