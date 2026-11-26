import argparse
import hashlib
import io
import os
import shutil
from xml.etree import ElementTree

from PyQt6 import QtWidgets
from PyQt6.uic.Compiler import compiler


def ui_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def untranslatable_ui(ui_path: str) -> io.BytesIO:
    tree = ElementTree.parse(ui_path)
    for string in tree.iter("string"):
        string.set("notr", "true")
    stream = io.BytesIO()
    tree.write(stream, encoding="utf-8")
    stream.seek(0)
    return stream


def compile_ui(ui_path: str, py_path: str) -> None:
    code = io.StringIO()
    winfo = compiler.UICompiler().compileUi(untranslatable_ui(ui_path), code)
    baseclass = winfo["baseclass"]
    if hasattr(QtWidgets, baseclass):
        baseclass = f"QtWidgets.{baseclass}"
    autoconnect = f"        QtCore.QMetaObject.connectSlotsByName({winfo['widgetname']})\n"
    source = code.getvalue()
    if source.count(autoconnect) != 1:
        raise RuntimeError(f"Unexpected connectSlotsByName call in compiled {ui_path!r}")
    with open(py_path, "w", encoding="utf-8") as f:
        f.write(source.replace(autoconnect, ""))
        f.write(f"\n\nUI_HASH = {ui_hash(ui_path)!r}\n")
        f.write(f"FormClass = {winfo['uiclass']}\n")
        f.write(f"BaseClass = {baseclass}\n")


def compile_dir(source: str, directory: str) -> int:
    shutil.rmtree(directory, ignore_errors=True)
    count = 0
    for root, _, files in os.walk(source):
        ui_files = [file for file in files if file.endswith(".ui")]
        if not ui_files:
            continue
        dest = os.path.join(directory, os.path.relpath(root, source))
        os.makedirs(dest, exist_ok=True)
        for file in ui_files:
            py_file = f"{file.removesuffix('.ui')}.py"
            compile_ui(os.path.join(root, file), os.path.join(dest, py_file))
            count += 1

    for root, _, files in os.walk(directory):
        if "__init__.py" not in files:
            open(os.path.join(root, "__init__.py"), "w").close()
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--source", default="res")
    parser.add_argument("-d", "--directory", default="compiled_res")
    args = parser.parse_args()

    count = compile_dir(args.source, args.directory)
    print(f"Compiled {count} .ui files into {args.directory!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
