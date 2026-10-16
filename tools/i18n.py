"""
Translation helper that works on Windows without installing GNU gettext.

    python tools/i18n.py          # find new strings, update locale/es/.../django.po, compile .mo
    python tools/i18n.py --check  # list strings that still have no Spanish translation

Workflow: wrap text in {% trans "..." %} / {% blocktrans %} in templates, or
_("...") in Python, run this script, fill in the empty msgstr "" lines in
locale/es/LC_MESSAGES/django.po (any text editor or Poedit), run it again.
"""
import re
import sys
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parent.parent
PO_PATH = ROOT / "locale" / "es" / "LC_MESSAGES" / "django.po"
SKIP_DIRS = {".venv", "venv", "node_modules", "staticfiles", "migrations", "tools", ".git"}

TRANS_RE = re.compile(r"""\{%\s*trans(?:late)?\s+(["'])(.+?)\1(?:\s+as\s+\w+)?\s*%\}""")
UNDERSCORE_RE = re.compile(r"""(?<![\w.])(?:_|gettext|gettext_lazy|pgettext)\(\s*(["'])((?:\\.|(?!\1).)+)\1\s*[,)]""")
UNDERSCORE_MULTI_RE = re.compile(r"""_\(\s*((?:"(?:[^"\\\n]|\\.)*"\s*)+)\)""")
BLOCK_RE = re.compile(r"\{%\s*blocktrans(?:late)?(.*?)%\}(.*?)\{%\s*endblocktrans(?:late)?\s*%\}", re.S)
VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _block_msg(text, trimmed):
    text = text.replace("%", "%%")
    text = VAR_RE.sub(lambda m: f"%({m.group(1)})s", text)
    if trimmed:
        text = " ".join(line.strip() for line in text.strip().splitlines() if line.strip())
    return text


def extract():
    found = {}  # (msgid, plural) -> set of locations
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        if path.suffix not in (".html", ".py", ".txt"):
            continue
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        if path.suffix in (".html", ".txt"):
            for m in TRANS_RE.finditer(src):
                found.setdefault((m.group(2), None), set()).add(rel)
            for m in BLOCK_RE.finditer(src):
                opts, body = m.group(1), m.group(2)
                trimmed = "trimmed" in opts
                if "{% plural %}" in body:
                    one, many = body.split("{% plural %}")
                    found.setdefault((_block_msg(one, trimmed), _block_msg(many, trimmed)), set()).add(rel)
                else:
                    found.setdefault((_block_msg(body, trimmed), None), set()).add(rel)
        for m in UNDERSCORE_RE.finditer(src):
            msg = m.group(2)
            if "\\" in msg:
                msg = msg.encode().decode("unicode_escape").encode("latin-1").decode("utf-8")
            found.setdefault((msg, None), set()).add(rel)
        if path.suffix == ".py":
            for m in UNDERSCORE_MULTI_RE.finditer(src):
                parts = re.findall(r'"((?:[^"\\\n]|\\.)*)"', m.group(1))
                if len(parts) > 1:
                    found.setdefault(("".join(parts), None), set()).add(rel)
    return found


def main():
    PO_PATH.parent.mkdir(parents=True, exist_ok=True)
    po = polib.pofile(str(PO_PATH)) if PO_PATH.exists() else polib.POFile()
    po.metadata.update({
        "Project-Id-Version": "frc-open-scout",
        "Language": "es",
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Plural-Forms": "nplurals=2; plural=(n != 1);",
    })
    existing = {(e.msgid, e.msgid_plural or None): e for e in po}
    found = extract()
    for (msgid, plural), locs in sorted(found.items()):
        entry = existing.get((msgid, plural))
        if entry is None:
            entry = polib.POEntry(msgid=msgid, msgstr="")
            if plural:
                entry.msgid_plural = plural
                entry.msgstr_plural = {0: "", 1: ""}
            po.append(entry)
        entry.occurrences = [(loc, "") for loc in sorted(locs)]
        entry.obsolete = False
    for key, entry in existing.items():
        if key not in found:
            entry.obsolete = True

    missing = [e.msgid for e in po if not e.obsolete and not e.translated()]
    if "--check" in sys.argv:
        print("\n".join(missing) or "All strings translated.")
        return
    po.save(str(PO_PATH))
    po.save_as_mofile(str(PO_PATH.with_suffix(".mo")))
    print(f"{len(found)} strings, {len(missing)} untranslated. Wrote {PO_PATH.relative_to(ROOT)} and .mo")


if __name__ == "__main__":
    main()
