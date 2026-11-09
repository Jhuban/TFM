#!/usr/bin/env python3
"""Crea un inventario y una muestra pequena de un dataset de imagenes en ZIP.
No modifica ni descomprime el archivo original. Python >= 3.9, sin librerias externas.
"""
import argparse
import csv
import json
import random
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'}
PATTERNS = [
    ('Black Spot', ('black spot', 'blackspot', 'mancha negra')),
    ('Downy Mildew', ('downy mildew', 'mildiu velloso', 'mildew downy')),
    ('Powdery Mildew', ('powdery mildew', 'oidio', 'mildiu polvoso')),
    ('Insect Hole', ('insect hole', 'insect-hole', 'insecthole', 'agujero')),
    ('Yellow Mosaic Virus', ('yellow mosaic virus', 'yellow mosaic', 'mosaic virus', 'mosaico')),
    ('Healthy', ('fresh leaf', 'disease free', 'healthy', 'hoja sana', 'normal')),
]


def normalize(s):
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[_\-]+', ' ', s).lower()


def infer_class(name):
    path = name.replace('\\', '/')
    parts = path.split('/')[:-1]
    for p in reversed(parts):
        n = normalize(p)
        for label, variations in PATTERNS:
            if any(normalize(v) in n for v in variations):
                return label
    # Si el ZIP clasifica por nombre de imagen en vez de carpeta
    basename = normalize(path.split('/')[-1])
    for label, variations in PATTERNS:
        if any(normalize(v) in basename for v in variations):
            return label
    return 'SIN_CLASE_IDENTIFICABLE'


def safe_label(value):
    return re.sub(r'[^A-Za-z0-9_\-]+', '_', value).strip('_') or 'Sin_clase'


def main():
    parser = argparse.ArgumentParser(description='Inventario y muestra de imagenes de ZIP de rosas')
    parser.add_argument('zip_file', help='Ruta al ZIP original del dataset')
    parser.add_argument('--salida', default='reporte_rosa', help='Carpeta de resultados')
    parser.add_argument('--por-clase', type=int, default=5, help='Cantidad de imagenes de muestra por clase (por defecto 5)')
    args = parser.parse_args()
    source = Path(args.zip_file)
    if not source.is_file():
        raise SystemExit(f'No existe el archivo: {source}')
    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)
    files_by_class = defaultdict(list)
    rows = []
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            if item.is_dir() or Path(item.filename).suffix.lower() not in EXTS or '__MACOSX' in item.filename:
                continue
            cls = infer_class(item.filename)
            files_by_class[cls].append(item)
            rows.append({
                'ruta_en_zip': item.filename,
                'clase_inferida_de_nombre': cls,
                'tamano_original_bytes': item.file_size,
                'tamano_comprimido_bytes': item.compress_size,
                'extension': Path(item.filename).suffix.lower(),
            })
        counts = {cls: len(items) for cls, items in sorted(files_by_class.items())}
        rng = random.Random(42)
        with zipfile.ZipFile(out / 'muestra_imagenes.zip', 'w', compression=zipfile.ZIP_STORED) as sample:
            for cls, items in sorted(files_by_class.items()):
                selected = rng.sample(items, min(max(0, args.por_clase), len(items)))
                for j, item in enumerate(selected, 1):
                    # Solo extrae las muestras y no la totalidad del ZIP original.
                    dest = f'{safe_label(cls)}/{j:02d}_{Path(item.filename).name}'
                    sample.writestr(dest, archive.read(item))
    with (out / 'inventario_imagenes.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else ['ruta_en_zip', 'clase_inferida_de_nombre', 'tamano_original_bytes', 'tamano_comprimido_bytes', 'extension'])
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        'archivo_fuente': source.name,
        'total_imagenes': len(rows),
        'imagenes_por_clase_inferida': counts,
        'total_bytes_imagenes_sin_comprimir': sum(int(x['tamano_original_bytes']) for x in rows),
        'nota': 'Las clases se infieren de nombres de carpetas/archivos. Deben contrastarse con el articulo del dataset. Esto NO valida etiquetas, calidad, duplicados ni separacion entrenamiento/prueba.',
    }
    (out / 'resumen_dataset.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f'\nArchivos para compartir en ChatGPT: {out / "resumen_dataset.json"}, {out / "inventario_imagenes.csv"}, {out / "muestra_imagenes.zip"}')


if __name__ == '__main__':
    main()
