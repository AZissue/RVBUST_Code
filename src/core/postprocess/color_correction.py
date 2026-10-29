"""Bounded colour-gain estimation, without geometry edits or camera assumptions.

Single-cloud correction estimates illumination, not material reflectance. Results
are visual mitigation, never a reconstruction of calibrated photographic colour.
"""
from dataclasses import dataclass, asdict
import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


@dataclass(frozen=True)
class ColorParameters:
    scale: float = 30.0
    strength: float = .6
    max_gain: float = 1.5
    sample_limit: int = 20000
    overlap_distance: float = 2.0
    min_samples: int = 24
    chunk_size: int = 65536
    seam_strength: float = .6
    algorithm: str = 'balanced'
    voxel_size: float = 0.

    def validate(self):
        if self.algorithm not in ('balanced', 'aggressive', 'spatial', 'image_fusion'):
            raise ValueError('未知颜色统一算法')
        if not np.isfinite(self.voxel_size) or self.voxel_size < 0:
            raise ValueError('预下采样体素必须为非负有限值（0关闭）')
        if not np.isfinite(self.seam_strength) or not 0 <= self.seam_strength <= 1:
            raise ValueError('接缝融合强度必须在0..100%之间')
        if not np.isfinite(self.scale) or self.scale <= 0:
            raise ValueError('空间尺度必须为正有限值（mm）')
        if not np.isfinite(self.overlap_distance) or self.overlap_distance <= 0:
            raise ValueError('重叠距离必须为正有限值（mm）')
        if not np.isfinite(self.strength) or not 0 < self.strength <= 1:
            raise ValueError(f'参数为0或非法：强度={self.strength*100:g}%，必须大于0且不超过100%')
        if not np.isfinite(self.max_gain) or not 1 < self.max_gain <= 2:
            raise ValueError(f'无可应用校正：增益上限={self.max_gain:g}，必须大于1且不超过2')
        for value, minimum, maximum in ((self.sample_limit, 24, 100000),
                (self.min_samples, 4, self.sample_limit), (self.chunk_size, 1, 262144)):
            if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
                raise ValueError('估计样本/邻域样本/分块参数无效')


def _sample(points, colors, limit):
    ids = np.linspace(0, len(points)-1, min(len(points), limit), dtype=np.int64)
    return points[ids], colors[ids]


def _gray(colors, chunk):
    return all(np.max(np.ptp(colors[i:i+chunk], axis=1), initial=0) <= 1e-6
               for i in range(0, len(colors), chunk))


class NoColorCorrection(ValueError):
    """Estimation succeeded but publishing an effectively identical result is forbidden."""
    def __init__(self, message, reports):
        super().__init__(message)
        self.reports = reports


