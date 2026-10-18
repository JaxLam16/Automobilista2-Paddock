"""Read-only Crew Chief SDK observer, using the public self-describing layout.

Protocol: gitlab.com/mr_belowski/CrewChiefV4, SharedMemory.cs and CrewChiefV4SDK.
Independent reader implementation; it never creates a mapping or alters settings.
"""
from __future__ import annotations

import ctypes as C
import os
import struct
import time


REGION = r"Local\CrewChiefV4"
SIZE = 500000


def decode(data):
    if len(data) < 16:
        raise ValueError("Crew Chief SDK header is incomplete.")
    version, count, headers, buffer = struct.unpack_from("<4i", data)
    if (version != 1 or not 1 <= count <= 128 or headers < 16
            or headers+count*400 > buffer or not buffer < len(data)):
        raise ValueError("Unknown Crew Chief SDK layout.")
    variables = {}
    for i in range(count):
        offset = headers+i*400
        kind, width, position, length = struct.unpack_from("<4i", data, offset)
        name = data[offset+16:offset+80].decode("utf-16-le").split("\0", 1)[0]
        if not name or name in variables or width <= 0 or length <= 0 or position < 0 or buffer+position+width*length > len(data):
            raise ValueError("Invalid Crew Chief SDK variable table.")
        variables[name] = (kind, width, buffer+position, length)
    def read(name, kind=3, width=4, index=0):
        item = variables.get(name)
        if item is None or item[0] != kind or item[1] != width or not 0 <= index < item[3]:
            raise ValueError("Missing or unsupported SDK variable: " + name)
        at = item[2]+index*width
        if kind == 1:
            if data[at] not in (0, 1):
                raise ValueError("Invalid SDK playing flag.")
            return bool(data[at])
        return struct.unpack_from("<i", data, at)[0]
    result = {"update_status": read("updateStatus"), "tick": read("tickCount"),
              "tick_ms": read("tickRate"), "playing": read("phraseIsPlaying", 1, 1),
              "sequence": None, "voice_type": None, "phrase": ""}
    if not 0 <= result["update_status"] <= 2 or not 0 <= result["tick_ms"] <= 10000:
        raise ValueError("Invalid SDK update state.")
    index = read("lastPhraseIndex")
    total = read("numTotalPhrases")
    if total > 0:
        result["sequence"] = read("phraseSequenceIds", index=index)
        result["voice_type"] = read("phrasesVoiceType", index=index)
        item = variables.get("phrasePhrases")
        if item is None or item[0] != 8 or item[1] != 8192 or not 0 <= index < item[3]:
            raise ValueError("Unsupported SDK subtitle buffer.")
        at = item[2]+index*item[1]
        result["phrase"] = data[at:at+item[1]].decode("utf-16-le").split("\0", 1)[0].strip()
    return result


class ReadOnlyMapping:
    def __init__(self, name=REGION):
        self.name, self.handle, self.view = name, None, None
        self.k32 = None
        if os.name == "nt":
            self.k32 = C.WinDLL("kernel32", use_last_error=True)
            self.k32.OpenFileMappingW.argtypes = [C.c_uint32, C.c_bool, C.c_wchar_p]
            self.k32.OpenFileMappingW.restype = C.c_void_p
            self.k32.MapViewOfFile.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_size_t]
            self.k32.MapViewOfFile.restype = C.c_void_p
            self.k32.UnmapViewOfFile.argtypes = [C.c_void_p]
            self.k32.CloseHandle.argtypes = [C.c_void_p]

    def read(self):
        if not self.k32:
            return None
        if not self.view:
            self.handle = self.k32.OpenFileMappingW(4, False, self.name)  #FILE_MAP_READ
            if not self.handle:
                return None
            self.view = self.k32.MapViewOfFile(self.handle, 4, 0, 0, SIZE)
            if not self.view:
                self.close()
                return None
        return C.string_at(self.view, SIZE)

    def close(self):
        if self.view:
            self.k32.UnmapViewOfFile(self.view)
        if self.handle:
            self.k32.CloseHandle(self.handle)
        self.view = self.handle = None


class CrewChiefObserver:
    def __init__(self, reader=None, clock=time.monotonic):
        self.reader = reader or ReadOnlyMapping()
        self.clock = clock
        self.tick = None
        self.changed_at = None
        self.advancing = False
        self.value = {"available": False, "busy": None, "reason": "not_observed"}

    def poll(self):
        now = self.clock()
        try:
            raw = self.reader.read()
            if raw is None:
                self.tick, self.changed_at, self.advancing = None, None, False
                self.value = {"available": False, "busy": None, "reason": "sdk_disabled_or_closed"}
                return self.value
            state = decode(raw)
            if self.tick is None or state["tick"] < self.tick:
                self.advancing = False
            elif state["tick"] != self.tick:
                self.advancing = True
            if state["tick"] != self.tick:
                self.changed_at = now
            self.tick = state["tick"]
            fresh = self.advancing and self.changed_at is not None and now-self.changed_at <= max(.5, min(1.5, state["tick_ms"]*.003))
            ready = fresh and state["update_status"] == 2
            self.value = {"available": ready, "busy": state["playing"] if ready else None,
                          "reason": "observed" if ready else "waiting_for_fresh_sdk",
                          "sequence": state["sequence"], "voice_type": state["voice_type"],
                          "phrase": state["phrase"]}
        except (OSError, ValueError, UnicodeError, struct.error) as exc:
            self.value = {"available": False, "busy": None, "reason": "invalid_sdk", "error": str(exc)}
            self.reader.close()
            self.tick, self.changed_at, self.advancing = None, None, False
        return self.value

    def close(self):
        self.reader.close()
