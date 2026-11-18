# native_bootstrap.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
#
def preload_native_backends() -> None:
    # Windows/Python 3.13 native DLL guard:
    # PyTorch must be imported before PyQt6, otherwise torch\lib\c10.dll can fail with WinError 1114.
    import torch
    _ = torch.__version__