def _apply(colors, gains, gray, params):
    out = np.empty_like(colors)
    bins = 8192
    histogram = np.zeros(bins, dtype=np.int64)
    estimated_low, estimated_high = np.full(3, np.inf), np.full(3, -np.inf)

    def apply_pass(k, estimate=False):
        clipped = changed = changed5 = changed10 = 0
        low, high = np.full(3, np.inf), np.full(3, -np.inf)
        for begin in range(0, len(colors), params.chunk_size):
            end = min(len(colors), begin+params.chunk_size)
            original = colors[begin:end]
            raw = gains(begin, end)
            log = params.strength*np.clip(np.log(raw), -np.log(params.max_gain), np.log(params.max_gain))
            gain = np.exp(k*log)
            values = original*gain
            if gray:
                values[:] = values.mean(axis=1, keepdims=True)
            clipped += np.count_nonzero(values > 1)
            out[begin:end] = np.clip(values, 0, 1)
            relative = np.max(abs(out[begin:end]-original)/np.maximum(original, .02), axis=1)
            changed += np.count_nonzero(relative > .005)
            changed5 += np.count_nonzero(relative > .05)
            changed10 += np.count_nonzero(relative > .1)
            low = np.minimum(low, gain.min(axis=0))
            high = np.maximum(high, gain.max(axis=0))
            if estimate:
                np.minimum(estimated_low, raw.min(axis=0), out=estimated_low)
                np.maximum(estimated_high, raw.max(axis=0), out=estimated_high)
                # Each increasing channel has a maximum safe exponent. A bounded
                # histogram finds a conservative global k without N-sized gains.
                limits = np.full_like(original, np.inf)
                np.divide(-np.log(np.maximum(original, 1e-300)), log,
                          out=limits, where=(log > 0) & (original > 0))
                active = limits[(limits >= 0) & (limits < 1)]
                histogram[:] += np.bincount(np.minimum((active*bins).astype(np.int64), bins-1), minlength=bins)
        return dict(gain_min=low.tolist(), gain_max=high.tolist(), clipped_fraction=clipped/colors.size,
            max_abs_log_gain=float(max(abs(np.log(low)).max(), abs(np.log(high)).max())),
            changed_fraction=changed/len(colors), changed_gt5_fraction=changed5/len(colors),
            changed_gt10_fraction=changed10/len(colors))

    report = apply_pass(1., estimate=True)
    requested_clip = report['clipped_fraction']
    k = 1.
    if requested_clip > .01:
        budget = int(.01*colors.size)
        index = int(np.searchsorted(np.cumsum(histogram), budget, side='right'))
        k = max(0., (index-1)/bins)
        amplitude = np.expm1(report['max_abs_log_gain']*k)
        if k < .2 or amplitude < .05:
            reason = f'受高光限制，可应用幅度不足：k={k:.1%}，最大变化约{amplitude:.1%}；请降低强度或调整尺度'
            report.update(adaptive_scale=k, actual_strength=params.strength*k, params=asdict(params),
                          status='无可应用校正', reason=reason)
            raise NoColorCorrection(reason, [report])
        report = apply_pass(k)
        if report['clipped_fraction'] > .01 + 1e-12:
            raise ValueError('高光自适应保护未能达到1%截断预算，未发布结果')
    ids = np.linspace(0, len(colors)-1, min(len(colors), params.sample_limit), dtype=np.int64)
    before = colors[ids].mean(axis=1)
    after = out[ids].mean(axis=1)
    spread_before = float(np.ptp(np.quantile(before, [.1, .9])))
    spread_after = float(np.ptp(np.quantile(after, [.1, .9])))
    retention = spread_after/spread_before if spread_before > 1e-12 else 1.
    report.update(estimated_gain_min=estimated_low.tolist(), estimated_gain_max=estimated_high.tolist(),
        requested_clipped_fraction=requested_clip, adaptive_scale=k, actual_strength=params.strength*k,
        distribution_before=spread_before, distribution_after=spread_after,
        distribution_retention=retention, distribution_samples=len(ids),
        material_warning=retention < .6, params=asdict(params))
    report['no_correction'] = report['max_abs_log_gain'] < .005 or report['changed_fraction'] < .01
    return out, report


def _no_correction_message(report):
    return (f"无可应用校正：最大对数幅度{report['max_abs_log_gain']:.2%}，"
            f"变化点{report['changed_fraction']:.2%}；请检查强度/增益上限、调整尺度或确认数据本身无可估计色差")


