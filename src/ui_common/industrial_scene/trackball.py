"""Continuous object-centred trackball, independent of Qt/OpenGL.

Quaternion accumulation has no Euler poles or pitch clamps. A sphere joined to
a hyperbolic sheet keeps the mapping continuous outside the virtual sphere too.
"""
import numpy as np


def multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([aw*bw-ax*bx-ay*by-az*bz,
                     aw*bx+ax*bw+ay*bz-az*by,
                     aw*by-ax*bz+ay*bw+az*bx,
                     aw*bz+ax*by-ay*bx+az*bw])


def axis_angle(axis, degrees):
    half = np.radians(degrees)*.5
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    return np.r_[np.cos(half), axis*np.sin(half)]


class Trackball:
    def __init__(self):
        self.set_view('等轴测')

    def set_view(self, name):
        yaw, pitch = {'等轴测': (-28, 57), '顶视': (0, 0),
                      '正视': (0, 90), '右视': (90, 90)}[name]
        self.quaternion = multiply(axis_angle([1, 0, 0], pitch), axis_angle([0, 0, 1], yaw))

    @property
    def matrix(self):
        w, x, y, z = self.quaternion
        return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                         [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                         [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

    @staticmethod
    def project(pos, width, height, pivot):
        radius = max(1., min(width, height)*.45)
        x, y = (pos[0]-pivot[0])/radius, (pivot[1]-pos[1])/radius
        squared = x*x+y*y
        z = np.sqrt(1-squared) if squared <= .5 else .5/np.sqrt(squared)
        vector = np.array([x, y, z])
        return vector/np.linalg.norm(vector)

    def drag(self, start, end, width, height, pivot):
        if start == end:
            return False
        a = self.project(start, width, height, pivot)
        b = self.project(end, width, height, pivot)
        cross = np.cross(a, b)
        delta = np.r_[1+float(np.clip(a @ b, -1, 1)), cross]
        norm = np.linalg.norm(delta)
        if norm < 1e-14:  # Antipodal fallback, not a mouse movement threshold.
            axis = np.cross(a, np.eye(3)[np.argmin(np.abs(a))])
            delta = np.r_[0., axis/np.linalg.norm(axis)]
        else:
            delta /= norm
        self.quaternion = multiply(delta, self.quaternion)
        self.quaternion /= np.linalg.norm(self.quaternion)
        return True
