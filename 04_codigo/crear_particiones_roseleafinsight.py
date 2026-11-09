#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""TFM Rosa IA — RoseLeafInsight: depuración lógica y partición estratificada.

Entradas: inventario_auditado.csv (auditoría E02) y planilla de revisión manual E05.
Salidas: manifiesto de exclusiones, inventario depurado, particiones y resumen JSON.

Garantías: no abre, elimina ni altera el ZIP original; no modifica imágenes.
Limitación: la revisión de 78 pares por hash NO demuestra independencia por planta,
fecha de captura o escena. La partición es por archivo original, estratificada por
clase, y evita duplicados binarios detectados. No equivale a validación en campo.

Uso, desde 03_datasets:
py ..\04_codigo\crear_particiones_roseleafinsight.py ^
  --inventario "..\05_resultados\auditoria_RoseLeafInsight\inventario_auditado.csv" ^
  --revision "..\05_resultados\revision_manual_RoseLeafInsight\planilla_revision_manual_revisada.csv" ^
  --salida "..\05_resultados\particiones_RoseLeafInsight"

En PowerShell, escribe el comando en UNA SOLA línea o utiliza acento grave `
como continuación; el símbolo ^ es para CMD, no PowerShell.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import random
from pathlib import Path

SEED_DEFAULT = 20261109
TARGET_COUNTS = {'CONFLICTO_ETIQUETA': 1, 'MISMA_FOTO': 1, 'DISTINTAS': 76}


def read_csv_auto(path: Path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        peek = f.read(6000)
        f.seek(0)
        sep = ';' if peek.splitlines()[0].count(';') > peek.splitlines()[0].count(',') else ','
        result = list(csv.DictReader(f, delimiter=sep))
    if not result:
        raise ValueError(f'El archivo no contiene filas: {path}')
    return result


def write_csv(path: Path, rows, fieldnames):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def require(test, message):
    if not test:
        raise ValueError(message)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('--inventario', required=True, type=Path)
    ap.add_argument('--revision', required=True, type=Path)
    ap.add_argument('--salida', required=True, type=Path)
    ap.add_argument('--semilla', type=int, default=SEED_DEFAULT)
    args = ap.parse_args()

    inventor = read_csv_auto(args.inventario)
    revision = read_csv_auto(args.revision)
    require(len(inventor) == 3228, f'Se esperaban 3228 imágenes originales, recibidas: {len(inventor)}')
    require(len(revision) == 78, f'Se esperaban 78 pares revisados, recibidos: {len(revision)}')
    by_path = {r['ruta_en_zip']: r for r in inventor}
    require(len(by_path) == len(inventor), 'Inventario con rutas repetidas')
    require(all(r.get('sha256') for r in inventor), 'Hay hashes SHA-256 vacíos')
    require(all(not r.get('error', '').strip() for r in inventor), 'Hay imágenes con errores de auditoría')
    require(sorted(int(r['id_par']) for r in revision) == list(range(1,79)), 'IDs de pares inesperados')
    decisions = collections.Counter(r['decision_revision_manual'].strip().upper() for r in revision)
    require(decisions == TARGET_COUNTS, f'Decisiones no esperadas: {decisions}')
    for r in revision:
        require(all(r.get(x, '').strip() for x in ('motivo_decision', 'accion_recomendada', 'revisado_por', 'fecha_revision')),
                f'Faltan campos de revisión en id_par={r["id_par"]}')
        require(r['ruta_a'] in by_path and r['ruta_b'] in by_path,
                f'Ruta inexistente en inventario para par {r["id_par"]}')
        da, db = by_path[r['ruta_a']], by_path[r['ruta_b']]
        is_exact = da['sha256'] == db['sha256']
        require(is_exact == (r['duplicado_exacto_segun_inventario'].lower() == 'true'),
                f'Inconsistencia SHA-256 / revisión en par {r["id_par"]}')
        if r['decision_revision_manual'] == 'DISTINTAS':
            require(not is_exact, 'Una pareja SHA-256 idéntica fue marcada DISTINTAS')

    # Lista explícita, aprobada como propuesta tras la revisión humana.
    p1 = next(r for r in revision if int(r['id_par']) == 1)
    p2 = next(r for r in revision if int(r['id_par']) == 2)
    require(p1['decision_revision_manual'] == 'CONFLICTO_ETIQUETA', 'Par 1 no confirmado como conflicto')
    require(p2['decision_revision_manual'] == 'MISMA_FOTO', 'Par 2 no confirmado como misma foto')
    require(by_path[p1['ruta_a']]['sha256'] == by_path[p1['ruta_b']]['sha256'] and p1['clase_a'] != p1['clase_b'],
            'Par 1 no es duplicado exacto de clases distintas')
    require(by_path[p2['ruta_a']]['sha256'] == by_path[p2['ruta_b']]['sha256'] and p2['clase_a'] == p2['clase_b'],
            'Par 2 no es duplicado exacto de la misma clase')
    excluded = {
        p1['ruta_a']: ('PAR_01', 'Contenido idéntico con dos etiquetas diferentes; etiqueta sin resolver'),
        p1['ruta_b']: ('PAR_01', 'Contenido idéntico con dos etiquetas diferentes; etiqueta sin resolver'),
        p2['ruta_b']: ('PAR_02', 'Copia binaria redundante; se conserva ruta_a de la pareja'),
    }
    require(len(excluded) == 3, 'La selección de exclusiones no equivale a 3 archivos distintos')

    # Si aparecen nuevos duplicados binarios ajenos a esos dos pares, detenerse.
    sha_groups = collections.defaultdict(list)
    for p, r in by_path.items(): sha_groups[r['sha256']].append(p)
    unexpected = [v for v in sha_groups.values() if len(v)>1 and not set(v).issubset(
        {p1['ruta_a'], p1['ruta_b'], p2['ruta_a'], p2['ruta_b']})]
    require(not unexpected, f'Hay nuevos grupos de duplicados que requieren revisión: {unexpected[:3]}')
    clean = [r for r in inventor if r['ruta_en_zip'] not in excluded]
    require(len(clean) == 3225, f'Se esperaban 3225 imágenes candidatas, recibidas {len(clean)}')
    require(len({r['sha256'] for r in clean}) == len(clean), 'Siguen existiendo duplicados exactos tras depuración lógica')

    # División 70/15/15 por clase: método del mayor resto para los tamaños.
    groups = collections.defaultdict(list)
    for r in clean:groups[r['clase']].append(r)
    rng = random.Random(args.semilla)
    split_rows = []
    for label in sorted(groups):
        items = sorted(groups[label], key=lambda x:x['ruta_en_zip'])
        rng.shuffle(items)
        n = len(items)
        raw = [n*.70, n*.15, n*.15]
        counts = [int(v) for v in raw]
        remainders = sorted(range(3), key=lambda i:(-(raw[i]-counts[i]),i))
        for idx in remainders[:n-sum(counts)]:counts[idx] += 1
        require(sum(counts)==n, f'Splits suman incorrectamente en clase {label}')
        k = 0
        for split, count in zip(('train','val','test'),counts):
            for r in items[k:k+count]:
                split_rows.append({'ruta_en_zip':r['ruta_en_zip'], 'clase':r['clase'],
                                   'particion':split, 'sha256':r['sha256']})
            k += count

    # Seguridad: cada imagen aparece una vez y los SHA no cruzan particiones.
    require(len(split_rows) == len(clean), 'No se asignaron todas las imágenes')
    require(len({r['ruta_en_zip'] for r in split_rows}) == len(clean), 'Rutas asignadas más de una vez')
    sha_partitions = collections.defaultdict(set)
    for r in split_rows: sha_partitions[r['sha256']].add(r['particion'])
    require(all(len(s)==1 for s in sha_partitions.values()), 'Se detecta duplicado SHA entre particiones')

    args.salida.mkdir(parents=True, exist_ok=True)
    manifest = []
    for r in inventor:
        p=r['ruta_en_zip']
        code, reason = excluded.get(p, ('',''))
        manifest.append({'ruta_en_zip':p,'clase':r['clase'], 'sha256':r['sha256'],
                         'estado':'EXCLUIR_PROPUESTO' if code else 'CONSERVAR',
                         'evidencia':code,'motivo':reason})
    write_csv(args.salida/'manifiesto_depuracion.csv', manifest,
              ['ruta_en_zip','clase','sha256','estado','evidencia','motivo'])
    write_csv(args.salida/'particiones_RoseLeafInsight.csv', split_rows,
              ['ruta_en_zip','clase','particion','sha256'])
    excluded_rows = [m for m in manifest if m['estado']=='EXCLUIR_PROPUESTO']
    write_csv(args.salida/'exclusiones_RoseLeafInsight.csv',excluded_rows,
              ['ruta_en_zip','clase','sha256','estado','evidencia','motivo'])
    counts = collections.defaultdict(collections.Counter)
    for r in split_rows:counts[r['clase']][r['particion']] += 1
    totals = collections.Counter(r['particion'] for r in split_rows)
    content = {'procedimiento':'propuesta de depuración lógica y partición estratificada',
               'estado':'PLAN GENERADO; NO SE HAN EXTRAÍDO NI MODIFICADO LAS IMÁGENES',
               'archivo_revision':str(args.revision), 'archivo_inventario':str(args.inventario),
               'semilla':args.semilla, 'proporciones_objetivo':{'train':0.70,'val':0.15,'test':0.15},
               'originales':len(inventor),'exclusiones_propuestas':len(excluded),
               'candidatas':len(clean),'revision_pares':dict(decisions),
               'particiones':dict(totals),
               'particiones_por_clase':{k:dict(v) for k,v in counts.items()},
               'advertencias':[
                   'La revisión por hashes perceptuales y visual no es exhaustiva.',
                   'No se dispone de identificadores de planta, sesión ni fecha de captura para garantizar independencia por origen.',
                   'Los datos de validación y prueba no deben someterse a data augmentation.',
                   'No se ha entrenado modelo alguno ni calculado métricas predictivas.',
                   'El ZIP original se conserva intacto.'
               ]}
    with (args.salida/'resumen_particiones.json').open('w',encoding='utf-8') as f:
        json.dump(content,f,ensure_ascii=False,indent=2)
    print(json.dumps(content,ensure_ascii=False,indent=2))
    print('Archivos generados:',', '.join(p.name for p in sorted(args.salida.iterdir())))


if __name__=='__main__':
    main()
