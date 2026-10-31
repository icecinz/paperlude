"""Geometry-preserving photo-paper assets and adaptive hold-frame planning.

Public API
----------
plan_segments(frames, masks, camera, fps)
    BGR uint8 source frames and target masks; camera[t] maps frame-0 pixel
    coordinates into frame-t coordinates. Returns JSON-serializable, half-open
    frame intervals. A paper selected at k must be warped for t with
    camera[t] @ inv(camera[k]). The planner holds the photographed pose while
    following the supplied placement transform. Residual target pixels are a
    background-repair requirement, not permission to speed up to video fps.
make_paper(frame, mask, seed, texture=None)
    Returns full-canvas BGRA uint8 and a 0/255 mask of *fully opaque* paper.
    No generated anatomy or geometric change: the source animal pixels are
    rendered as an understated monochrome print. Border, texture, and thin
    thickness are deterministic for a seed. Optional texture is a Pillow image,
    NumPy image, or local image path; it affects paper texture, not silhouette.

Planning uses half-resolution stabilized masks inside their common ROI.
Holds are 0.10--0.45 s, biased toward 0.25 s. Peak coverage and approximate
head/body/foot anchors have explicit limits; small residual thin legs still
need background repair. Metrics are diagnostic relative to supplied masks;
they are not a claim of perfect segmentation or visual completion.
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def _binary(mask):
    arr = np.asarray(mask)
    if arr.ndim == 3:
        arr = arr[..., 0]
    threshold = 0.5 if arr.size and float(arr.max()) <= 1.0 else 127
    return np.where(arr > threshold, 255, 0).astype(np.uint8)


def _bounds(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1,
            int(ys.max()) + 1)


def _rim_width(mask):
    x0, y0, x1, y1 = _bounds(mask)
    return float(np.clip((y1 - y0) * 0.0055, 2.4, 5.0))


def _shape_anchors(mask):
    """Approximate head, torso, and support anchors from the main component.

    These are silhouette diagnostics, not anatomical keypoint predictions.
    Ignore disconnected speckles when computing anchors, but leave the input
    mask intact so the caller's real coverage checks can still reveal errors.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count < 2:
        return np.full((3, 2), np.nan), 1.0
    main = int(1 + np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    yy, xx = np.nonzero(labels == main)
    low, high = np.percentile(yy, [0.2, 99.8])
    height = max(1.0, high-low)
    anchors = []
    for bottom, top in [(0.00, 0.16), (0.43, 0.78), (0.88, 1.01)]:
        selected = (yy >= low+bottom*height) & (yy <= low+top*height)
        if selected.any():
            anchors.append([float(np.median(xx[selected])),
                            float(np.median(yy[selected]))])
        else:
            anchors.append([float(np.median(xx)), float(np.median(yy))])
    return np.asarray(anchors), height


def plan_segments(frames, masks, camera, fps):
    """Plan low-frequency paper poses; start/end/key are source-frame indices.

    The last segment can be shorter only when the whole clip is shorter than
    the minimum. Otherwise the dynamic program partitions the whole sequence
    with regular minimum and maximum holds, avoiding a tiny trailing segment.
    Estimated leakage uses a narrow, regular rim; actual paper alpha must be
    measured again by the compositor after asset creation and camera warping.
    """
    n = len(frames)
    if n != len(masks) or n == 0:
        raise ValueError("frames and masks must be nonempty and equally long")
    fps = float(fps)
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be positive")
    height, width = np.asarray(frames[0]).shape[:2]
    transforms = (np.repeat(np.eye(3)[None], n, axis=0) if camera is None
                  else np.asarray(camera, dtype=np.float64))
    if transforms.shape != (n, 3, 3):
        raise ValueError("camera must be an N x 3 x 3 array, frame 0 -> frame t")
    stable = []
    clarity = []
    valid = []
    raw = []
    for i, (frame, mask) in enumerate(zip(frames, masks)):
        frame = np.asarray(frame)
        bm = _binary(mask)
        if frame.shape[:2] != (height, width) or bm.shape != (height, width):
            raise ValueError("all frames and masks must share one canvas")
        raw.append(bm)
        valid.append(bool(np.count_nonzero(bm)))
        inv = np.linalg.inv(transforms[i])
        stable.append(cv2.warpPerspective(
            bm, inv, (width, height), flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT, borderValue=0))
        inside = cv2.erode(bm, np.ones((3, 3), np.uint8)) > 0
        lap = cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_32F)
        clarity.append(float(np.mean(lap[inside] ** 2)) if inside.any() else 0.0)
    if not any(valid):
        raise ValueError("no nonempty target mask was supplied")

    union = np.maximum.reduce(stable)
    x0, y0, x1, y1 = _bounds(union)
    pad = 12
    x0, y0 = max(0, x0-pad), max(0, y0-pad)
    x1, y1 = min(width, x1+pad), min(height, y1+pad)
    roi_w, roi_h = x1-x0, y1-y0
    # Cap pairwise planning memory for long/high-resolution callers too.
    scale = min(0.5, np.sqrt(65000.0 / max(1, roi_w * roi_h)))
    dw, dh = max(1, round(roi_w*scale)), max(1, round(roi_h*scale))
    sampled, papers = [], []
    for bm in stable:
        roi = bm[y0:y1, x0:x1]
        small = cv2.resize(roi, (dw, dh), interpolation=cv2.INTER_NEAREST)
        radius = max(1, round(_rim_width(bm) * scale))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (2*radius+1, 2*radius+1))
        sampled.append((small > 0).ravel())
        papers.append((cv2.dilate(small, kernel) > 0).ravel())
    a = np.asarray(sampled, np.float32)
    p = np.asarray(papers, np.float32)
    areas = np.maximum(a.sum(axis=1), 1.0)
    # rows: candidate key, columns: frame to cover.
    intersections = p @ a.T
    leak = np.maximum(0, 1.0 - intersections / areas[None, :])
    exact_intersections = a @ a.T
    iou = exact_intersections / np.maximum(
        1.0, areas[:, None] + areas[None, :] - exact_intersections)
    anchor_data = [_shape_anchors(m) for m in stable]
    anchors = np.asarray([v[0] for v in anchor_data])
    heights = np.asarray([v[1] for v in anchor_data])
    # rows=candidate, columns=current frame, final axis=head/torso/support.
    anchor_distance = np.linalg.norm(
        anchors[:, None, :, :] - anchors[None, :, :, :], axis=3)
    pair_height = np.maximum(1.0, (heights[:, None]+heights[None, :])/2)
    anchor_normalized = anchor_distance / pair_height[..., None]
    sharp = np.asarray(clarity, dtype=float)
    lo, hi = np.percentile(sharp[np.asarray(valid)], [10, 90])
    sharp_norm = np.clip((sharp-lo) / max(hi-lo, 1e-6), 0.0, 1.0)
    valid = np.asarray(valid, dtype=bool)
    min_len = max(1, round(0.10 * fps))
    max_len = max(min_len, round(0.45 * fps))
    if n < min_len:
        min_len = n
    dp = np.full(n+1, np.inf)
    dp[0] = 0.0
    back = [None] * (n+1)

    for end in range(1, n+1):
        for start in range(max(0, end-max_len), end-min_len+1):
            if not np.isfinite(dp[start]):
                continue
            candidates = np.arange(start, end)[valid[start:end]]
            if not len(candidates):
                continue
            block = leak[candidates, start:end]
            means, peaks = block.mean(axis=1), block.max(axis=1)
            anchor_peak = np.nanmax(
                anchor_normalized[candidates, start:end], axis=1)
            symmetric_peak = np.maximum(
                block, leak[start:end, :][:, candidates].T).max(axis=1)
            # A narrow rim may miss an occasional thin leg; it must not leave
            # a substantially displaced head/body or most of a silhouette to
            # be disguised by a large background patch.
            allowed = ((peaks <= 0.30) & (symmetric_peak <= 0.38)
                       & (anchor_peak[:, 0] <= 0.055)
                       & (anchor_peak[:, 1] <= 0.035)
                       & (anchor_peak[:, 2] <= 0.045))
            if not allowed.any():
                continue
            duration = (end-start) / fps
            # A real edit has a cost. This stops near-identical poses from
            # producing unnecessary rapid cuts just to reduce a small leak.
            costs = (0.30 + 3.2*means + 8.0*peaks
                     + 0.17*(1-sharp_norm[candidates])
                     + 0.60*((duration-0.25)/0.12)**2
                     + 0.15*np.max(anchor_peak, axis=1)/0.055)
            costs[~allowed] = np.inf
            if start:
                # Tiny tie-breaker only; a still animal need not invent motion.
                costs += 0.045 * np.maximum(
                    0, (iou[candidates, start-1]-0.97) / 0.03)
            winner = int(np.argmin(costs))
            total = dp[start] + float(costs[winner])
            if total < dp[end]:
                dp[end] = total
                key = int(candidates[winner])
                back[end] = (start, key, float(means[winner]),
                             float(peaks[winner]), float(costs[winner]),
                             anchor_peak[winner].tolist(),
                             float(symmetric_peak[winner]))
    if back[n] is None:
        raise ValueError("cannot partition clip within hold/peak-coverage/anchor "
                         "limits; inspect masks or placement transforms")
    result = []
    end = n
    while end:
        start, key, mean_leak, max_leak, cost, anchor_peak, sym_peak = back[end]
        result.append({
            "start": int(start), "end": int(end), "key": int(key),
            "metrics": {
                "duration_seconds": float((end-start)/fps),
                "estimated_mean_uncovered_ratio": mean_leak,
                "estimated_max_uncovered_ratio": max_leak,
                "estimated_max_symmetric_uncovered_ratio": sym_peak,
                "max_anchor_deviation_height_fraction": {
                    "head": anchor_peak[0], "torso": anchor_peak[1],
                    "support": anchor_peak[2]},
                "hard_limits": {
                    "max_uncovered_ratio": 0.30,
                    "max_symmetric_uncovered_ratio": 0.38,
                    "head_height_fraction": 0.055,
                    "torso_height_fraction": 0.035,
                    "support_height_fraction": 0.045},
                "source_sharpness": float(sharp[key]),
                "source_bbox_xyxy": list(_bounds(raw[key])),
                "source_rim_pixels": _rim_width(raw[key]),
                "missing_mask_frames": int((~valid[start:end]).sum()),
                "planning_cost": cost,
                "coverage_is_estimate": True,
                "needs_actual_alpha_coverage_check": True,
            }})
        end = start
    return result[::-1]


