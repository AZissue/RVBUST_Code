"""Isolated large manual-registration job, with bounded native thread counts."""
from dataclasses import asdict
from pathlib import Path
import json, os, subprocess, sys, tempfile, time
import numpy as np
from .session import CloudLayer
from .icp_registration import ICPParameters


def run_job(reference,moving,a,b,params,progress=None,timeout=180):
    notify=progress or (lambda message:None)
    with tempfile.TemporaryDirectory(prefix='MCC_manual_registration_') as folder:
        root=Path(folder)
        notify('准备独立配准进程数据')
        for index,layer in enumerate((reference,moving)):
            np.save(root/f'points{index}.npy',layer.points)
            if layer.colors is not None: np.save(root/f'colors{index}.npy',layer.colors)
        (root/'request.json').write_text(json.dumps(dict(names=[reference.name,moving.name],
            origins=[reference.origins,moving.origins],a=np.asarray(a).tolist(),b=np.asarray(b).tolist(),params=asdict(params))),encoding='utf-8')
        env=os.environ.copy()
        env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]),OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='2',PYTHONIOENCODING='utf-8')
        with (root/'stderr.log').open('w',encoding='utf-8') as err:
            process=subprocess.Popen([sys.executable,'-m','core.postprocess.registration_job',str(root)],
                env=env,stdout=subprocess.DEVNULL,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            start=time.monotonic(); last=None
            try:
                while process.poll() is None:
                    if time.monotonic()-start>timeout:
                        raise TimeoutError(f'手动配准计算超过{timeout:g}秒，未发布结果；请核对对应点、增大计算体素或先裁剪重叠区域')
                    try: stage=(root/'stage.txt').read_text(encoding='utf-8')
                    except OSError: stage='启动独立配准进程'
                    if stage and stage!=last: notify(stage);last=stage
                    try: process.wait(timeout=.25)
                    except subprocess.TimeoutExpired: pass
            finally:
                if process.poll() is None: process.kill();process.wait()
        if process.returncode:
            if (root/'error.txt').exists(): raise ValueError((root/'error.txt').read_text(encoding='utf-8'))
            raise RuntimeError('独立配准进程失败：'+(root/'stderr.log').read_text(encoding='utf-8')[-1200:])
        notify('读取完整配准结果')
        data=json.loads((root/'result.json').read_text(encoding='utf-8'))
        output=CloudLayer(data['name'],np.load(root/'result.npy',mmap_mode='r'),
            np.load(root/'result_colors.npy',mmap_mode='r') if (root/'result_colors.npy').exists() else None,
            origins=reference.origins+moving.origins,parent_transforms=data['parent_transforms'])
        return output,data['report']


def child(root):
    from .manual_registration import register_manual
    root=Path(root)
    try:
        data=json.loads((root/'request.json').read_text(encoding='utf-8'))
        layers=[CloudLayer(data['names'][i],np.load(root/f'points{i}.npy',mmap_mode='r'),
            np.load(root/f'colors{i}.npy',mmap_mode='r') if (root/f'colors{i}.npy').exists() else None,
            origins=tuple(tuple(t) for t in data['origins'][i])) for i in range(2)]
        output,report=register_manual(*layers,data['a'],data['b'],ICPParameters(**data['params']),isolated=False,
            progress=lambda text:(root/'stage.txt').write_text(text,encoding='utf-8'))
        np.save(root/'result.npy',output.points)
        if output.colors is not None: np.save(root/'result_colors.npy',output.colors)
        (root/'result.json').write_text(json.dumps(dict(name=output.name,parent_transforms=output.parent_transforms,report=report)),encoding='utf-8')
    except Exception as exc:
        (root/'error.txt').write_text(str(exc),encoding='utf-8');raise

if __name__=='__main__': child(sys.argv[1])
