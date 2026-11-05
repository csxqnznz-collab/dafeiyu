import os
import runpy
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
runpy.run_path(os.path.join(BASE, "桌宠.py"), run_name="__main__")
