"""Anti-cheat checks on a candidate json_tokener.c, run before it is built.

A rewrite may only restructure the parser. These checks reject a candidate
that could pass the gate without behaving like the baseline: one that looks
at its surroundings, tampers with the checker or its files, switches off or
detects the sanitizers, gets around the allocation-failure wrappers, or
carries answers for the gate's inputs. Every rule compares the candidate with
the baseline source, so whatever the baseline itself does stays allowed.

1. Calls. Compiled without instrumentation, every function the candidate
   calls must be defined by the rest of json-c (except the ones in
   JSON_C_FORBIDDEN), called by the baseline, or a pure C library function
   in SAFE_CALLS. That shuts out the environment,
   files, time, randomness, threads, signals, exiting, printing, dlsym and
   __real_malloc (around the allocation wrappers).
2. Definitions. No global symbol the C library or the sanitizer runtime
   defines (malloc, getenv, __lsan_is_turned_off, ...), nothing starting
   with "__", no main or libFuzzer entry point.
3. Compiler tricks in its own code: attributes in FORBIDDEN_ATTRIBUTES (no
   sanitizing, constructors, optimisation settings, ...), inline asm, pragmas.
4. Build detection: macros in BUILD_MACROS that tell a sanitizer, fuzzer,
   coverage or optimised build apart.
5. Hard-coded inputs: a new string literal of MIN_LITERAL or more characters
   that occurs in one of the gate's inputs.
"""
import re
import shutil
import subprocess
from pathlib import Path

SAFE_CALLS = {
    "malloc", "calloc", "realloc", "free", "strdup", "strndup",
    "memcpy", "memmove", "memset", "memcmp", "memchr",
    "strlen", "strnlen", "strcmp", "strncmp", "strchr", "strrchr", "strstr", "strspn", "strcspn",
    "strtod", "strtof", "strtold", "strtol", "strtoll", "strtoul", "strtoull",
    "__isoc23_strtol", "__isoc23_strtoll", "__isoc23_strtoul", "__isoc23_strtoull",
    "snprintf", "vsnprintf", "__snprintf_chk", "__vsnprintf_chk",
    "__memcpy_chk", "__memmove_chk", "__memset_chk",
    "tolower", "toupper", "isdigit", "isxdigit", "isspace", "isalpha", "isalnum",
    "__ctype_b_loc", "__ctype_tolower_loc", "__ctype_toupper_loc",
    "abs", "labs", "llabs", "isnan", "isinf", "__isnan", "__isinf",
    "__assert_fail", "__errno_location", "__stack_chk_fail",
    "uselocale", "newlocale", "freelocale", "duplocale", "setlocale",
}
# json-c functions a tokener has no use for: files, logging, library-wide
# settings, randomness.
JSON_C_FORBIDDEN = {
    "json_object_from_fd", "json_object_from_fd_ex", "json_object_from_file", "json_object_to_fd",
    "json_object_to_file", "json_object_to_file_ext", "mc_debug", "mc_error", "mc_info", "mc_set_debug",
    "mc_set_syslog", "json_c_set_serialization_double_format", "json_global_set_string_hash",
    "json_c_get_random_seed", "_json_c_set_last_err",
}
FORBIDDEN_ATTRIBUTES = {
    "no_sanitize", "no_sanitize_address", "no_address_safety_analysis", "no_sanitize_thread",
    "no_sanitize_undefined", "no_sanitize_coverage", "no_stack_protector", "disable_sanitizer_instrumentation",
    "no_instrument_function", "no_profile_instrument_function", "optimize", "target", "constructor",
    "destructor", "section", "weak", "weakref", "alias", "ifunc", "visibility", "used", "cleanup",
}
BUILD_MACROS = {
    "__SANITIZE_ADDRESS__", "__SANITIZE_THREAD__", "__has_feature", "__has_include", "__has_include_next",
    "FUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION", "__OPTIMIZE__", "__OPTIMIZE_SIZE__", "__NO_INLINE__",
    "__COVERAGE__", "__SSP__", "__SSP_STRONG__", "__SSP_ALL__", "__FORTIFY_SOURCE",
}
ENTRY_POINTS = {"main", "LLVMFuzzerTestOneInput", "LLVMFuzzerInitialize", "LLVMFuzzerCustomMutator"}
MIN_LITERAL = 4
LINEMARKER = re.compile(r'^# (\d+) "((?:[^"\\]|\\.)*)"')
STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                          timeout=120, **kw)


def _symbols(nm_args, path):
    out = _run(["nm", *nm_args, str(path)]).stdout
    return {line.split()[-1].split("@")[0] for line in out.splitlines() if line.split()}


def _runtime_symbols(cc: str) -> set:
    """What the C library and the sanitizer runtimes define."""
    names = set()
    for lib in ("libc.so.6", "libm.so.6", "libasan.so", "libubsan.so"):
        path = _run([cc, f"-print-file-name={lib}"]).stdout.strip()
        if path and Path(path).is_file():
            names |= _symbols(["-D", "--defined-only"], Path(path).resolve())
    return names


