"""Ordinary unencoded circle centres from image + organized point map, millimetres."""
from dataclasses import asdict, dataclass, replace
from math import hypot
import cv2
import numpy as np

@dataclass(frozen=True)
class CircleParameters:
    polarity: str = 'dark'
    threshold: int = -1
    min_radius: float = 3.
    max_radius: float = 60.
    circularity: float = .65
    depth_radius: int = 3
    depth_spread: float = 5.

    def validate(self):
        if self.polarity not in ('dark','light') or not -1 <= self.threshold <= 255:
            raise ValueError('圆点极性或灰度阈值无效')
        if not np.isfinite([self.min_radius,self.max_radius,self.circularity,self.depth_spread]).all():
            raise ValueError('检测参数必须为有限值')
        if not 1 <= self.min_radius < self.max_radius <= 1000 or not .1 <= self.circularity <= 1:
            raise ValueError('圆半径或圆度参数无效')
        if not 1 <= self.depth_radius <= 20 or not .01 <= self.depth_spread <= 100:
            raise ValueError('深度邻域或深度离散阈值无效')


def _is_concentric_ring(contours, hierarchy, hole, outer_area, centre, axes, min_circularity):
    if hole == -1 or hierarchy[hole, 0] != -1:
        return False
    inner = contours[hole]
    area = cv2.contourArea(inner)
    perimeter = cv2.arcLength(inner, True)
    if len(inner) < 5 or perimeter <= 0 or not .16 <= area / outer_area < 1:
        return False
    if 4 * np.pi * area / perimeter**2 < min_circularity:
        return False
    inner_centre, inner_axes, _ = cv2.fitEllipse(inner)
    outer_aspect = min(axes) / max(axes)
    inner_aspect = min(inner_axes) / max(inner_axes)
    return (
        abs(inner_aspect - outer_aspect) <= .25
        and np.linalg.norm(np.subtract(inner_centre, centre)) <= max(1., .15 * min(axes))
    )


def _grayscale(image):
    image=np.asarray(image)
    if image.dtype==np.uint16:
        image=(image/256).astype(np.uint8)
    if image.dtype!=np.uint8:
        raise ValueError('输入图像必须是8位或16位灰度/BGR图')
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 and image.shape[2]==3 else image
    if gray.ndim!=2:
        raise ValueError('仅支持灰度或三通道BGR图像')
    return gray


class _TooManyCircles(ValueError):
    pass


def detect_circles(image, pointmap, params=CircleParameters(), *, candidate_limit=24):
    params.validate()
    gray = _grayscale(image)
    h,w=gray.shape
    points=np.asarray(pointmap,float)
    if points.shape!=(h*w,3):
        raise ValueError('原始有序点云必须逐像素对应图像，点数=宽×高；不能用裁剪或无序PLY')
    points=points.reshape(h,w,3)
    flag=cv2.THRESH_BINARY_INV if params.polarity=='dark' else cv2.THRESH_BINARY
    _,binary=cv2.threshold(gray,max(0,params.threshold),255,flag|(cv2.THRESH_OTSU if params.threshold<0 else 0))
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]
    candidates = []
    for index, contour in enumerate(contours):
        _, _, hole, parent = hierarchy[index]
        if parent != -1:
            continue
        area=cv2.contourArea(contour); perimeter=cv2.arcLength(contour,True)
        radius=np.sqrt(area/np.pi)
        if not params.min_radius<=radius<=params.max_radius or perimeter<=0:
            continue
        circularity = 4 * np.pi * area / perimeter**2
        if circularity < params.circularity or len(contour) < 5:
            continue
        (x,y),(a,b),_=cv2.fitEllipse(contour)
        left,top,ww,hh=cv2.boundingRect(contour)
        if left<=0 or top<=0 or left+ww>=w or top+hh>=h or min(a,b)<.45*max(a,b):
            continue
        cx,cy=int(round(x)),int(round(y))
        if not 0<=cx<w or not 0<=cy<h:
            continue
        if binary[cy, cx] == 0 and not _is_concentric_ring(
            contours, hierarchy, hole, area, (x, y), (a, b), params.circularity
        ):
            continue
        candidates.append((float(radius), float(x), float(y), min(a, b), circularity))

    # A rim and a separated inner disk can both be foreground components.
    # Prefer the outer ellipse when the centres are close and one encloses the other.
    unique = []
    for radius, x, y, minor_axis, circularity in sorted(candidates, key=lambda item: item[0], reverse=True):
        if any(hypot(x - ox, y - oy) <= min(.25 * outer, outer - radius + 1.)
               for outer, ox, oy, _, _ in unique):
            continue
        unique.append((radius, x, y, minor_axis, circularity))
        if len(unique) > candidate_limit:
            raise _TooManyCircles(f'圆点候选超过{candidate_limit}个，请缩小半径范围或调整灰度阈值；本版不截断候选后猜测匹配')

    dots=[]
    for radius, x, y, minor_axis, circularity in unique:
        cx, cy = int(round(x)), int(round(y))
        r=max(1,min(params.depth_radius,int(max(1,minor_axis*.25))))
        x0,x1=max(0,cx-r),min(w,cx+r+1);y0,y1=max(0,cy-r),min(h,cy+r+1)
        patch=points[y0:y1,x0:x1]
        yy,xx=np.mgrid[y0:y1,x0:x1]
        valid=np.isfinite(patch).all(axis=2)&np.any(patch!=0,axis=2)&((xx-x)**2+(yy-y)**2<=r*r)
        samples=patch[valid]
        xyz=None
        if len(samples)>=3:
            median=np.median(samples,axis=0)
            stable=np.abs(samples[:,2]-median[2])<=params.depth_spread
            if stable.sum()>=3 and stable.mean()>=.7:
                xyz=np.median(samples[stable],axis=0)
        dots.append(dict(pixel=[x,y],radius=radius,circularity=circularity,xyz=xyz,valid_3d=xyz is not None))
    dots.sort(key=lambda dot:(round(dot['pixel'][1],1),dot['pixel'][0]))
    return dots


