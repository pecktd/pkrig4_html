# pkrig4 manual

The reference manual for [pkrig4](https://github.com/pecktd/pkrig4), published at
https://pecktd.github.io/pkrig4_html/.

The API reference is generated from pkrig4's own code (module docstrings,
`__all__`, signatures and docstrings), so documentation changes belong in pkrig4.
Hand-written pages live in `content/`.

## Build

Run with mayapy, pointing at the folder that contains `pkrig4`:

```
"C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" build.py --pkrig4-parent C:/dev
```

The site is written to `docs/`, which GitHub Pages serves. Commit `docs/` after
rebuilding.

| Path | Contents |
|---|---|
| `build.py` | Generator: layout, navigation, and the API reference from docstrings |
| `content/` | Hand-written pages (`index`, `concepts`, `development`) and extra prose for module pages (`node`) |
| `static/style.css` | Site stylesheet |
| `docs/` | Generated output |

Pages and their order are listed in `PAGES` in `build.py`.