def _overlap(reference, target, reference_colors, colors, gray, params):
    ref_tree, tree = cKDTree(reference), cKDTree(target)
    distances, nearest = ref_tree.query(target)
    _, reverse = tree.query(reference)
    mutual = (distances <= params.overlap_distance) & (reverse[nearest] == np.arange(len(target)))
    candidate = int(mutual.sum())
    if candidate < params.min_samples:
        raise ValueError(f'可靠双向重叠不足：{candidate}/{params.min_samples}，距离阈值 {params.overlap_distance:g} mm')
    if np.median(distances[mutual]) > .75*params.overlap_distance:
        raise ValueError('重叠距离集中在阈值边缘，可能未正确对齐')
    left, right = reference_colors[nearest[mutual]], colors[mutual]
    if gray:
        left = np.repeat(left.mean(axis=1, keepdims=True), 3, axis=1)
        right = np.repeat(right.mean(axis=1, keepdims=True), 3, axis=1)
    valid = ((left > .02) & (left < .98) & (right > .02) & (right < .98)).all(axis=1)
    left, right = left[valid], right[valid]
    if len(left) < params.min_samples:
        raise ValueError('重叠区有效非黑/非饱和颜色样本不足')
    if min(np.max(np.quantile(c, .9, axis=0)-np.quantile(c, .1, axis=0))
           for c in (left, right)) < .015:
        raise ValueError('重叠颜色动态范围过低，无法可靠估计')
    ratios = np.log(left/right)
    median = np.median(ratios, axis=0)
    mad = np.median(np.abs(ratios-median), axis=0)
    inliers = (np.abs(ratios-median) <= np.maximum(3*1.4826*mad, .03)).all(axis=1)
    if inliers.sum() < max(params.min_samples, len(ratios)*.5) or np.max(mad) > .25:
        raise ValueError('重叠颜色对应不一致，稳健内点不足')
    gain = np.exp(np.median(ratios[inliers], axis=0))
    if np.any((gain < .4) | (gain > 2.5)):
        raise ValueError('估计色差过大，增益不可信')
    return gain, dict(matches=int(inliers.sum()), candidates=candidate,
        distance_median_mm=float(np.median(distances[mutual])), estimated_gain=gain.tolist())