def search_circle_parameters(image, pointmap, current=CircleParameters(), *, cancelled=None):
    """Find a comparable-size group with stable 3D centres across nearby thresholds."""
    current.validate()
    gray = _grayscale(image)
    points = np.asarray(pointmap, dtype=float)
    if points.shape != (gray.size, 3):
        raise ValueError('自动设置需要与图像逐像素对应的原始有序点云')

    def detect(parameters, limit=24):
        if cancelled is not None and cancelled.is_set():
            raise ValueError('自动设置已取消')
        try:
            return detect_circles(gray, points, parameters, candidate_limit=limit)
        except _TooManyCircles:
            return []

    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    thresholds = dict.fromkeys(int(np.clip(value, 8, 247)) for value in (
        otsu + 16, otsu, otsu - 16, 64, 96, 128, 160, 192, 224,
        current.threshold if current.threshold >= 0 else otsu))
    best = None
    best_score = (0, 0.)
    for polarity in (current.polarity, 'light' if current.polarity == 'dark' else 'dark'):
        broad = replace(current, polarity=polarity, min_radius=2., max_radius=1000., circularity=.45)
        for threshold in thresholds:
            parameters = replace(broad, threshold=threshold)
            dots = detect(parameters, limit=256)
            radii = sorted(dot['radius'] for dot in dots if dot['valid_3d'])
            if len(radii) < 3:
                continue
            # Radius clustering excludes small reflections and large background contours.
            group = max(([other for other in radii if radius <= other <= 1.8 * radius]
                         for radius in radii), key=len)
            if len(group) < 3 or len(group) < best_score[0]:
                continue
            circularity = min(dot['circularity'] for dot in dots if dot['valid_3d']
                              and group[0] <= dot['radius'] <= group[-1])
            parameters = replace(parameters, min_radius=round(max(1., .82 * group[0]), 2),
                                 max_radius=round(min(1000., 1.18 * group[-1]), 2),
                                 circularity=round(max(.45, circularity - .08), 2))
            hits = detect(parameters)
            valid = [dot for dot in hits if dot['valid_3d']]
            if len(valid) < 3 or len(valid) < best_score[0]:
                continue
            pixels = np.array([dot['pixel'] for dot in valid])
            stable = np.ones(len(valid), dtype=bool)
            for offset in (-8, 8):
                nearby = [dot['pixel'] for dot in detect(replace(parameters, threshold=threshold + offset))
                          if dot['valid_3d']]
                if not nearby:
                    stable[:] = False
                    break
                distances = np.linalg.norm(pixels[:, None] - np.array(nearby)[None, :], axis=2)
                stable &= distances.min(axis=1) <= 2.
            count = int(stable.sum())
            score = (count, count / len(hits))
            if count >= 3 and score[1] >= .75 and score > best_score:
                best, best_score = parameters, score
    if best is None:
        raise ValueError('未稳定检出至少 3 个有效 3D 圆心，识别参数保持不变。')
    return dict(unencoded=asdict(best), stable_count=best_score[0])
