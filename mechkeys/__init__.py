"""MechKeys: mechanical keyboard sounds for every keystroke on Windows."""

import os

# MechKeys never does linear algebra, but numpy's OpenBLAS otherwise starts one
# worker thread per CPU core and commits a buffer for each (~800 MB on 24 cores).
# This must run before numpy is first imported.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

__version__ = "1.1.0"
