"""Build the pkrig4 manual from pkrig4's own code.

The API reference on each module page is generated from that module's
docstring, ``__all__``, signatures and docstrings, so it always matches the
code. Hand-written pages and extra prose live in ``content/<slug>.html``.

Run with mayapy, with pkrig4's parent folder on the path (default ``C:/dev``)::

    "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" build.py [--pkrig4-parent C:/dev]

Output goes to ``docs/`` (served by GitHub Pages).
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import datetime
import enum
import html
import importlib
import inspect
import re
import shutil
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTENT = HERE / "content"
STATIC = HERE / "static"
OUTPUT = HERE / "docs"

# (section, [(slug, nav label, module or None)])
PAGES: list[tuple[str, list[tuple[str, str, str | None]]]] = [
    ("Getting started", [("index", "Overview", None), ("concepts", "Concepts", None)]),
    (
        "Core",
        [
            ("node", "node", "node"),
            ("core", "core", "core"),
            ("attribute", "attribute", "attribute"),
            ("naming", "naming", "naming"),
            ("constants", "constants", "constants"),
            ("shapes", "shapes", "shapes"),
            ("context", "context", "context"),
        ],
    ),
    (
        "Helpers",
        [
            ("joints", "joints", "joints"),
            ("controls", "controls", "controls"),
            ("constraints", "constraints", "constraints"),
            ("spaces", "spaces", "spaces"),
            ("attrs", "attrs", "attrs"),
            ("connect", "connect", "connect"),
            ("twist", "twist", "twist"),
            ("deform", "deform", "deform"),
            ("scene", "scene", "scene"),
        ],
    ),
    (
        "Data I/O",
        [
            ("data_io", "data_io", "data_io"),
            ("data_io-files", "data_io.files", "data_io.files"),
        ],
    ),
    (
        "Builder",
        [
            ("builder", "builder", "builder"),
            ("templates", "templates", "templates"),
        ],
    ),
    (
        "Components",
        [
            ("component", "component", "component"),
            ("components", "components", "components"),
            ("components-ik_solvers", "components.ik_solvers", "components.ik_solvers"),
            ("components-limb_ends", "components.limb_ends", "components.limb_ends"),
            ("ik", "ik", "ik"),
        ],
    ),
    (
        "Workspace window",
        [
            ("ui", "ui", "ui"),
            ("ui-model", "ui.model", "ui.model"),
            ("ui-actions", "ui.actions", "ui.actions"),
            ("ui-export", "ui.export", "ui.export"),
            ("ui-qt", "ui.qt", "ui.qt"),
        ],
    ),
    ("Development", [("development", "Development", None)]),
]

SECTION = re.compile(
    r"^(Args|Arguments|Parameters|Returns|Raises|Yields|Example|Examples|Note|Notes|Warning):\s*$"
)
ENTRY = re.compile(r"^(\*{0,2}[\w.]+)(?:\s*\(([^)]*)\))?\s*:\s*(.*)$")


# --------------------------------------------------------------------------- #
# Docstrings
# --------------------------------------------------------------------------- #


def inline(text: str) -> str:
    """Escape text and turn ``code`` / :role:`target` / `code` into <code>."""
    text = html.escape(text, quote=False)
    text = re.sub(r"``(.+?)``", r"<code>\1</code>", text)
    text = re.sub(
        r":(?:class|func|meth|mod|attr|data|obj):`(~?)([\w.]+)`",
        lambda m: f"<code>{m.group(2).split('.')[-1] if m.group(1) else m.group(2)}</code>",
        text,
    )
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def code_block(lines: list[str]) -> str:
    body = textwrap.dedent("\n".join(lines)).strip("\n")
    return f'<pre><code class="language-python">{html.escape(body, quote=False)}</code></pre>'


def _take_indented(lines: list[str], start: int) -> tuple[list[str], int]:
    """Lines from ``start`` until a non-blank line at column 0."""
    block, i = [], start
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
        block.append(lines[i])
        i += 1
    while block and not block[-1].strip():
        block.pop()
    return block, i


def _render_entries(lines: list[str]) -> str:
    entries: list[list[str]] = []
    for line in textwrap.dedent("\n".join(lines)).splitlines():
        match = ENTRY.match(line)
        if match and not line.startswith(" "):
            name, kind, text = match.groups()
            label = f"{name} ({kind})" if kind else name
            entries.append([label, text])
        elif entries and line.strip():
            entries[-1][1] += " " + line.strip()
        elif line.strip():
            entries.append(["", line.strip()])
    rows = "".join(
        f"<dt><code>{html.escape(name)}</code></dt><dd>{inline(text)}</dd>" if name
        else f"<dt></dt><dd>{inline(text)}</dd>"
        for name, text in entries
    )
    return f'<dl class="params">{rows}</dl>'


def clean(doc: str | None) -> str:
    """A raw ``__doc__`` with its indentation normalised (as ``inspect.getdoc`` does)."""
    return inspect.cleandoc(doc) if doc else ""


TABLE_RULE = re.compile(r"^=+(?: +=+)+\s*$")
"""A reStructuredText simple-table rule: ``=====  ======``."""


def _render_simple_table(lines: list[str], start: int) -> tuple[str, int]:
    """A reStructuredText simple table from its opening rule; returns the HTML and the next line.

    Columns start where the rule's ``=`` runs start. A third rule makes the
    rows before it a header. A row whose first column is blank continues the
    row above.
    """
    rule = lines[start]
    starts = [m.start() for m in re.finditer(r"=+", rule)]
    rows: list[list[str]] = []
    rules = 0
    header_rows = 0
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if TABLE_RULE.match(line):
            rules += 1
            i += 1
            if rules == 1 and _rule_before_blank(lines, i):
                header_rows = len(rows)  # a third rule follows: the rows so far are the header
                continue
            break
        if not line.strip():
            i += 1
            continue
        cells = [
            line[a : (starts[n + 1] if n + 1 < len(starts) else None)].strip()
            for n, a in enumerate(starts)
        ]
        if rows and not cells[0]:
            rows[-1] = [f"{old} {new}".strip() for old, new in zip(rows[-1], cells)]
        else:
            rows.append(cells)
        i += 1
    head = "".join(
        "<tr>" + "".join(f"<th>{inline(c)}</th>" for c in r) + "</tr>" for r in rows[:header_rows]
    )
    body = "".join(
        "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[header_rows:]
    )
    thead = f"<thead>{head}</thead>" if head else ""
    return f'<div class="table-wrap"><table>{thead}<tbody>{body}</tbody></table></div>', i


def _rule_before_blank(lines: list[str], start: int) -> bool:
    for line in lines[start:]:
        if not line.strip():
            return False
        if TABLE_RULE.match(line):
            return True
    return False


def render_doc(doc: str | None) -> str:
    """Render already-cleaned docstring text; pass raw ``__doc__`` through :func:`clean`."""
    if not doc:
        return ""
    lines = doc.expandtabs().splitlines()
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        section = SECTION.match(line)
        if section:
            flush()
            body, i = _take_indented(lines, i + 1)
            name = section.group(1)
            out.append(f'<div class="section-label">{name}</div>')
            if name in ("Args", "Arguments", "Parameters", "Raises"):
                out.append(_render_entries(body))
            elif name.startswith("Example"):
                out.append(code_block(body))
            else:
                out.append(render_doc(textwrap.dedent("\n".join(body))))
            continue
        if not para and line.startswith((" ", "\t")):
            body, i = _take_indented(lines, i)
            out.append(code_block(body))
            continue
        if not para and TABLE_RULE.match(line):
            html_table, i = _render_simple_table(lines, i)
            out.append(html_table)
            continue
        if not para and stripped.startswith(">>>"):
            block = []
            while i < len(lines) and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append(code_block(block))
            continue
        if not para and stripped.startswith(("- ", "* ")):
            items: list[str] = []
            while i < len(lines) and lines[i].strip():
                item = lines[i].strip()
                if item.startswith(("- ", "* ")):
                    items.append(item[2:])
                elif items:
                    items[-1] += " " + item
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>")
            continue
        if stripped.endswith("::"):
            para.append(stripped[:-1])
            flush()
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            body, i = _take_indented(lines, i)
            out.append(code_block(body))
            continue
        para.append(stripped)
        i += 1
    flush()
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Signatures
# --------------------------------------------------------------------------- #


def fmt_annotation(annotation: object) -> str | None:
    if annotation is inspect.Parameter.empty:
        return None
    if isinstance(annotation, str):
        return annotation
    forward = getattr(annotation, "__forward_arg__", None)  # typing.ForwardRef
    if forward is not None:
        return forward
    text = getattr(annotation, "__name__", None) or repr(annotation)
    return text.replace("typing.", "")


def fmt_default(value: object) -> str:
    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    shapes = sys.modules.get("pkrig4.shapes")
    if shapes is not None and dataclasses.is_dataclass(value):
        for key, shape in shapes.SHAPES.items():
            if shape is value:
                return f"shapes.{key.upper()}"
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def fmt_params(sig: inspect.Signature, skip_first: bool) -> tuple[list[str], str | None]:
    params = list(sig.parameters.values())
    if skip_first and params and params[0].name in ("self", "cls"):
        params = params[1:]
    parts: list[str] = []
    star_done = False
    for p in params:
        if p.kind is p.KEYWORD_ONLY and not star_done:
            parts.append("*")
            star_done = True
        name = p.name
        if p.kind is p.VAR_POSITIONAL:
            name = "*" + name
            star_done = True
        elif p.kind is p.VAR_KEYWORD:
            name = "**" + name
        annotation = fmt_annotation(p.annotation)
        text = f"{name}: {annotation}" if annotation else name
        if p.default is not p.empty:
            text += f" = {fmt_default(p.default)}" if annotation else f"={fmt_default(p.default)}"
        parts.append(text)
    return parts, fmt_annotation(sig.return_annotation)


def render_signature(kind: str, name: str, anchor: str, sig: inspect.Signature | None,
                     skip_first: bool = False, bare: bool = False) -> str:
    head = (f'<span class="kind">{kind}</span> ' if kind else "") + (
        f'<a class="anchor" href="#{anchor}"><span class="name">{html.escape(name)}</span></a>'
    )
    if sig is None or bare:
        return f'<pre class="sig">{head}</pre>'
    parts, returns = fmt_params(sig, skip_first)
    one_line = ", ".join(parts)
    tail = f" -&gt; {html.escape(returns)}" if returns else ""
    if len(name) + len(one_line) < 80:
        body = f"({html.escape(one_line)})"
    else:
        body = "(\n" + "".join(f"    {html.escape(p)},\n" for p in parts) + ")"
    return f'<pre class="sig">{head}{body}{tail}</pre>'


def signature_or_none(obj: object) -> inspect.Signature | None:
    try:
        return inspect.signature(obj)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# API items
# --------------------------------------------------------------------------- #


def own_doc(cls: type) -> str | None:
    doc = cls.__dict__.get("__doc__")
    # Placeholders Python writes for undocumented NamedTuples and Enums.
    if not doc or doc.strip() == "An enumeration." or re.fullmatch(rf"{cls.__name__}\(.*\)", doc.strip()):
        return None
    return doc


def field_docs(cls: type) -> dict[str, str]:
    """Docstrings written under class attributes (NamedTuple / dataclass fields)."""
    try:
        source = textwrap.dedent(inspect.getsource(cls))
    except (OSError, TypeError):
        return {}
    body = ast.parse(source).body[0].body  # type: ignore[attr-defined]
    docs: dict[str, str] = {}
    for current, following in zip(body, body[1:]):
        target = current.target if isinstance(current, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and isinstance(following, ast.Expr) and isinstance(
            following.value, ast.Constant
        ) and isinstance(following.value.value, str):
            docs[target.id] = inspect.cleandoc(following.value.value)
    return docs


def render_member(cls: type, name: str, value: object) -> str | None:
    anchor = f"{cls.__name__}.{name}"
    if isinstance(value, property):
        returns = fmt_annotation(inspect.signature(value.fget).return_annotation) if value.fget else None
        settable = " (settable)" if value.fset else ""
        sig = f'<pre class="sig"><span class="kind">property</span> <a class="anchor" href="#{anchor}"><span class="name">{name}</span></a>'
        sig += f": {html.escape(returns)}" if returns else ""
        sig += f'<span class="kind">{settable}</span></pre>'
        doc = value.fget.__doc__ if value.fget else None
        return f'<div class="member" id="{anchor}">{sig}{render_doc(clean(doc))}</div>'
    kind, func = "def", value
    if isinstance(value, staticmethod):
        kind, func = "staticmethod", value.__func__
    elif isinstance(value, classmethod):
        kind, func = "classmethod", value.__func__
    if not inspect.isfunction(func):
        return None
    sig = render_signature(kind, name, anchor, signature_or_none(func), skip_first=True)
    return f'<div class="member" id="{anchor}">{sig}{render_doc(clean(func.__doc__))}</div>'


def render_class(cls: type) -> str:
    name = cls.__name__
    parts = [f'<div class="api-item" id="{name}">']
    is_namedtuple = issubclass(cls, tuple) and hasattr(cls, "_fields")
    is_enum = issubclass(cls, enum.Enum)

    if is_enum:
        parts.append(render_signature("class", name, name, None, bare=True))
    else:
        sig = signature_or_none(cls)
        if sig is not None:
            sig = sig.replace(return_annotation=inspect.Signature.empty)  # constructors return None
        parts.append(render_signature("class", name, name, sig))

    bases = [b.__name__ for b in cls.__bases__ if b not in (object, tuple) and not b.__name__.startswith("_")]
    if is_namedtuple:
        bases = ["NamedTuple"]
    if bases:
        parts.append(f'<p class="bases">Bases: {", ".join(f"<code>{b}</code>" for b in bases)}</p>')
    parts.append(render_doc(clean(own_doc(cls))))

    if is_namedtuple or dataclasses.is_dataclass(cls):
        docs = field_docs(cls)
        annotations = cls.__dict__.get("__annotations__", {})
        rows = []
        for field in getattr(cls, "_fields", None) or [f.name for f in dataclasses.fields(cls)]:
            default = ""
            if dataclasses.is_dataclass(cls):
                f = next(f for f in dataclasses.fields(cls) if f.name == field)
                if f.default is not dataclasses.MISSING:
                    default = html.escape(fmt_default(f.default))
            rows.append(
                f"<tr><td><code>{field}</code></td><td><code>{html.escape(fmt_annotation(annotations.get(field, inspect.Parameter.empty)) or '')}</code></td>"
                + (f"<td><code>{default}</code></td>" if dataclasses.is_dataclass(cls) else "")
                + f"<td>{inline(docs.get(field, ''))}</td></tr>"
            )
        head = "<th>Field</th><th>Type</th>" + ("<th>Default</th>" if dataclasses.is_dataclass(cls) else "") + "<th></th>"
        parts.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    if is_enum:
        rows = "".join(
            f"<tr><td><code>{member.name}</code></td><td><code>{html.escape(repr(member.value))}</code></td></tr>"
            for member in cls  # type: ignore[attr-defined]
        )
        parts.append(f'<div class="table-wrap"><table><thead><tr><th>Member</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table></div>')

    members = []
    for member_name, value in vars(cls).items():
        if member_name.startswith("_") or (is_enum and not callable(value) and not isinstance(value, (property, classmethod, staticmethod))):
            continue
        if is_namedtuple and member_name in getattr(cls, "_fields", ()):
            continue
        rendered = render_member(cls, member_name, value)
        if rendered:
            members.append(rendered)
    if members:
        parts.append(f'<div class="members">{"".join(members)}</div>')
    parts.append("</div>")
    return "\n".join(parts)


def render_function(func: object, name: str) -> str:
    sig = render_signature("def", name, name, signature_or_none(func))
    return f'<div class="api-item" id="{name}">{sig}{render_doc(clean(getattr(func, "__doc__", None)))}</div>'


def render_value(name: str, value: object) -> str:
    if isinstance(value, dict):
        keys = ", ".join(f"<code>{html.escape(str(k))}</code>" for k in value)
        value_type = type(next(iter(value.values()))).__name__ if value else "object"
        sig = f'<pre class="sig"><a class="anchor" href="#{name}"><span class="name">{name}</span></a>: dict[str, {value_type}]</pre>'
        return f'<div class="api-item" id="{name}">{sig}<p>Keys: {keys}</p></div>'
    sig = f'<pre class="sig"><a class="anchor" href="#{name}"><span class="name">{name}</span></a> = {html.escape(fmt_default(value))}</pre>'
    return f'<div class="api-item" id="{name}">{sig}</div>'


def module_link(module: object) -> str:
    """A link to a submodule's page if the manual has one, else its name."""
    dotted = getattr(module, "__name__", "").removeprefix("pkrig4.")
    slugs = {mod: slug for _, pages in PAGES for slug, _, mod in pages if mod}
    label = f"<code>{html.escape(dotted)}</code>"
    return f'<a href="{slugs[dotted]}.html">{label}</a>' if dotted in slugs else label


