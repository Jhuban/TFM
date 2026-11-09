#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Crea láminas y planilla para revisar MANUALMENTE los pares candidatos RoseLeafInsight.

Uso desde 03_datasets (con código en ../04_codigo):
 py "..\04_codigo\preparar_revision_manual_pares.py" "RoseLeafInsight Original Image.zip" \
   --candidatos "..\05_resultados\revision_similitud_RoseLeafInsight\candidatos_similitud.csv" \
   --salida "..\05_resultados\revision_manual_RoseLeafInsight"

No elimina imágenes, no cambia etiquetas ni reescribe el ZIP.
Requisitos: Python >= 3.9 y Pillow (py -m pip install pillow).
La cercanía perceptual de dHash/aHash NO verifica identidad biológica ni patología.
"""

import argparse
import csv
import io
import json
import math
import zipfile
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont


def get_font(size):
    for path in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def get_image(zf, filename, index):
    key = filename.replace('\\', '/').strip('/')
    zipname = index.get(key)
    if zipname is None:
        possible = [v for k,v in index.items() if k.endswith('/'+key)]
        if len(possible) != 1:
            raise FileNotFoundError(f"No se localizó una ruta única para {filename!r} dentro del ZIP")
        zipname=possible[0]
    with Image.open(io.BytesIO(zf.read(zipname))) as im:
        rgb=ImageOps.exif_transpose(im.convert('RGB'))
        rgb.thumbnail((460,235), Image.Resampling.LANCZOS)
        output=Image.new('RGB',(470,245),'white')
        output.paste(rgb,((470-rgb.width)//2,(245-rgb.height)//2))
    return output


def render_lamina(zf, index, chunk, start, page, total, folder):
    width, top, row_h = 1110, 120, 327
    img=Image.new('RGB',(width, top + row_h*len(chunk) + 35),'white')
    draw=ImageDraw.Draw(img)
    normal=get_font(19); strong=get_font(23)
    draw.text((25,18), f'RoseLeafInsight | Revisión manual de pares | Lámina {page}/{total}',font=strong,fill='#222222')
    draw.text((25,59), 'Comparar la MISMA hoja/captura, no solamente forma o color. No excluir sin justificar.',font=normal,fill='#444444')
    for i, item in enumerate(chunk):
        y = top + i*row_h
        uid=start+i+1
        for col, suffix in ((0,'a'),(1,'b')):
            x=30+col*540
            filename=item['ruta_'+suffix]
            label=item['clase_'+suffix]
            tile=get_image(zf,filename,index)
            img.paste(tile,(x,y))
            draw.text((x,y+250), f'{uid:02d}{suffix.upper()} | {label}',font=strong,fill='#222222')
            show=filename.replace('\\','/')
            if len(show)>48: show=show[:45]+'...'
            draw.text((x,y+282),show,font=normal,fill='#404040')
        dt=item['distancia_dhash']; at=item['distancia_ahash']
        exact=str(item['duplicado_exacto_segun_inventario']).lower()=='true'
        cross=str(item['clases_distintas']).lower()=='true'
        draw.text((25,y+311), f'dHash={dt} | aHash={at} | distintas={cross} | exacto_SHA256={exact}',font=normal,fill='#333333')
    filepath=folder/f'revision_pares_{page:02d}.png'
    img.save(filepath,optimize=True)
    return filepath


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('zip_original')
    ap.add_argument('--candidatos',required=True,help='CSV generado por revisar_similitud_roseleafinsight.py')
    ap.add_argument('--salida',default='revision_manual_RoseLeafInsight')
    ap.add_argument('--pares-por-lamina',type=int,default=8)
    args=ap.parse_args()
    if args.pares_por_lamina <1 or args.pares_por_lamina>15: ap.error('--pares-por-lamina debe estar entre 1 y 15')
    out=Path(args.salida)
    out.mkdir(parents=True,exist_ok=True)
    with open(args.candidatos,encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    if not rows: ap.error('El CSV de candidatos no contiene pares')
    n=math.ceil(len(rows)/args.pares_por_lamina)
    with zipfile.ZipFile(args.zip_original) as zf:
        index={name.replace('\\','/').strip('/'):name for name in zf.namelist() if not name.endswith('/')}
        for p in range(n):
            s=p*args.pares_por_lamina
            file=render_lamina(zf,index,rows[s:s+args.pares_por_lamina],s,p+1,n,out)
            print(f'Generada {file} ({min(s+args.pares_por_lamina,len(rows))}/{len(rows)} pares)',flush=True)
    fieldnames=['id_par','ruta_a','clase_a','ruta_b','clase_b','distancia_dhash','distancia_ahash',
                'clases_distintas','duplicado_exacto_segun_inventario','evidencia_previa',
                'decision_revision_manual','motivo_decision','accion_recomendada','revisado_por','fecha_revision']
    csv_file=out/'planilla_revision_manual.csv'
    with open(csv_file,'w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fieldnames);writer.writeheader()
        for i,row in enumerate(rows,1):
            evidence='DUPLICADO_BINARIO_SHA256' if str(row['duplicado_exacto_segun_inventario']).lower()=='true' else 'CANDIDATO_HASH_PERCEPTUAL'
            base={k:row.get(k,'') for k in fieldnames}
            base.update({'id_par':f'{i:02d}','evidencia_previa':evidence,'decision_revision_manual':'PENDIENTE',
                         'motivo_decision':'','accion_recomendada':'','revisado_por':'','fecha_revision':''})
            writer.writerow(base)
    instructions=(
        'GUIA DE REVISION HUMANA DE SIMILITUD ROSELEAFINSIGHT\n'
        '1. Abre todas las laminas revision_pares_XX.png y revisa cada par 1A/1B, 2A/2B, etc.\n'
        '2. Completa planilla_revision_manual.csv, sin borrar ni modificar filas.\n'
        '3. En decision_revision_manual anota uno de: MISMA_FOTO, DISTINTAS, DUDOSO, CONFLICTO_ETIQUETA.\n'
        '4. Usa CONFLICTO_ETIQUETA solamente si es LA MISMA imagen con dos etiquetas diferentes.\n'
        '   Etiquetas diferentes NO significan por si solas un error: pueden ser hojas distintas.\n'
        '5. En motivo_decision explica brevemente rasgos comparados, orientacion, nervaduras, bordes, etc.\n'
        '6. No elimines fotografias del ZIP, ni decidas el split a partir de parecidos sin revisar.\n'
        '7. Prioriza los 8 pares de clases distintas, despues los 70 de la misma clase.\n'
        '8. Los dos pares marcados DUPLICADO_BINARIO_SHA256 ya tienen identidad digital confirmada.\n'
        '9. Comparte la planilla revisada. No se recomiendan exclusiones automaticas.\n'
        'Este procedimiento es una auditoria visual, no una validacion fitopatologica.\n'
    )
    (out/'INSTRUCCIONES.txt').write_text(instructions,encoding='utf-8')
    summary={'dataset':Path(args.zip_original).name,'numero_pares':len(rows),
             'pares_con_etiquetas_distintas':sum(str(x['clases_distintas']).lower()=='true' for x in rows),
             'pares_exactos_reconocidos':sum(str(x['duplicado_exacto_segun_inventario']).lower()=='true' for x in rows),
             'laminas_generadas':n,'decision_manual':'PENDIENTE','zip_original_modificado':False}
    (out/'resumen_preparacion_revision.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print(f'Planilla para completar: {csv_file}')

if __name__ == '__main__': main()
