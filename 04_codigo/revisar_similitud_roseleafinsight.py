#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auditoría visual complementaria del dataset RoseLeafInsight.

Propósito: localizar PARES CANDIDATOS de imágenes visualmente similares
tras una auditoría de duplicados exactos. NO excluye archivos, NO modifica
el ZIP de origen y NO decide que dos hojas sean la misma fotografía.

Requisitos: Python 3.9+, Pillow (py -m pip install pillow).

Ejemplo en PowerShell:
  py revisar_similitud_roseleafinsight.py "RoseLeafInsight Original Image.zip" \
    --inventario auditoria_RoseLeafInsight/inventario_auditado.csv \
    --salida revision_similitud_RoseLeafInsight --umbral 4

El análisis usa hashes perceptuales dHash (64 bits), sensibles a la forma
visual aproximada, y aHash para ordenar la revisión. Un dHash parecido NO
prueba que dos imágenes sean duplicadas; se necesita inspección humana.
"""

import argparse
import csv
import io
import json
import sys
import heapq
import zipfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def dhash(gray):
    reduced = gray.resize((9, 8), Image.Resampling.LANCZOS)
    data = list(reduced.get_flattened_data() if hasattr(reduced, "get_flattened_data") else reduced.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | int(data[y * 9 + x] > data[y * 9 + x + 1])
    return bits


def ahash(gray):
    reduced = gray.resize((8, 8), Image.Resampling.LANCZOS)
    vals = list(reduced.get_flattened_data() if hasattr(reduced, "get_flattened_data") else reduced.getdata())
    avg = sum(vals) / len(vals)
    bits = 0
    for value in vals:
        bits = (bits << 1) | int(value >= avg)
    return bits


def label_from_path(path):
    # Solo se usa cuando no hay inventario. Con inventario se conservan sus clases.
    low = path.lower().replace("_", " ")
    if "black spot" in low:
        return "Black Spot"
    if "yellow mosaic" in low:
        return "Yellow Mosaic Virus"
    if "healthy" in low or "fresh leaf" in low:
        return "Healthy"
    if "insect" in low and "hole" in low:
        return "Insect Hole"
    return "SIN_CLASE_IDENTIFICABLE"


def load_inventory(path):
    data = {}
    if not path:
        return data
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("ruta_en_zip") or "").replace("\\", "/").strip("/")
            if key:
                data[key] = row
    return data


def font():
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, 17)
        except OSError:
            continue
    return ImageFont.load_default()


def thumb(zf, name, size=(280, 230)):
    raw = zf.read(name)
    with Image.open(io.BytesIO(raw)) as image:
        rgb = ImageOps.exif_transpose(image.convert("RGB"))
        rgb.thumbnail(size, Image.Resampling.LANCZOS)
        out = Image.new("RGB", size, "white")
        out.paste(rgb, ((size[0]-rgb.width)//2, (size[1]-rgb.height)//2))
        return out


def make_contact(zf, pairs, records, target, max_pairs):
    selected = pairs[:max_pairs]
    if not selected:
        return 0
    fw = font()
    width, header, row_height = 840, 90, 280
    sheet = Image.new("RGB", (width, header + len(selected) * row_height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 14), "RoseLeafInsight: pares CANDIDATOS para revisión manual", fill="black", font=fw)
    draw.text((16, 47), "Similitud de hash no equivale a duplicado confirmado", fill="black", font=fw)
    for idx, pair in enumerate(selected):
        a, b = records[pair["i"]], records[pair["j"]]
        y0 = header + idx * row_height
        for k, item in enumerate([a, b]):
            x0 = 22 + k * 405
            sheet.paste(thumb(zf, item["zipname"]), (x0, y0))
            draw.text((x0, y0 + 236), f"{idx+1}{'A' if k==0 else 'B'}: {item['clase'][:23]}", fill="black", font=fw)
        draw.text((18, y0 + 259), f"dHash={pair['distancia_dhash']} | aHash={pair['distancia_ahash']} | clases distintas={pair['clases_distintas']}", fill="black", font=fw)
    sheet.save(target, optimize=True)
    return len(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip_original", help="ZIP original de RoseLeafInsight; no se modifica")
    parser.add_argument("--inventario", help="CSV inventario_auditado.csv de la auditoría anterior")
    parser.add_argument("--salida", default="revision_similitud_RoseLeafInsight")
    parser.add_argument("--umbral", type=int, default=4, help="Distancia Hamming máxima dHash (por defecto 4)")
    parser.add_argument("--umbral-ahash", type=int, default=12, help="Distancia Hamming máxima aHash (por defecto 12)")
    parser.add_argument("--max-pares", type=int, default=3000, help="Máximo de pares priorizados guardados (por defecto 3000)")
    parser.add_argument("--max-miniaturas", type=int, default=12, help="Pares en la imagen de revisión (por defecto 12)")
    args = parser.parse_args()
    if not 0 <= args.umbral <= 12:
        parser.error("--umbral debe estar entre 0 y 12 (se sugiere 4)")
    if not 0 <= args.umbral_ahash <= 64:
        parser.error("--umbral-ahash debe estar entre 0 y 64")
    if args.max_pares < 1:
        parser.error("--max-pares debe ser positivo")
    target = Path(args.salida)
    target.mkdir(parents=True, exist_ok=True)
    inventory = load_inventory(args.inventario)
    records, errors = [], []

    with zipfile.ZipFile(args.zip_original) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/") and Path(n).suffix.lower() in EXTS]
        print(f"Imágenes detectadas en el ZIP: {len(names)}", flush=True)
        for ix, name in enumerate(names, start=1):
            key = name.replace("\\", "/").strip("/")
            meta = inventory.get(key, {})
            try:
                with Image.open(io.BytesIO(zf.read(name))) as im:
                    # draft puede acelerar JPEG/MPO, manteniendo el ZIP intacto.
                    try:
                        im.draft("L", (80, 80))
                    except (AttributeError, OSError, ValueError):
                        pass
                    gray = ImageOps.exif_transpose(im.convert("L"))
                    h1, h2 = dhash(gray), ahash(gray)
                records.append({
                    "zipname": name,
                    "ruta": key,
                    "clase": meta.get("clase") or label_from_path(key),
                    "sha256": meta.get("sha256", ""),
                    "dhash": h1,
                    "ahash": h2,
                })
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                errors.append({"ruta": key, "error": str(exc)})
            if ix % 250 == 0 or ix == len(names):
                print(f"Hashes calculados: {ix}/{len(names)}", flush=True)

        # 3.228 imágenes: ~5,2 millones de pares, viables en un equipo personal.
        # Se limitan las filas guardadas para evitar consumo excesivo de RAM.
        heap = []
        counter = Counter()
        for i, a in enumerate(records):
            for j in range(i + 1, len(records)):
                b = records[j]
                d1 = (a["dhash"] ^ b["dhash"]).bit_count()
                if d1 > args.umbral:
                    continue
                d2 = (a["ahash"] ^ b["ahash"]).bit_count()
                if d2 > args.umbral_ahash:
                    continue
                different = a["clase"] != b["clase"]
                exact = bool(a["sha256"] and b["sha256"] and a["sha256"] == b["sha256"])
                counter["pares_total"] += 1
                counter["clases_distintas" if different else "misma_clase"] += 1
                if exact:
                    counter["exactos_ya_detectados"] += 1
                # Priorización: duplicados exactos; etiquetas distintas; distancias menores.
                priority = (int(exact), int(different), -d1, -d2, -i, -j)
                item = (priority, i, j, d1, d2, different, exact)
                if len(heap) < args.max_pares:
                    heapq.heappush(heap, item)
                elif priority > heap[0][0]:
                    heapq.heapreplace(heap, item)
        pairs = [
            {"i": i, "j": j, "distancia_dhash": d1, "distancia_ahash": d2,
             "clases_distintas": different, "duplicado_exacto_segun_inventario": exact}
            for _, i, j, d1, d2, different, exact in heap
        ]
        pairs.sort(key=lambda p: (not p["duplicado_exacto_segun_inventario"], not p["clases_distintas"], p["distancia_dhash"], p["distancia_ahash"]))
        csvpath = target / "candidatos_similitud.csv"
        with csvpath.open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(["ruta_a", "clase_a", "ruta_b", "clase_b", "distancia_dhash", "distancia_ahash", "clases_distintas", "duplicado_exacto_segun_inventario", "decision_revision_manual"])
            for p in pairs:
                a, b = records[p["i"]], records[p["j"]]
                writer.writerow([a["ruta"], a["clase"], b["ruta"], b["clase"], p["distancia_dhash"], p["distancia_ahash"], str(p["clases_distintas"]), str(p["duplicado_exacto_segun_inventario"]), "PENDIENTE"])
        imagepath = target / "contacto_revision_candidatos.png"
        nthumbs = make_contact(zf, pairs, records, imagepath, args.max_miniaturas)

    summary = {
        "archivo_analizado": Path(args.zip_original).name,
        "total_imagenes_en_zip": len(names),
        "imagenes_procesadas": len(records),
        "imagenes_no_procesadas": errors,
        "umbral_distancia_dhash_64bits": args.umbral,
        "umbral_distancia_ahash_64bits": args.umbral_ahash,
        "pares_candidatos_total": counter["pares_total"],
        "pares_guardados_csv": len(pairs),
        "tope_guardado_csv": args.max_pares,
        "pares_con_clases_distintas": counter["clases_distintas"],
        "pares_misma_clase": counter["misma_clase"],
        "pares_exactos_ya_detectados_segun_inventario": counter["exactos_ya_detectados"],
        "pares_mostrados_en_contacto": nthumbs,
        "advertencia": "Son candidatos por dos hashes perceptuales, NO duplicados confirmados ni búsqueda exhaustiva de semejanza visual. Se requiere revisión humana antes de excluir o separar imágenes.",
        "accion_sobre_zip_original": "Ninguna. Archivo original sin modificaciones.",
    }
    (target / "resumen_similitud.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nArchivos: {target / 'resumen_similitud.json'}, {csvpath}" + (f", {imagepath}" if nthumbs else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
