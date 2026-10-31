"""Local camera estimation and conservative, auditable background plates.

All coordinates refer to the supplied crop.  Camera matrices map frame 0
coordinates into the corresponding frame.  No neural model or network is used.
The returned diagnostics explicitly distinguish temporally observed grass from
spatially borrowed texture and inpainted pixels; those are not ground truth.
"""

from __future__ import annotations

import warnings
import cv2
import numpy as np


def _mask(mask):
    return (np.asarray(mask) > 0).astype(np.uint8) * 255


def _disk(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def _smooth(values, sigma=1.5):
    a = np.asarray(values, dtype=np.float64)
    if len(a) < 3:
        return a.copy()
    return cv2.GaussianBlur(a.reshape(-1, 1), (1, 0), sigmaX=0, sigmaY=sigma,
                            borderType=cv2.BORDER_REPLICATE).reshape(a.shape)


def _affine_fit(a, b):
    if len(a) < 12:
        return None, {"tracks": int(len(a)), "inliers": 0}
    fit, good = cv2.estimateAffine2D(
        np.asarray(a, np.float32), np.asarray(b, np.float32),
        method=cv2.RANSAC, ransacReprojThreshold=1.8, maxIters=2500,
        confidence=0.995, refineIters=15,
    )
    if fit is None or good is None:
        return None, {"tracks": int(len(a)), "inliers": 0}
    keep = good.ravel().astype(bool)
    projected = cv2.transform(np.asarray(a, np.float32).reshape(1, -1, 2), fit)[0]
    err = np.linalg.norm(projected - b, axis=1)
    out = np.eye(3, dtype=np.float64)
    out[:2] = fit
    return out, {"tracks": int(len(a)), "inliers": int(keep.sum()),
                 "median_error_px": float(np.median(err[keep])) if keep.any() else None}


def _match(previous, current, previous_mask, current_mask):
    h, w = previous.shape
    allowed = 255 - cv2.dilate(previous_mask, _disk(24))
    allowed[:12] = 0
    allowed[-12:] = 0
    allowed[:, :12] = 0
    allowed[:, -12:] = 0
    points = cv2.goodFeaturesToTrack(previous, mask=allowed, maxCorners=900,
                                    qualityLevel=0.008, minDistance=8, blockSize=7)
    if points is None:
        return None, {"tracks": 0, "inliers": 0}
    next_points, ok, _ = cv2.calcOpticalFlowPyrLK(
        previous, current, points, None, winSize=(23, 23), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 0.01),
    )
    if next_points is None:
        return None, {"tracks": 0, "inliers": 0}
    back, back_ok, _ = cv2.calcOpticalFlowPyrLK(
        current, previous, next_points, None, winSize=(23, 23), maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 35, 0.01),
    )
    p = points.reshape(-1, 2)
    q = next_points.reshape(-1, 2)
    fb = np.linalg.norm(back.reshape(-1, 2) - p, axis=1)
    keep = ok.ravel().astype(bool) & back_ok.ravel().astype(bool) & (fb < 0.8)
    keep &= (q[:, 0] >= 0) & (q[:, 0] < w) & (q[:, 1] >= 0) & (q[:, 1] < h)
    x = np.clip(q[:, 0].astype(int), 0, w - 1)
    y = np.clip(q[:, 1].astype(int), 0, h - 1)
    next_exclude = cv2.dilate(current_mask, _disk(24))
    keep &= next_exclude[y, x] == 0
    return _affine_fit(p[keep], q[keep])


def estimate_camera(frames, masks):
    """Return N matrices mapping frame 0 to each frame, excluding the subject.

    RANSAC fits a full local affine background transform. In this ground-level
    crop, parallax gives horizontal shear; fitting a similarity incorrectly
    converts that shear to accumulated roll. A weak temporal smoothing
    suppresses estimation noise, not the animal's motion. Diagnostics
    are available as ``estimate_camera.last_diagnostics``.
    """
    if len(frames) != len(masks) or len(frames) == 0:
        raise ValueError("frames and masks must have the same non-zero length")
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    bins = [_mask(m) for m in masks]
    accumulated = [np.eye(3, dtype=np.float64)]
    diagnostics = [{"frame": 0, "method": "reference"}]
    for t in range(1, len(frames)):
        step, diag = _match(grays[t - 1], grays[t], bins[t - 1], bins[t])
        if step is not None:
            scales = np.linalg.svd(step[:2, :2], compute_uv=False)
            plausible = (diag.get("inliers", 0) >= 15 and
                         scales.min() > 0.96 and scales.max() < 1.04 and
                         np.linalg.det(step[:2, :2]) > 0 and
                         np.linalg.norm(step[:2, 2]) < 30)
        else:
            plausible = False
        if not plausible:
            step = np.eye(3)
            diag["failed"] = True
        accumulated.append(step @ accumulated[-1])
        diag.update(frame=t, method="background_LK_full_affine_RANSAC",
                    step_affine=step.tolist())
        diagnostics.append(diag)
    result = np.stack(accumulated)
    # Preserve all six affine coefficients, including shear; do not reconstruct
    # these matrices as similarities after estimating the full affine model.
    for row in range(2):
        for col in range(3):
            result[:, row, col] = _smooth(result[:, row, col])
    anchor = np.linalg.inv(result[0].copy())
    result = result @ anchor
    estimate_camera.last_diagnostics = diagnostics
    return result