def _single(points, colors, gray, params):
    xyz, rgb = _sample(points, colors, params.sample_limit)
    valid = ((rgb > .02) & (rgb < .98)).all(axis=1)
    xyz, rgb = xyz[valid], rgb[valid]
    if len(xyz) < params.min_samples:
        raise ValueError('单云有效颜色估计样本不足')
    if gray:
        rgb = np.repeat(rgb.mean(axis=1, keepdims=True), 3, axis=1)
    log_rgb = np.log(rgb)
    # Fixed spatial cells aggregate robust statistics only; they are NOT
    # independently normalized. A broad Gaussian field and interpolation follow.
    _, inverse, counts = np.unique(np.floor(xyz/(params.scale/2)), axis=0,
                                  return_inverse=True, return_counts=True)
    order = np.argsort(inverse, kind='stable')
    starts = np.r_[0, np.cumsum(counts)]
    nodes, stats, weights = [], [], []
    for i, count in enumerate(counts):
        if count < 4:
            continue
        ids = order[starts[i]:starts[i+1]]
        nodes.append(xyz[ids].mean(axis=0))
        stats.append(np.median(log_rgb[ids], axis=0))
        weights.append(count)
    if len(nodes) < 2:
        raise ValueError('空间邻域支持不足，请增大空间尺度或样本上限')
    nodes, stats, weights = np.asarray(nodes), np.asarray(stats), np.asarray(weights)
    tree = cKDTree(nodes)
    distances, ids = tree.query(nodes, k=min(32, len(nodes)))
    weight = np.exp(-.5*(distances/params.scale)**2) * np.sqrt(weights[ids])
    weight[distances > 2.5*params.scale] = 0
    supported = ((weights[ids]*(distances <= 2.5*params.scale)).sum(axis=1) >= params.min_samples)
    field = (stats[ids]*weight[..., None]).sum(axis=1)/weight.sum(axis=1)[:, None]
    # Geometrically disconnected islands must not be pulled to one global
    # material colour. The existing bounded k-NN graph supplies local anchors;
    # continuous surfaces remain ambiguous and are reported as such.
    rows = np.repeat(np.arange(len(nodes)), ids.shape[1])
    within = (distances <= 2.5*params.scale).ravel()
    graph = coo_matrix((np.ones(int(within.sum())), (rows[within], ids.ravel()[within])),
                       shape=(len(nodes), len(nodes))).tocsr()
    component_count, labels = connected_components(graph, directed=False)
    _, sample_node = tree.query(xyz, k=1)
    membership = labels[sample_node]
    grouped = np.argsort(membership, kind='stable')
    _, component_counts = np.unique(membership[grouped], return_counts=True)
    offsets = np.r_[0, np.cumsum(component_counts)]
    anchors = np.tile(np.median(log_rgb, axis=0), (component_count, 1))
    for index, label in enumerate(np.unique(membership)):
        anchors[label] = np.median(log_rgb[grouped[offsets[index]:offsets[index+1]]], axis=0)
    log_gain = anchors[labels]-field
    log_gain[~supported] = 0
    if not supported.any():
        raise ValueError('空间邻域样本不足，未进行颜色校正')
    # A spatial gain alone cannot remove a discontinuity: coincident points
    # receive the same gain. Estimate a colour-conditioned local residual too.
    # Compact spatial support avoids distant sheets; a redescending range
    # kernel excludes black/white patterns and large material boundaries.
    seam_tree = cKDTree(xyz)
    radius = params.scale / (4 if params.algorithm == 'balanced' else 2)
    def gains(begin, end):
        d, ix = tree.query(points[begin:end], k=min(8, len(nodes)))
        w = np.exp(-.5*(d/params.scale)**2)
        w[(d > 2.5*params.scale) | ~supported[ix]] = 0
        total = w.sum(axis=1)
        log = (log_gain[ix]*w[..., None]).sum(axis=1)/np.maximum(total[:, None], 1e-30)
        log[total == 0] = 0
        if params.seam_strength:
            sd, si = seam_tree.query(points[begin:end], k=min(24, len(xyz)))
            original = colors[begin:end]
            delta = log_rgb[si] - np.log(np.maximum(original[:, None, :], .002))
            difference = np.max(np.abs(delta), axis=2)
            width, cutoff = (.30, .55) if params.algorithm == 'balanced' else (.70, 1.4)
            if params.algorithm == 'spatial':
                # Deliberately remove luminance edges, retaining chroma edges.
                # This also removes real gray texture: explicitly opt in.
                chroma = delta - delta.mean(axis=2, keepdims=True)
                range_weight = np.exp(-(np.max(abs(chroma), axis=2)/.25)**4)
            else:
                range_weight = np.exp(-(difference/width)**4)
                range_weight[difference > cutoff] = 0
            sw = np.exp(-.5*(sd/radius)**2) * range_weight
            sw[sd > radius] = 0
            valid_color = ((original > .02) & (original < .98)).all(axis=1)
            support = (sw > .05).sum(axis=1) >= 4
            residual = (delta*sw[..., None]).sum(axis=1)/np.maximum(sw.sum(axis=1)[:, None], 1e-30)
            residual[~(valid_color & support)] = 0
            log += params.seam_strength * residual
        return np.exp(log)
    try:
        result, report = _apply(colors, gains, gray, params)
    except NoColorCorrection as exc:
        for row in exc.reports:
            row.update(samples=len(xyz), nodes=len(nodes), supported_nodes=int(supported.sum()), components=component_count)
        raise
    report.update(samples=len(xyz), nodes=len(nodes), supported_nodes=int(supported.sum()), components=component_count,
                  seam_radius_mm=radius, seam_strength=params.seam_strength)
    return result, report


def correct_color_layers(layers, *, reference=0, params=None):
    """Optional voxel averaging BEFORE estimation/application, with provenance."""
    from .session import CloudLayer
    from .processing import voxel_downsample
    params = params or ColorParameters()
    params.validate()
    if params.algorithm == 'image_fusion':
        raise ValueError('原始2D融合需要DB原始帧和拼接位姿，请从后处理颜色统一入口执行')
    if any(layer.colors is None for layer in layers):
        raise ValueError('颜色统一拒绝无色或混合有色/无色输入')
    inputs = layers
    if params.voxel_size:
        inputs = []
        for layer in layers:
            xyz, rgb = voxel_downsample(layer.points, layer.colors, params.voxel_size)
            inputs.append(CloudLayer(layer.name, xyz, rgb, source=layer.source, origins=layer.origins))
    colors, reports = unify_colors(inputs, reference=reference, params=params)
    outputs = []
    for source, layer, rgb, report in zip(layers, inputs, colors, reports):
        report.update(input_points=len(source.points), output_points=len(layer.points),
                      voxel_size_mm=params.voxel_size, algorithm=params.algorithm)
        outputs.append(CloudLayer(source.name+' · 颜色统一', layer.points, rgb,
                                  source=source.source, origins=source.origins))
    return outputs, reports


