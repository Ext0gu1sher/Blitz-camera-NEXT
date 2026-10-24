"""Read map resources and record feasibility evidence. Never changes the client.

This is an offline research script; lz4 is not a workstation dependency.
Height values are raw uint16 samples, not calibrated world heights.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct
import zlib
from datetime import datetime, timezone
import lz4.block

ROOT=Path(__file__).resolve().parents[2]
MAPS=Path(r'C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\Data\3d\Maps')


def decode(path):
    raw=path.read_bytes()
    if len(raw)<20:raise ValueError('Missing DVPL footer')
    usize,csize,crc,method,magic=struct.unpack('<IIII4s',raw[-20:]);payload=raw[:-20]
    if magic!=b'DVPL' or len(payload)!=csize or zlib.crc32(payload)!=crc:raise ValueError('DVPL integrity mismatch')
    if usize>128*1024*1024:raise ValueError('Resource exceeds research bound')
    if method==0:data=payload
    elif method in (1,2):data=lz4.block.decompress(payload,uncompressed_size=usize)
    else:raise ValueError('Unsupported compression')
    if len(data)!=usize:raise ValueError('Decoded size mismatch')
    return data,{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'decoded_size':usize,'compression':method,'crc_verified':True,'decoded_header':data[:32].hex()}


def heights(data):
    size,tile=struct.unpack_from('<II',data)
    if not 1<=tile<=size<=8192 or size&(size-1) or size%tile or len(data)!=8+size*size*2:raise ValueError('Heightmap differs from the inspected tiled layout')
    rows=[[0]*size for _ in range(size)];offset=8
    for by in range(0,size,tile):
        for bx in range(0,size,tile):
            for y in range(tile):
                rows[by+y][bx:bx+tile]=struct.unpack_from('<'+'H'*tile,data,offset);offset+=tile*2
    assert offset==len(data)
    return size,tile,rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--map-id',default='11_plant_pn');args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]+',args.map_id):raise ValueError('Invalid map ID')
    folder=MAPS/args.map_id
    height_files=sorted(folder.glob('landscape/*.heightmap.dvpl'))
    if len(height_files)!=1:raise ValueError('Select a map with exactly one heightmap for this bounded probe')
    out=ROOT/'research/builds/11.21.0.1235/map-assets'/args.map_id;out.mkdir(parents=True,exist_ok=True)
    report={'read_at_utc':datetime.now(timezone.utc).isoformat(),'map_id':args.map_id,'client_read_only':True,'world_alignment_verified':False,'building_meshes_decoded':False,'sources':[]}
    for path in [height_files[0],folder/(args.map_id+'.sc2.dvpl'),folder/(args.map_id+'.scg.dvpl')]:
        data,evidence=decode(path);report['sources'].append(evidence)
        if path==height_files[0]:
            size,tile,rows=heights(data);values=[v for row in rows for v in row]
            report['heightmap']={'size':[size,size],'tile_size':tile,'sample_count':len(values),'sample_type':'uint16','minimum_raw':min(values),'maximum_raw':max(values),'world_height_scale_verified':False}
            (out/'height-grid.json').write_text(json.dumps({'coordinate_space':'unscaled heightmap grid; not game world','size':size,'rows':rows},separators=(',',':')),encoding='utf8')
        elif '.sc2.' in path.name:
            reference=height_files[0].relative_to(folder).as_posix().removesuffix('.dvpl').encode()
            evidence['heightmap_reference_present']=reference in data
    (out/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
