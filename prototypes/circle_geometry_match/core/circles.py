"""Ordinary unencoded circle centres from image + organized point map, millimetres."""
from dataclasses import dataclass
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


def detect_circles(image, pointmap, params=CircleParameters()):
    params.validate()
    image=np.asarray(image)
    if image.dtype==np.uint16:
        image=(image/256).astype(np.uint8)
    if image.dtype!=np.uint8:
        raise ValueError('输入图像必须是8位或16位灰度/BGR图')
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 and image.shape[2]==3 else image
    if gray.ndim!=2:
        raise ValueError('仅支持灰度或三通道BGR图像')
    h,w=gray.shape
    points=np.asarray(pointmap,float)
    if points.shape!=(h*w,3):
        raise ValueError('原始有序点云必须逐像素对应图像，点数=宽×高；不能用裁剪或无序PLY')
    points=points.reshape(h,w,3)
    flag=cv2.THRESH_BINARY_INV if params.polarity=='dark' else cv2.THRESH_BINARY
    _,binary=cv2.threshold(gray,max(0,params.threshold),255,flag|(cv2.THRESH_OTSU if params.threshold<0 else 0))
    contours,_=cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE)
    dots=[]
    for contour in contours:
        area=cv2.contourArea(contour); perimeter=cv2.arcLength(contour,True)
        radius=np.sqrt(area/np.pi)
        if not params.min_radius<=radius<=params.max_radius or perimeter<=0:
            continue
        if 4*np.pi*area/perimeter**2<params.circularity or len(contour)<5:
            continue
        (x,y),(a,b),_=cv2.fitEllipse(contour)
        left,top,ww,hh=cv2.boundingRect(contour)
        if left<=0 or top<=0 or left+ww>=w or top+hh>=h or min(a,b)<.45*max(a,b):
            continue
        # Reject hollow rings: an ordinary dot must be filled at its centre.
        cx,cy=int(round(x)),int(round(y))
        if not 0<=cx<w or not 0<=cy<h or binary[cy,cx]==0:
            continue
        r=max(1,min(params.depth_radius,int(max(1,min(a,b)*.25))))
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
        dots.append(dict(pixel=[float(x),float(y)],radius=float(radius),xyz=xyz,valid_3d=xyz is not None))
    dots.sort(key=lambda dot:(round(dot['pixel'][1],1),dot['pixel'][0]))
    if len(dots)>24:
        raise ValueError('圆点候选超过24个，请缩小半径范围或调整灰度阈值；本版不截断候选后猜测匹配')
    return dots
