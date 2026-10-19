"""Prepare a measured, offline sequence without changing the source scans."""
import sys,json
from pathlib import Path
import numpy as np
import cv2
import open3d as o3d
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine

def prepare(source,output):
    source,output=Path(source),Path(output)
    output.mkdir(parents=True,exist_ok=True)
    detector=MarkerDetector();engine=CalibrationEngine();records=[];world=[]
    for i in range(1,9):
        image=cv2.imdecode(np.fromfile(source/f'{i}.png',np.uint8),cv2.IMREAD_COLOR)
        markers=detector.detect_3d(image,offline_ply_path=str(source/f'{i}.ply'),include_invalid=True)
        valid=[m for m in markers if m.get('valid_3d',True)]
        if len(valid)<3:raise RuntimeError(f'Frame {i}: fewer than 3 valid markers')
        T=np.eye(4);reference=None;shared=[];rms=0.;used=[];rejected=[]
        if records:
            candidates=[]
            for j,r in enumerate(records):
                common=sorted({m['code'] for m in valid}&{m['code'] for m in r['valid']})
                if len(common)<3:continue
                result=engine.calibrate_pair(str(j+1),str(i),r['valid'],valid,ransac_threshold=2.)
                if result.get('success') and result['inlier_ratio']>=.4 and result['rms_mm']<=2.:
                    candidates.append((len(common),j,common,result))
            if not candidates:raise RuntimeError(f'Frame {i}: no accepted registration')
            _,j,shared,result=max(candidates,key=lambda v:v[0])
            T=world[j]@result['T'];reference=j+1;rms=float(result['rms_mm'])
            rejected=result.get('outlier_codes',[]);used=sorted(set(shared)-set(rejected))
        world.append(T)
        record=dict(frame=i,markers=markers,valid=valid,T=T.tolist(),reference=reference,shared=shared,rms=rms,used_codes=used,rejected_codes=rejected,registration_accepted=reference is not None)
        records.append(record)
        print(f'FRAME {i}: valid={len(valid)}, shared={len(shared)}, reference={reference}, rms={rms:.4f}',flush=True)
    # Ground markers define a horizontal plane. Choose the normal toward the stool.
    p=o3d.io.read_point_cloud(str(source/'1.ply'))
    xyz=np.asarray(p.points);rgb=np.asarray(p.colors)
    marker_xyz=np.array([[m['x_3d'],m['y_3d'],m['z_3d']] for m in records[0]['valid']])
    origin=marker_xyz.mean(0);_,_,vh=np.linalg.svd(marker_xyz-origin);normal=vh[-1]
    red=(rgb[:,0]>.30)&(rgb[:,0]>rgb[:,1]*1.8)&(rgb[:,0]>rgb[:,2]*1.8)&np.isfinite(xyz).all(1)
    if (xyz[red].mean(0)-origin)@normal<0:normal=-normal
    x=np.array([1.,0,0]);x-=normal*(x@normal);x/=np.linalg.norm(x)
    y=np.cross(normal,x);A=np.vstack([x,y,normal])
    orient=np.eye(4);orient[:3,:3]=A;orient[:3,3]=-A@origin
    for r,T in zip(records,world):
        i=r['frame'];p=o3d.io.read_point_cloud(str(source/f'{i}.ply'))
        xyz=np.asarray(p.points);rgb=np.asarray(p.colors)
        keep=np.isfinite(xyz).all(1)&(np.linalg.norm(xyz,axis=1)>1e-5)
        xyz=xyz[keep];rgb=rgb[keep];r['original_points']=len(xyz)
        T=orient@T
        # Stable, uniform preview sample; registration uses the full measured marker positions.
        if len(xyz)>600000:
            indices=np.random.default_rng(i).choice(len(xyz),600000,replace=False);xyz=xyz[indices];rgb=rgb[indices]
        xyz=xyz@T[:3,:3].T+T[:3,3]
        np.savez(output/f'frame_{i}.npz',points=xyz.astype(np.float32),colors=rgb.astype(np.float32))
        for m in r['markers']:
            if m.get('valid_3d',True):
                v=T@np.array([m['x_3d'],m['y_3d'],m['z_3d'],1.]);m['world']=v[:3].tolist()
        cv2.imencode('.jpg',image if False else cv2.imdecode(np.fromfile(source/f'{i}.png',np.uint8),cv2.IMREAD_COLOR))[1].tofile(output/f'image_{i}.jpg')
        r.pop('valid');r['display_points']=len(xyz)
        print('CACHED',i,len(xyz),flush=True)
    (output/'sequence.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':prepare(sys.argv[1],sys.argv[2])
