"""Verify the ctypes layout against the official header, field by field.

Point AMS2_SHM_HEADER at the SharedMemory.h that ships with the game, e.g.
  ...\\steamapps\\common\\Automobilista 2\\Support\\SharedMemory\\AMS2_SharedMemoryExampleApp\\SharedMemory.h
Requires g++ (or set CXX). Skipped when either is missing.
"""
import ctypes as C
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from ams2season.shm import ParticipantInfo, SharedMemory

HEADER = os.environ.get("AMS2_SHM_HEADER", "")
CXX = os.environ.get("CXX", "g++")


def _program(header: str) -> str:
    lines = ['#include <cstdio>', '#include <cstddef>', f'#include "{header}"', "int main(){"]
    lines.append('printf("SharedMemory %zu\\n", sizeof(SharedMemory));')
    lines.append('printf("ParticipantInfo %zu\\n", sizeof(ParticipantInfo));')
    for name, _ in SharedMemory._fields_:
        lines.append(f'printf("{name} %zu\\n", offsetof(SharedMemory, {name}));')
    for name, _ in ParticipantInfo._fields_:
        lines.append(f'printf("P.{name} %zu\\n", offsetof(ParticipantInfo, {name}));')
    lines.append("return 0;}")
    return "\n".join(lines)


@pytest.mark.skipif(not HEADER or not Path(HEADER).exists() or not shutil.which(CXX),
                    reason="set AMS2_SHM_HEADER to the game's SharedMemory.h and have g++ available")
def test_layout_matches_header():
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "layout.cpp"
        exe = Path(td) / "layout"
        src.write_text(_program(str(Path(HEADER).resolve())))
        subprocess.run([CXX, "-std=c++11", "-w", str(src), "-o", str(exe)], check=True)
        out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout

    expected = dict(line.rsplit(" ", 1) for line in out.strip().splitlines())
    mismatches = []
    if int(expected["SharedMemory"]) != C.sizeof(SharedMemory):
        mismatches.append(("sizeof(SharedMemory)", expected["SharedMemory"], C.sizeof(SharedMemory)))
    if int(expected["ParticipantInfo"]) != C.sizeof(ParticipantInfo):
        mismatches.append(("sizeof(ParticipantInfo)", expected["ParticipantInfo"], C.sizeof(ParticipantInfo)))
    for name, _ in SharedMemory._fields_:
        ours = getattr(SharedMemory, name).offset
        if int(expected[name]) != ours:
            mismatches.append((name, expected[name], ours))
    for name, _ in ParticipantInfo._fields_:
        ours = getattr(ParticipantInfo, name).offset
        if int(expected[f"P.{name}"]) != ours:
            mismatches.append((f"ParticipantInfo.{name}", expected[f"P.{name}"], ours))
    assert not mismatches, mismatches