def _shift(image, dx, dy=0, interpolation=cv2.INTER_NEAREST):
    h, w = image.shape[:2]
    return cv2.warpAffine(image, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h),
                          flags=interpolation, borderMode=cv2.BORDER_CONSTANT)


def clean_background(frames, masks, camera):
    """Restore from sharp, directly registered neighbour frames, not an atlas.

    Returns (cleaned_frames, info). Each temporal pixel carries its donor frame
    ID. Multi-depth grass is registered in overlapping height bands; no temporal
    median is used. Spatial borrowing and final inpainting are explicit fallbacks.
    Only the supplied target mask plus a 10-pixel feather band can change.
    """
    if len(frames) != len(masks) or len(frames) != len(camera) or len(frames) == 0:
        raise ValueError("frames, masks and camera lengths must agree")
    n = len(frames)
    h, w = frames[0].shape[:2]
    bins = [_mask(m) for m in masks]
    expanded = [cv2.dilate(m, _disk(10)) for m in bins]
    sift = cv2.SIFT_create(nfeatures=2200, contrastThreshold=0.012)
    features = []
    for t, frame in enumerate(frames):
        allowed = 255 - cv2.dilate(bins[t], _disk(24))
        allowed[:8] = 0; allowed[-8:] = 0
        allowed[:, :8] = 0; allowed[:, -8:] = 0
        kp, desc = sift.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), allowed)
        features.append((np.array([k.pt for k in kp], np.float32), desc))
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=32))
    source_ids = np.full((n, h, w), -1, np.int16)
    # -1 untouched, -2 spatial donor in same frame, -3 inpaint; >=0 video donor.
    cleaned = []
    repairs = []
    registration_stats = []
    previous_sources = []
    total_temporal = total_spatial = total_inpaint = total_required = 0
    band_edges = np.linspace(0, h, 4).astype(int)
    for t in range(n):
        target = expanded[t] > 0
        remaining = target.copy()
        plate = frames[t].copy()
        # Prefer a previous strong donor to reduce frame-to-frame source changes.
        candidates = list(previous_sources)
        for step in (4, 8, 14, 22, 34, 50, 74, 102):
            candidates += [t - step, t + step]
        candidates += [0, n - 1]
        candidates = list(dict.fromkeys(d for d in candidates if 0 <= d < n and d != t))
        dest_points, dest_desc = features[t]
        local_regs = []
        for d in candidates:
            if not remaining.any() or dest_desc is None:
                break
            donor_points, donor_desc = features[d]
            if donor_desc is None or len(donor_desc) < 12 or len(dest_desc) < 12:
                continue
            pairs = matcher.knnMatch(donor_desc, dest_desc, k=2)
            good = [a for pair in pairs if len(pair) == 2
                    for a, b in [pair] if a.distance < 0.70 * b.distance]
            if len(good) < 14:
                continue
            a = np.asarray([donor_points[m.queryIdx] for m in good], np.float32)
            b = np.asarray([dest_points[m.trainIdx] for m in good], np.float32)
            used_for_donor = 0
            donor_errors = []
            for band in range(3):
                y0, y1 = band_edges[band:band + 2]
                active = remaining[y0:y1]
                if not active.any():
                    continue
                # Fit near the destination band's depth. Padding avoids seams
                # caused by estimating from too few grass features.
                select = (b[:, 1] >= y0 - 150) & (b[:, 1] < y1 + 150)
                aa, bb = a[select], b[select]
                if len(aa) < 14:
                    aa, bb = a, b
                if len(aa) < 14:
                    continue
                fit, inliers = cv2.estimateAffine2D(
                    aa, bb, method=cv2.RANSAC, ransacReprojThreshold=1.7,
                    maxIters=2200, confidence=0.995, refineIters=15)
                if fit is None or inliers is None:
                    continue
                keep = inliers.ravel().astype(bool)
                if keep.sum() < 12 or keep.sum() / len(aa) < 0.24:
                    continue
                sv = np.linalg.svd(fit[:, :2], compute_uv=False)
                if sv.min() < 0.55 or sv.max() > 1.7 or np.linalg.det(fit[:, :2]) <= 0:
                    continue
                projected = cv2.transform(aa.reshape(1, -1, 2), fit)[0]
                error = float(np.median(np.linalg.norm(projected[keep] - bb[keep], axis=1)))
                if error > 1.5:
                    continue
                donor = cv2.warpAffine(frames[d], fit, (w, h), flags=cv2.INTER_LINEAR,
                                       borderMode=cv2.BORDER_CONSTANT)
                clear = cv2.warpAffine(255 - expanded[d], fit, (w, h),
                                       flags=cv2.INTER_NEAREST) > 254
                # Reject interpolated target-boundary contamination.
                clear = cv2.erode(clear.astype(np.uint8), _disk(2)) > 0
                use = remaining & clear
                use[:y0] = False; use[y1:] = False
                count = int(use.sum())
                if count:
                    plate[use] = donor[use]
                    source_ids[t][use] = d
                    remaining[use] = False
                    used_for_donor += count
                    donor_errors.append(error)
            if used_for_donor:
                local_regs.append({"source_frame": int(d), "pixels": used_for_donor,
                                   "median_feature_error_px": float(np.median(donor_errors))})
        temporal_pixels = int((source_ids[t] >= 0).sum())
        # Residual holes use same-height nearby texture. This is intentionally
        # marked synthesis, even though its pixels originate in the real frame.
        for dx in (100, 140, 180, 220, 280, -100, -140, -180, -220, -280, 340, -340):
            if not remaining.any():
                break
            donor_clear = _shift(255 - expanded[t], dx) > 254
            use = remaining & donor_clear
            if use.any():
                donor = _shift(frames[t], dx, interpolation=cv2.INTER_LINEAR)
                plate[use] = donor[use]
                source_ids[t][use] = -2
                remaining[use] = False
        spatial_pixels = int((source_ids[t] == -2).sum())
        final_holes = remaining.astype(np.uint8) * 255
        if final_holes.any():
            plate = cv2.inpaint(plate, final_holes, 3, cv2.INPAINT_TELEA)
            source_ids[t][remaining] = -3
        inpaint_pixels = int(remaining.sum())
        # Keep the same cleanup band as the first implementation's contract.
        remove = cv2.dilate(bins[t], _disk(6))
        alpha = cv2.GaussianBlur(remove.astype(np.float32) / 255, (9, 9), 1.2)[..., None]
        out = frames[t].astype(np.float32) * (1 - alpha) + plate.astype(np.float32) * alpha
        cleaned.append(np.rint(out).clip(0, 255).astype(np.uint8))
        ranked = sorted(local_regs, key=lambda r: r["pixels"], reverse=True)
        previous_sources = [r["source_frame"] for r in ranked[:2]]
        registration_stats.append({"frame": t, "donors": local_regs})
        required = int(target.sum())
        repairs.append({"frame": t, "required_pixels": required,
                        "temporal_pixels": temporal_pixels, "spatial_pixels": spatial_pixels,
                        "inpaint_pixels": inpaint_pixels})
        total_required += required; total_temporal += temporal_pixels
        total_spatial += spatial_pixels; total_inpaint += inpaint_pixels
        if t % 20 == 0:
            print(f"background frame {t}: temporal={temporal_pixels}/{required}, "
                  f"spatial={spatial_pixels}, inpaint={inpaint_pixels}", flush=True)
    den = max(1, total_required)
    info = {
        "method": "sharp_neighbour_donors_direct_SIFT_local_full_affine_no_temporal_median",
        "camera_direction": "frame0_to_frame_t",
        "temporal_fraction_in_repair_regions": total_temporal / den,
        "spatial_borrow_fraction_in_repair_regions": total_spatial / den,
        "inpaint_fraction_in_repair_regions": total_inpaint / den,
        "source_frame_maps": source_ids,
        "temporally_observed_mask": (source_ids[0] >= 0).astype(np.uint8) * 255,
        "spatial_borrow_mask": (source_ids[0] == -2).astype(np.uint8) * 255,
        "inpaint_mask": (source_ids[0] == -3).astype(np.uint8) * 255,
        "reference_clean_bgr": cleaned[0],
        "frame_repairs": repairs,
        "direct_registration": registration_stats,
        "provenance_codes": {"-1": "untouched", "-2": "same_frame_spatial_texture",
                             "-3": "inpaint", ">=0": "video_donor_frame"},
        "caution": "Donor availability and low feature residual do not prove seamless repair. Inspect the visible area outside the paper, especially leg gaps and the tail.",
    }
    return cleaned, info
