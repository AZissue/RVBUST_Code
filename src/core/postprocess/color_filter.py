"""ROI-only colour threshold filtering; RGB in [0,1], inclusive 8-bit limits."""
import numpy as np

METRICS = ('value', 'gray', 'red', 'green', 'blue')

def color_values(colors, metric='value'):
    rgb = np.asarray(colors, dtype=float)
    if rgb.ndim != 2 or rgb.shape[1] != 3 or not np.isfinite(rgb).all():
        raise ValueError('需要有效的RGB颜色')
    if metric == 'value':
        value = rgb.max(axis=1) if len(rgb) else np.empty(0)
    elif metric == 'gray':
        value = rgb @ np.array([.299, .587, .114])
    elif metric in ('red','green','blue'):
        value = rgb[:, ('red','green','blue').index(metric)]
    else:
        raise ValueError('未知颜色通道')
    return np.rint(np.clip(value,0,1)*255).astype(np.uint8)


def threshold_rejection(colors, roi, low=40, high=255, metric='value'):
    if not 0 <= low <= high <= 255 or int(low) != low or int(high) != high:
        raise ValueError('颜色阈值必须满足 0 ≤ 下限 ≤ 上限 ≤ 255')
    values = color_values(colors, metric)
    roi = np.asarray(roi)
    if roi.dtype != np.bool_ or roi.shape != values.shape:
        raise ValueError('框选掩码与颜色点数不一致')
    return roi & ((values < low) | (values > high))


def preview_data(layer, roi, view):
    if layer.colors is None:
        raise ValueError('当前点云没有原始RGB颜色，不能按颜色去黑边')
    indices = np.flatnonzero(roi)
    if not len(indices):
        raise ValueError('框选区域没有点')
    colors = layer.colors[indices]
    histograms = {key: np.bincount(color_values(colors,key),minlength=256) for key in METRICS}
    sample = indices[np.linspace(0,len(indices)-1,min(12000,len(indices)),dtype=int)]
    projected = ((layer.points[sample]-view['center']) @ view['rotation_matrix'].T)[:,:2]
    projected[:,1] *= -1
    return dict(histograms=histograms, points=projected, colors=layer.colors[sample],
                values={key:color_values(layer.colors[sample],key) for key in METRICS},
                selected=len(indices), total=len(layer.points))