def unify_colors(layers, *, reference=0, params=None):
    """Return new colour arrays and diagnostics in input order; no XYZ edits.

    A mixed/uncoloured batch is rejected. Unreliable overlap layers remain
    unchanged with an explicit skipped report. If all targets fail, reject.
    """
    params = params or ColorParameters()
    params.validate()
    if params.algorithm == 'image_fusion':
        raise ValueError('原始2D融合需要DB原始帧和拼接位姿，请从后处理颜色统一入口执行')
    if not layers or not isinstance(reference, int) or not 0 <= reference < len(layers):
        raise ValueError('请选择有效的颜色输入和参考层')
    if any(layer.colors is None for layer in layers):
        raise ValueError('颜色统一拒绝无色或混合有色/无色输入，不会补造原始颜色')
    for layer in layers:
        if (layer.points.ndim != 2 or layer.points.shape[1] != 3 or not len(layer.points)
                or layer.colors.shape != layer.points.shape):
            raise ValueError('点云坐标/颜色必须为 N×3 数据')
        for begin in range(0, len(layer.points), params.chunk_size):
            points = layer.points[begin:begin+params.chunk_size]
            colors = layer.colors[begin:begin+params.chunk_size]
            if (not np.isfinite(points).all() or not np.isfinite(colors).all()
                    or np.any(colors < 0) or np.any(colors > 1)):
                raise ValueError('点云坐标/颜色必须有限，颜色范围 0..1')
    if len(layers) == 1:
        layer = layers[0]
        colors, report = _single(layer.points, layer.colors, _gray(layer.colors, params.chunk_size), params)
        report.update(mode='空间低频', status='已处理')
        if report['no_correction']:
            report.update(status='无可应用校正', reason=_no_correction_message(report))
            raise NoColorCorrection(report['reason'], [report])
        return [colors], [report]
    ref = layers[reference]
    xyz, rgb = _sample(ref.points, ref.colors, params.sample_limit)
    outputs, reports, corrected = [], [], 0
    for index, layer in enumerate(layers):
        if index == reference:
            outputs.append(layer.colors.copy())
            reports.append(dict(mode='重叠匹配', status='参考不变', samples=len(xyz),
                gain_min=[1.]*3, gain_max=[1.]*3, estimated_gain_min=[1.]*3, estimated_gain_max=[1.]*3,
                changed_fraction=0., changed_gt5_fraction=0., changed_gt10_fraction=0., distribution_retention=1.,
                clipped_fraction=0., adaptive_scale=1., actual_strength=0., params=asdict(params)))
            continue
        points, colors = _sample(layer.points, layer.colors, params.sample_limit)
        try:
            gray = _gray(layer.colors, params.chunk_size)
            gain, report = _overlap(xyz, points, rgb, colors, gray, params)
            result, applied = _apply(layer.colors, lambda a, b: gain[None, :], gray, params)
            report.update(applied, mode='重叠匹配', status='已处理', samples=len(points))
            if applied['no_correction']:
                result = layer.colors.copy()
                report.update(status='跳过', reason=_no_correction_message(applied))
            else:
                corrected += 1
        except ValueError as exc:
            result, report = layer.colors.copy(), dict(mode='重叠匹配', status='跳过', reason=str(exc), samples=len(points))
        outputs.append(result)
        reports.append(report)
    if not corrected:
        message = '没有可靠重叠可校正：' + '；'.join(row.get('reason', '') for row in reports if row['status'] == '跳过')
        if any(row.get('no_correction') for row in reports):
            raise NoColorCorrection(message, reports)
        raise ValueError(message)
    return outputs, reports