def render_reference(module: object) -> str:
    exported = list(getattr(module, "__all__", []))
    # Submodules listed in __all__ are links, not reference entries.
    submodules = [getattr(module, n) for n in exported if inspect.ismodule(getattr(module, n))]
    names = [n for n in exported if not inspect.ismodule(getattr(module, n))]
    modules_html = ""
    if submodules:
        links = ", ".join(module_link(m) for m in submodules)
        modules_html = f'<p class="modules">Modules: {links}</p>'
    if not names:
        return modules_html
    items = []
    for name in names:
        obj = getattr(module, name)
        if inspect.isclass(obj):
            items.append(render_class(obj))
        elif callable(obj):
            items.append(render_function(obj, name))
        else:
            items.append(render_value(name, obj))
    toc = "".join(f'<li><a href="#{n}">{n}</a></li>' for n in names)
    return (
        f'<h2 id="reference">Reference</h2>{modules_html}<ul class="toc-inline">{toc}</ul>'
        f'<div class="api">{"".join(items)}</div>'
    )


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

LAYOUT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" media="(prefers-color-scheme: light)" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
<link rel="stylesheet" media="(prefers-color-scheme: dark)" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<link rel="stylesheet" href="style.css?v={asset_version}">
</head>
<body>
<div class="page">
<aside class="sidebar" id="sidebar">
<a class="brand" href="index.html"><b>pkrig4</b><span>v{version} · Maya rigging framework</span></a>
<button class="menu-toggle" type="button" aria-expanded="false" aria-controls="sidebar">Menu</button>
<nav aria-label="Manual">
{nav}
</nav>
</aside>
<main>
{body}
<footer>Generated from pkrig4 {version} on {date}. The reference is built from the code's own docstrings.</footer>
</main>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script>
hljs.highlightAll();
const toggle = document.querySelector(".menu-toggle");
toggle.addEventListener("click", () => {{
  const open = document.getElementById("sidebar").classList.toggle("open");
  toggle.setAttribute("aria-expanded", String(open));
}});
</script>
</body>
</html>
"""


def render_nav(active: str) -> str:
    out = []
    for section, pages in PAGES:
        out.append(f'<div class="nav-section">{section}</div>')
        for slug, label, module in pages:
            text = f"<code>{label}</code>" if module else label
            current = ' class="nav-link active" aria-current="page"' if slug == active else ' class="nav-link"'
            out.append(f'<a{current} href="{slug}.html">{text}</a>')
    return "\n".join(out)


def read_content(slug: str) -> str:
    path = CONTENT / f"{slug}.html"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def module_page(slug: str, module_name: str) -> tuple[str, str]:
    module = importlib.import_module(f"pkrig4.{module_name}")
    doc = inspect.getdoc(module) or ""
    summary, _, rest = doc.partition("\n\n")
    body = [
        f'<div class="eyebrow">pkrig4.{module_name}</div>',
        f"<h1><code>{module_name}</code></h1>",
        f'<p class="lede">{inline(summary.replace(chr(10), " "))}</p>',
        render_doc(rest),
        read_content(slug),
        render_reference(module),
    ]
    return f"pkrig4.{module_name}", "\n".join(body)


def build(pkrig4_parent: str) -> None:
    import maya.standalone

    maya.standalone.initialize()
    try:
        from maya import cmds

        if cmds.about(version=True) is None:
            raise SystemExit(f"maya.cmds is a stub module ({cmds.__file__}); fix PYTHONPATH.")
        for name in [m for m in sys.modules if m == "pkrig4" or m.startswith("pkrig4.")]:
            del sys.modules[name]
        sys.path.insert(0, pkrig4_parent)
        import pkrig4

        version = pkrig4.__version__
        date = datetime.date.today().isoformat()
        if OUTPUT.exists():
            shutil.rmtree(OUTPUT)
        OUTPUT.mkdir()
        shutil.copy(STATIC / "style.css", OUTPUT / "style.css")
        (OUTPUT / ".nojekyll").write_text("", encoding="utf-8")

        for _, pages in PAGES:
            for slug, label, module_name in pages:
                if module_name:
                    title, body = module_page(slug, module_name)
                else:
                    title, body = label, read_content(slug).replace("{version}", version)
                page = LAYOUT.format(
                    title=html.escape(f"{title} · pkrig4" if slug != "index" else "pkrig4 manual"),
                    version=version,
                    nav=render_nav(slug),
                    body=body,
                    date=date,
                    asset_version=f"{version}-{date}",  # new URL per build, so browsers never reuse an old stylesheet
                )
                (OUTPUT / f"{slug}.html").write_text(page, encoding="utf-8", newline="\n")
                print(f"  {slug}.html")
        print(f"Built pkrig4 {version} manual -> {OUTPUT}")
    finally:
        maya.standalone.uninitialize()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pkrig4-parent", default="C:/dev", help="folder that contains pkrig4/")
    build(parser.parse_args().pkrig4_parent)
