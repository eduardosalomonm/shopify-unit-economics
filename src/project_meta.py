"""Small, dependency-free source of truth for public release metadata."""

import os
import re


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_PATH = os.path.join(BASE, "VERSION")


def version():
    with open(VERSION_PATH, "r", encoding="ascii") as handle:
        value = handle.read().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("VERSION must contain a semantic version such as 1.0.0.")
    return value