def _own_lines(preprocessed: str, source: Path) -> str:
    """The lines of a preprocessor output that come from `source` itself."""
    keep, mine = [], False
    for line in preprocessed.split("\n"):
        m = LINEMARKER.match(line)
        if m:
            mine = Path(m.group(2)).name == source.name and Path(m.group(2)).parent.name == source.parent.name
            continue
        if mine:
            keep.append(line)
    return "\n".join(keep)


def _without_comments(text: str) -> str:
    """Source with comments and string literals blanked, for finding macros."""
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', " ", text, flags=re.S)


def _decode(literal: str) -> str:
    try:
        return bytes(literal, "latin-1").decode("unicode_escape", errors="replace")
    except (UnicodeEncodeError, ValueError):
        return literal


def _attributes(text: str) -> set:
    names = set()
    for body in re.findall(r"__attribute__\s*\(\((.*?)\)\)", text, flags=re.S):
        names |= set(re.findall(r"(?:^|,)\s*_*([A-Za-z]\w*?)_*\s*(?=\(|,|$)", body))
    return names


class _Look:
    """What one json_tokener.c calls, defines and contains."""

    def __init__(self, source: Path, cc: str, compile_args: list, where: Path):
        where.mkdir(parents=True, exist_ok=True)
        self.source = where / "json_tokener.c"  # a fixed name, so linemarkers can be told apart
        shutil.copy(source, self.source)
        obj = where / "plain.o"
        built = _run([cc, *compile_args, "-O0", "-c", str(self.source), "-o", str(obj)])
        self.compiles = built.returncode == 0
        self.calls = _symbols(["-u"], obj) if self.compiles else set()
        self.defines = _symbols(["--defined-only", "-g"], obj) if self.compiles else set()
        pre = _run([cc, *compile_args, "-E", str(self.source)]).stdout
        self.code = _own_lines(pre, self.source)
        raw = self.source.read_text(encoding="latin-1")
        self.identifiers = set(re.findall(r"[A-Za-z_]\w*", _without_comments(raw)))
        self.literals = {_decode(s) for s in STRING.findall(self.code)}
        self.attributes = _attributes(self.code)
        self.asm = bool(re.search(r"\b(?:asm|__asm|__asm__)\b", self.code))
        self.pragmas = sorted({line.strip() for line in self.code.split("\n") if line.lstrip().startswith("#pragma")}
                              | set(re.findall(r"_Pragma\s*\([^)]*\)", self.code)))


def find_cheats(candidate: Path, baseline_source: bytes, compile_args: list, rest_lib: Path, inputs: list,
                tmp: Path, cc: str = "gcc") -> list:
    """Reasons to reject the candidate, one line each; empty if none. A
    candidate that does not compile gives none: the build reports it."""
    base_file = tmp / "cheat-baseline-src.c"
    base_file.write_bytes(baseline_source)
    base = _Look(base_file, cc, compile_args, tmp / "cheat-baseline")
    new = _Look(candidate, cc, compile_args, tmp / "cheat-candidate")
    if not new.compiles:
        return []
    found = []

    allowed_calls = (_symbols(["--defined-only", "-g"], rest_lib) - JSON_C_FORBIDDEN) | base.calls | SAFE_CALLS
    calls = sorted(new.calls - allowed_calls)
    if calls:
        found.append("calls functions a rewrite of the tokener has no use for: " + ", ".join(calls))

    runtime = _runtime_symbols(cc)
    defines = sorted(name for name in new.defines - base.defines
                     if name in runtime or name in ENTRY_POINTS or name.startswith("__"))
    if defines:
        found.append("defines symbols that belong to the C library, the sanitizers or a test harness: "
                     + ", ".join(defines))

    attributes = sorted((new.attributes - base.attributes) & FORBIDDEN_ATTRIBUTES)
    if attributes:
        found.append("uses attributes that change how it is built or run: " + ", ".join(attributes))
    if new.asm and not base.asm:
        found.append("uses inline assembly")
    pragmas = sorted(set(new.pragmas) - set(base.pragmas))
    if pragmas:
        found.append("uses pragmas: " + "; ".join(p[:60] for p in pragmas))

    macros = sorted((new.identifiers - base.identifiers) & BUILD_MACROS)
    if macros:
        found.append("tests how it is being built (sanitizers, fuzzer, coverage or optimisation): "
                     + ", ".join(macros))

    text = "\n".join(_decode_input(line) for line in inputs)
    copied = sorted(lit for lit in new.literals - base.literals if len(lit) >= MIN_LITERAL and lit in text)
    if copied:
        found.append("contains text from the gate's inputs, as a hard-coded answer would: "
                     + ", ".join(repr(lit)[:60] for lit in copied[:10]))
    return found


def _decode_input(line: str) -> str:
    """An input line as the tokener sees it ("\\xNN" is one byte)."""
    return re.sub(r"\\x([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), line)
