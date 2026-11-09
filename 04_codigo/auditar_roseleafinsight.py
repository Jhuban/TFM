#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auditoría reproducible de RoseLeafInsight SIN extraer ni modificar imágenes.

Requiere Pillow: py -m pip install pillow
Ejemplo:
    py auditar_roseleafinsight.py "RoseLeafInsight Original Image.zip"

Genera inventario_auditado.csv, duplicados_exactos.csv, resumen_auditoria.json.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import statistics
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

try:
    from PIL import Image, ImageFile
except ImportError:
    raise SystemExit("Falta Pillow. Ejecuta: py -m pip install pillow")

ImageFile.LOAD_TRUNCATED_IMAGES = False
CLASES = {
    "black spot": "Black Spot",
    "healthy leaf": "Healthy",
    "healthy": "Healthy",
    "insect hole": "Insect Hole",
    "yellow mosaic virus": "Yellow Mosaic Virus",
}
CLASES_ESPERADAS = {
    "Black Spot": 409,
    "Healthy": 1686,
    "Insect Hole": 453,
    "Yellow Mosaic Virus": 680,
}
EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto)
    return " ".join(texto.strip().replace("_", " ").split()).casefold()


def clase_de_ruta(ruta: str) -> str:
    # Usa el primer componente de carpeta, no los nombres individuales de imágenes.
    carpetas = Path(ruta).parts
    return CLASES.get(normalizar(carpetas[0]), "SIN_CLASE_IDENTIFICABLE") if len(carpetas) > 1 else "SIN_CLASE_IDENTIFICABLE"


def ejecutar(archivo_zip: Path, carpeta_salida: Path) -> None:
    if not archivo_zip.is_file():
        raise SystemExit(f"No existe el ZIP: {archivo_zip}")
    carpeta_salida.mkdir(parents=True, exist_ok=True)
    campos = ["ruta_en_zip", "clase", "formato", "ancho_px", "alto_px", "modo", "bytes", "sha256", "error"]
    conteos = Counter()
    dimensiones = Counter()
    errores = []
    hashes = defaultdict(list)
    tamanos = []
    cantidad = 0
    inventario = carpeta_salida / "inventario_auditado.csv"

    with zipfile.ZipFile(archivo_zip, "r") as zipf, inventario.open("w", newline="", encoding="utf-8-sig") as out:
        escritor = csv.DictWriter(out, fieldnames=campos)
        escritor.writeheader()
        entradas = [i for i in zipf.infolist() if not i.is_dir() and Path(i.filename).suffix.lower() in EXTENSIONES and not i.filename.startswith("__MACOSX/")]
        for indice, info in enumerate(entradas, start=1):
            cantidad += 1
            clase = clase_de_ruta(info.filename)
            conteos[clase] += 1
            ancho = alto = modo = formato = ""
            sha = ""
            error = ""
            try:
                # Solo se mantiene una imagen en memoria a la vez.
                datos = zipf.read(info)
                sha = hashlib.sha256(datos).hexdigest()
                hashes[sha].append((info.filename, clase))
                with Image.open(io.BytesIO(datos)) as img:
                    formato = img.format or ""
                    ancho, alto = img.size
                    modo = img.mode
                    img.load()  # Valida que la imagen puede decodificarse.
                dimensiones[(ancho, alto)] += 1
                tamanos.append(info.file_size)
            except Exception as ex:
                error = f"{type(ex).__name__}: {str(ex)[:160]}"
                errores.append({"archivo": info.filename, "error": error})
            escritor.writerow({
                "ruta_en_zip": info.filename, "clase": clase, "formato": formato,
                "ancho_px": ancho, "alto_px": alto, "modo": modo,
                "bytes": info.file_size, "sha256": sha, "error": error
            })
            if indice % 250 == 0 or indice == len(entradas):
                print(f"Revisadas {indice}/{len(entradas)} imágenes", flush=True)

    duplicados = [[sha, rutas] for sha, rutas in hashes.items() if len(rutas) > 1]
    duplicados_archivo = carpeta_salida / "duplicados_exactos.csv"
    with duplicados_archivo.open("w", newline="", encoding="utf-8-sig") as out:
        escritor = csv.writer(out)
        escritor.writerow(["sha256", "cantidad", "rutas_y_clases"])
        for sha, rutas in duplicados:
            escritor.writerow([sha, len(rutas), " | ".join(f"{ruta} [{clase}]" for ruta, clase in rutas)])

    alertas = []
    if "SIN_CLASE_IDENTIFICABLE" in conteos:
        alertas.append("Existen imágenes cuya clase no se reconoce a partir de la carpeta.")
    if errores:
        alertas.append("Existen archivos de imagen que no pudieron decodificarse.")
    if duplicados:
        alertas.append("Hay imágenes con contenido binario idéntico; revisar antes de particionar.")
    for clase, esperado in CLASES_ESPERADAS.items():
        if conteos[clase] != esperado:
            alertas.append(f"La clase {clase} contiene {conteos[clase]}, pero el artículo informa {esperado} originales.")
    if cantidad != 3228:
        alertas.append(f"Total diferente de las 3228 imágenes originales publicadas: {cantidad}.")

    resumen = {
        "archivo_analizado": archivo_zip.name,
        "imagenes": cantidad,
        "distribucion_clases": dict(sorted(conteos.items())),
        "porcentaje_por_clase": {k: round(100 * v / cantidad, 2) for k, v in sorted(conteos.items())},
        "dimensiones_mas_comunes": [{"ancho": w, "alto": h, "cantidad": n} for (w, h), n in dimensiones.most_common(15)],
        "imagenes_con_error": len(errores),
        "errores_ejemplos": errores[:15],
        "grupos_duplicados_exactos_sha256": len(duplicados),
        "total_imagenes_en_grupos_duplicados": sum(len(rutas) for _, rutas in duplicados),
        "tamano_mediano_bytes": int(statistics.median(tamanos)) if tamanos else None,
        "alertas": alertas,
        "limitaciones": [
            "Sin etiquetas clínicas independientes: las clases proceden de carpetas.",
            "SHA-256 encuentra duplicados binarios, no imágenes visualmente similares recodificadas.",
            "Esta auditoría no evalúa exactitud fitopatológica ni generalización en campo.",
            "No se generan particiones train/validation/test: deben diseñarse tras revisar posibles duplicados y procedencia de capturas."
        ]
    }
    json_path = carpeta_salida / "resumen_auditoria.json"
    json_path.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(f"\nArchivos para compartir: {json_path}, {duplicados_archivo}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoría de imágenes originales de RoseLeafInsight")
    parser.add_argument("zip", type=Path, help="Ruta al ZIP original")
    parser.add_argument("--salida", type=Path, default=Path("auditoria_RoseLeafInsight"))
    args = parser.parse_args()
    ejecutar(args.zip, args.salida)

if __name__ == "__main__":
    main()
