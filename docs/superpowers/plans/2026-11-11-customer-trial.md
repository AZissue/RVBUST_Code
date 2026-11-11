# MCC Customer Trial Implementation Plan

**Goal:** Build a Windows x64 trial bundle and a runnable Python stitching kit.

**Architecture:** Build the existing industrial application with PyInstaller and a trial marker that hides experimental UI and the internal stool fixture. Ship a separate Python kit reusing a snapshot of the production core, with synthetic reproducible inputs and three stitching entry points.

**Tech Stack:** Python 3.10, PyInstaller, PySide6, NumPy, Open3D, SciPy and OpenCV.

**Spec:** Customer trial scope in the conversation, revised to Python only on 2026-11-11.

1. Build the trial application and launch the frozen executable with and without the offline argument.
2. Implement and verify fixed extrinsics, marker chain and FPFH chain examples using synthetic data.
3. Stage application, Python kit, quick start and validation notes in a fresh output directory. Verify ZIP content and checksum.