def _texture_field(texture, rng, height, width):
    fine = rng.normal(0, 1, (height, width)).astype(np.float32)
    fine = cv2.GaussianBlur(fine, (0, 0), 0.6)
    coarse = rng.normal(0, 1, (max(2, height//64),
                              max(2, width//64))).astype(np.float32)
    coarse = cv2.resize(coarse, (width, height), interpolation=cv2.INTER_CUBIC)
    field = 0.70*fine + 0.30*coarse
    if texture is not None:
        if isinstance(texture, (str, Path)):
            tex = np.asarray(Image.open(texture).convert("L"), dtype=np.float32)
        elif isinstance(texture, Image.Image):
            tex = np.asarray(texture.convert("L"), dtype=np.float32)
        else:
            tex = np.asarray(texture, dtype=np.float32)
            if tex.ndim == 3:
                tex = tex[..., :3].mean(axis=2)
        tex = cv2.resize(tex, (width, height), interpolation=cv2.INTER_LINEAR)
        tex = (tex-np.mean(tex)) / max(float(np.std(tex)), 1.0)
        field = 0.45*field + 0.55*tex
    return np.clip(field, -2.5, 2.5)


def make_paper(frame, mask, seed, texture=None):
    """Return a restrained photographic print, retaining the source geometry.

    The returned alpha includes antialiasing and a very thin lower/right paper
    thickness. The second return value contains alpha >= 254 only, so neither
    a translucent edge nor a shadow is incorrectly treated as solid coverage.
    Ground/contact shadows belong in the compositor, not this flat asset.
    """
    bgr = np.asarray(frame)
    if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("frame must be BGR uint8")
    bm = _binary(mask)
    height, width = bgr.shape[:2]
    if bm.shape != (height, width):
        raise ValueError("mask must share the source-frame canvas")
    if not np.any(bm):
        return np.zeros((height, width, 4), np.uint8), bm
    rng = np.random.default_rng(int(seed))
    grain = _texture_field(texture, rng, height, width)
    edge_noise = rng.normal(0, 1, (max(2, height//7),
                                  max(2, width//7))).astype(np.float32)
    edge_noise = cv2.resize(edge_noise, (width, height),
                            interpolation=cv2.INTER_CUBIC)
    edge_noise = cv2.GaussianBlur(edge_noise, (0, 0), 0.9)
    outside_dist = cv2.distanceTransform(255-bm, cv2.DIST_L2, 5)
    rim = _rim_width(bm)
    varied_rim = rim + np.clip(edge_noise, -1.7, 1.7) * 0.65
    paper = (outside_dist <= varied_rim).astype(np.uint8)*255
    # A single subpixel-scale thickness, not the heavy sticker shadow used
    # by generic cutout filters. RGB outside alpha is zeroed before return.
    thickness = cv2.warpAffine(paper, np.float32([[1, 0, 0.8], [0, 1, 1.0]]),
                               (width, height), flags=cv2.INTER_LINEAR)
    alpha = np.maximum(paper, thickness)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.35)
    base = np.empty((height, width, 3), dtype=np.float32)
    base[:] = np.array([225.0, 236.0, 241.0], np.float32)
    base += grain[..., None]*1.8
    side = (thickness > paper) & (paper < 127)
    base[side] = np.array([162.0, 173.0, 181.0], np.float32)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # One curve for the entire clip (source animal pooled P1=37, P99=127).
    # The flat source needs a print-like contrast expansion. Never stretch
    # each pose separately: that would make the ink density flicker at cuts.
    normalized = np.clip((gray-30.0)/105.0,0.0,1.0)
    ink = 30.0 + 195.0*np.power(normalized, 0.85)
    printed = ink[..., None]*np.array([0.965, 0.985, 1.0], np.float32)
    printed += grain[..., None]*2.2
    body = bm.astype(np.float32)/255.0
    base = base*(1-body[..., None]) + printed*body[..., None]
    base = np.clip(base, 0, 255).astype(np.uint8)
    base[alpha == 0] = 0
    out = np.dstack([base, alpha])
    opaque = np.where(alpha >= 254, 255, 0).astype(np.uint8)
    return out, opaque
