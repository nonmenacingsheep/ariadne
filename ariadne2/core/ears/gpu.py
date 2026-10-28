"""Making a card that exists actually usable for Whisper. Trimmed from 1.x gpu.py.

A card and a driver are not enough: cuBLAS and cuDNN arrive as pip wheels
under site-packages/nvidia/*/lib, which the loader does not search, and
LD_LIBRARY_PATH cannot usefully be set from inside a running process. So they
are opened here by absolute path, which puts them in the process and lets the
later dlopen-by-soname find them already loaded.
"""
from __future__ import annotations

import os
import sys

CUDA_LIBS = ("libcublas.so.12", "libcudnn.so.9")
CUDA_WHEELS = ("nvidia-cublas-cu12", "nvidia-cudnn-cu12")     # what to pip install for them


def nvidia_lib_dirs() -> list[str]:
    dirs = []
    for base in sys.path:
        root = os.path.join(base, "nvidia")
        if os.path.isdir(root):
            for entry in sorted(os.listdir(root)):
                lib = os.path.join(root, entry, "lib")
                if os.path.isdir(lib):
                    dirs.append(lib)
    return dirs


def preload_cuda() -> bool:
    """Load the CUDA libraries by full path. True when all are now in the process."""
    import ctypes
    ok = True
    for soname in CUDA_LIBS:
        try:
            ctypes.CDLL(soname, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
            continue                                   # already reachable
        except OSError:
            pass
        found = next((os.path.join(d, soname) for d in nvidia_lib_dirs()
                      if os.path.exists(os.path.join(d, soname))), None)
        try:
            if found is None:
                raise OSError(soname)
            ctypes.CDLL(found, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
        except OSError:
            ok = False
    return ok


def cuda_works() -> bool:
    """Whether CUDA can actually be used, rather than merely reported.

    CTranslate2 happily lists a device with cuBLAS missing and only fails when
    the first transcription runs, which is how this once claimed the GPU was in
    use and then fell over on the first clip.
    """
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() < 1:
            return False
    except Exception:
        return False
    return preload_cuda()
