"""Bounded, progressive, per-frame render copies. Original arrays stay untouched.

Build on a worker thread. A scene is an immutable snapshot; cached packs can be
shared with the GUI while a subsequent frame is being prepared.
"""
from dataclasses import dataclass
from math import gcd
import numpy as np

PACK_DTYPE = np.dtype([('position', '<f4', (3,)), ('color', 'u1', (4,))])


@dataclass(frozen=True)
class RenderPolicy:
    static_points: int = 5_000_000
    moving_points: int = 500_000
    per_frame_points: int = 5_000_000
    restore_ms: int = 220

    def __post_init__(self):
        if not 0 < self.moving_points <= self.static_points or self.per_frame_points <= 0:
            raise ValueError('Invalid render point budget')


POLICIES = {
    '流畅': RenderPolicy(1_000_000, 100_000),
    '均衡': RenderPolicy(),
    '细节': RenderPolicy(10_000_000, 1_000_000),
}


@dataclass(frozen=True)
class FrameSource:
    points: np.ndarray
    colors: object
    revision: int = 0

    @property
    def key(self):
        return id(self.points), id(self.colors), self.revision


def sources_from_layers(layers):
    return tuple(FrameSource(layer.points, layer.colors, getattr(layer, 'revision', 0))
                 for layer in layers if layer.visible)


def allocate_counts(sizes, budget):
    """Integer proportional allocation, bounded exactly by a global budget."""
    total = sum(sizes)
    if total <= budget:
        return tuple(sizes)
    cumulative, previous, result = 0, 0, []
    for size in sizes:
        cumulative += size
        current = cumulative * budget // total
        result.append(current - previous)
        previous = current
    return tuple(result)


def progressive_indices(size, count, start=0):
    """A coprime stride visits each original index at most once, without a full
    permutation allocation. Every draw prefix spans the source acquisition.
    This is display-only decimation, not voxel averaging or algorithm input.
    """
    if not 0 <= start <= start + count <= size:
        raise ValueError('Invalid sample range')
    stride = max(1, int(size * .618033988749895))
    while gcd(stride, size) != 1:
        stride += 1
    return (np.arange(start, start + count, dtype=np.uint64) * stride % size).astype(np.intp)


@dataclass(frozen=True)
class PackedFrame:
    source: FrameSource   # Keeps source identities alive; no original data copy.
    packed: np.ndarray
    origin: np.ndarray
    bounds: np.ndarray

    @property
    def key(self):
        return self.source.key


@dataclass(frozen=True)
class PreparedScene:
    frames: tuple
    counts: tuple
    original_points: int
    bounds: object
    builds: int

    @property
    def stored_points(self):
        return sum(len(frame.packed) for frame in self.frames)

    def draw_counts(self, moving, policy):
        return allocate_counts(self.counts, policy.moving_points) if moving else self.counts


class FrameRenderCache:
    def __init__(self):
        self._frames = {}

    def prepare(self, sources, policy):
        sizes = [min(len(source.points), policy.per_frame_points) for source in sources]
        counts = allocate_counts(sizes, policy.static_points)
        frames, drawn, current, builds = [], [], {}, 0
        # Copy the dict: old scene arrays remain owned by old GUI snapshots.
        for source, target in zip(sources, counts):
            if not target:
                continue
            old = self._frames.get(source.key)
            if old is not None and target <= len(old.packed) <= 2 * target:
                frame = old
            else:
                if old is None:
                    bounds = np.array([source.points.min(axis=0), source.points.max(axis=0)])
                    origin = (bounds[0] + bounds[1]) * .5
                else:
                    bounds, origin = old.bounds, old.origin
                packed = np.empty(target, dtype=PACK_DTYPE)
                for start in range(0, target, 262144):
                    count = min(262144, target - start)
                    idx = progressive_indices(len(source.points), count, start)
                    block = packed[start:start + count]
                    # Subtract a local float64 origin before float32 conversion.
                    block['position'] = source.points[idx] - origin
                    if source.colors is None:
                        block['color'][:, :3] = [168, 206, 232]
                    else:
                        block['color'][:, :3] = np.clip(source.colors[idx] * 255, 0, 255).astype(np.uint8)
                    block['color'][:, 3] = 255
                packed.setflags(write=False)
                frame = PackedFrame(source, packed, origin, bounds)
                builds += 1
            current[source.key] = frame
            frames.append(frame)
            drawn.append(target)
        self._frames = current
        bounds = (np.array([np.min([f.bounds[0] for f in frames], axis=0),
                            np.max([f.bounds[1] for f in frames], axis=0)]) if frames else None)
        return PreparedScene(tuple(frames), tuple(drawn), sum(len(s.points) for s in sources), bounds, builds)
