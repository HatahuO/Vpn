#!/usr/bin/env python3
"""Assemble l'artefact (page HTML autonome) à partir de programme_lfi_2027.json et de artifact_template.html.

Sortie : un fragment prêt à publier (sans <html>/<head>) et, avec --wrapped, une version complète pour test local.
"""
import argparse, json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--data", default="programme_lfi_2027.json")
ap.add_argument("--template", default="artifact_template.html")
ap.add_argument("--out", required=True)
ap.add_argument("--wrapped", help="écrit aussi une version complète (doctype, head) pour test local")
a = ap.parse_args()

d = json.loads(Path(a.data).read_text(encoding="utf-8"))
compact = {
    "generated_at": d["meta"]["generated_at"],
    "expected": d["meta"]["expected_measures"],
    "documents": [
        {k: doc[k] for k in ("code", "kind", "title", "short", "url", "units")} for doc in d["documents"]
    ],
}
payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = Path(a.template).read_text(encoding="utf-8").replace("__DATA__", payload)
Path(a.out).write_text(html, encoding="utf-8")
print(f"{a.out}: {len(html)/1e6:.2f} Mo")
if a.wrapped:
    head = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light;'
            'padding:env(safe-area-inset-top,0px) 0 env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui}'
            'img{max-width:100%}[hidden]{display:none!important}</style></head><body>')
    Path(a.wrapped).write_text(head + html + "</body></html>", encoding="utf-8")
