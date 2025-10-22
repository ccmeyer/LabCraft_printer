# nozzle_analyzer.py
import cv2, numpy as np
from math import sqrt

# ---------------- Calibration default ----------------
UM_PER_PX = 0.3896  # microns per pixel (override from UI)

# ---- Tunables (defaults; can be overridden via function args) ----
DEFAULT_LO = 25
DEFAULT_HI = 25
R_MIN_FRAC = 0.04
R_MAX_FRAC = 0.35
CENTER_WIN_FRAC = 0.20
SEED_WIN_FRAC   = 0.18
GRID_N = 5

# ---------------- Fitting helpers ----------------
def _kasa_fit(points):
    x = points[:,0].astype(np.float64); y = points[:,1].astype(np.float64)
    A = np.column_stack([x, y, np.ones_like(x)])
    b = -(x*x + y*y)
    a, bcoef, c = np.linalg.lstsq(A, b, rcond=None)[0]
    xc = -a/2; yc = -bcoef/2
    r  = sqrt((a*a + bcoef*bcoef)/4 - c)
    return xc, yc, r

def _robust_refit(points, iters=5, mad_tau=2.5):
    xc, yc, r = _kasa_fit(points)
    for _ in range(iters):
        rr = np.sqrt((points[:,0]-xc)**2 + (points[:,1]-yc)**2)
        resid = np.abs(rr - r)
        med  = np.median(resid)
        mad  = np.median(np.abs(resid - med)) + 1e-9
        keep = resid <= mad_tau * 1.4826 * mad
        if keep.sum() < 12: break
        points = points[keep]
        xc, yc, r = _kasa_fit(points)
    return xc, yc, r, points

def _enhance(img):
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    return cv2.GaussianBlur(clahe.apply(img), (5,5), 0)

# ---------------- Flood fill candidates ----------------
def _floodfill_candidates(roi, seeds, lo=DEFAULT_LO, hi=DEFAULT_HI):
    im = _enhance(roi)
    h, w = im.shape
    cand = []

    r_min = R_MIN_FRAC * min(h, w)
    r_max = R_MAX_FRAC * min(h, w)
    cx0, cy0 = w//2, h//2
    center_norm = CENTER_WIN_FRAC * min(h, w)

    for sx, sy in seeds:
        mask = np.zeros((h+2, w+2), np.uint8)
        filled = im.copy()
        flags = cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
        cv2.floodFill(filled, mask, (int(sx), int(sy)), 255, lo, hi, flags)
        m = (mask[1:-1, 1:-1] > 0).astype(np.uint8)*255
        area = int(m.sum() // 255)
        if area < 30:
            continue

        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not cnts:
            continue
        pts = max(cnts, key=cv2.contourArea).reshape(-1,2).astype(np.float64)

        xc, yc, r = _kasa_fit(pts)
        rr = np.sqrt((pts[:,0]-xc)**2 + (pts[:,1]-yc)**2)
        circ_std = max(0.0, 1.0 - rr.std()/(rr.mean()+1e-9))

        center_pen = min(1.0, np.hypot(xc - cx0, yc - cy0) / (center_norm + 1e-9))
        radius_pen = 0.0 if (r_min <= r <= r_max) else 1.0

        inside_r  = max(1, int(0.8*r))
        outside_r = min(int(1.25*r), int(0.45*min(h, w)))
        inside = np.zeros_like(im, np.uint8)
        outside = np.zeros_like(im, np.uint8)
        cv2.circle(inside,  (int(xc), int(yc)), inside_r, 255, -1)
        cv2.circle(outside, (int(xc), int(yc)), outside_r, 255,  5)
        ins_mean = float(im[inside > 0].mean()) if (inside > 0).any() else 0
        out_mean = float(im[outside > 0].mean()) if (outside > 0).any() else ins_mean
        contrast = max(0.0, min(1.0, (ins_mean - out_mean) / (abs(ins_mean) + 1e-6) + 0.5))

        score = (0.40*circ_std + 0.30*contrast + 0.30*(1.0 - center_pen)) - 0.40*radius_pen
        cand.append((score, (xc, yc, r), pts, m, (sx, sy)))

    if not cand: return None
    cand.sort(key=lambda t: t[0], reverse=True)
    return cand[0]   # (score, (xc,yc,r), pts, mask, seed)

# ---------------- Circularity metrics ----------------
def _circularity_metrics(inliers, center, percentiles=(5,95)):
    xc, yc = center
    rads = np.sqrt((inliers[:,0]-xc)**2 + (inliers[:,1]-yc)**2)
    p_lo, p_hi = percentiles
    r_in  = float(np.percentile(rads, p_lo))
    r_out = float(np.percentile(rads, p_hi))
    C_io  = max(0.0, min(1.0, r_in/(r_out+1e-9)))
    radial_nonuniformity = (r_out - r_in) / (r_out + 1e-9)
    return C_io, r_in, r_out, radial_nonuniformity

# ---------------- Eyepiece → ROI ----------------
def detect_field_robust(gray):
    h, w = gray.shape
    img = cv2.GaussianBlur(gray, (9,9), 0)
    minR = int(0.22*min(h,w)); maxR = int(0.65*min(h,w))
    circles = cv2.HoughCircles(img, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min(h,w)//2,
                               param1=120, param2=50, minRadius=minR, maxRadius=maxR)
    if circles is not None:
        x,y,r = sorted(np.round(circles[0]).astype(int), key=lambda p:p[2], reverse=True)[0]
        return (int(x),int(y)), int(r)
    _, bin_ = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    cnts,_ = cv2.findContours(bin_, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return (w//2, h//2), min(h,w)//2
    (x,y), r = cv2.minEnclosingCircle(max(cnts, key=cv2.contourArea))
    return (int(x),int(y)), int(r*0.98)

def crop_central_roi(gray, center, field_r, roi_scale=0.62):
    cx, cy = center
    roi_r = int(field_r*roi_scale)
    x1, y1 = max(0, cx-roi_r), max(0, cy-roi_r)
    x2, y2 = min(gray.shape[1], cx+roi_r), min(gray.shape[0], cy+roi_r)
    return gray[y1:y2, x1:x2]

# ---------------- Public analysis API ----------------
def analyze_nozzle_from_roi(
    roi_gray,
    um_per_px=UM_PER_PX,
    lo=DEFAULT_LO, hi=DEFAULT_HI,
    seed_win_frac=SEED_WIN_FRAC, grid_n=GRID_N,
    p_lo=5, p_hi=95
):
    """Analyze a pre-cropped grayscale ROI."""
    H, W = roi_gray.shape
    cx0, cy0 = W//2, H//2
    win = int(seed_win_frac * min(H, W))
    xs = np.linspace(cx0 - win, cx0 + win, grid_n)
    ys = np.linspace(cy0 - win, cy0 + win, grid_n)
    seeds = [(float(x), float(y)) for x in xs for y in ys]

    best = _floodfill_candidates(roi_gray, seeds, lo=lo, hi=hi)
    if best is None:
        raise RuntimeError("Nozzle not detected.")
    score, (xc, yc, r0), pts, mask, seed = best

    xc, yc, r, inliers = _robust_refit(pts, iters=5, mad_tau=2.5)

    diameter_px = 2.0 * r
    diameter_um = diameter_px * um_per_px
    C_io, r_in, r_out, rn = _circularity_metrics(inliers, (xc, yc), percentiles=(p_lo, p_hi))

    # Build overlay
    overlay = cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR)
    for x,y in inliers[::max(1, len(inliers)//600)]:
        cv2.circle(overlay, (int(x), int(y)), 1, (0,128,255), -1)
    cv2.circle(overlay, (int(round(xc)), int(round(yc))), int(round(r)), (0,255,0), 2)
    cv2.circle(overlay, (int(round(xc)), int(round(yc))), int(round(r_in)),  (255,0,0), 1)
    cv2.circle(overlay, (int(round(xc)), int(round(yc))), int(round(r_out)), (255,0,0), 1)

    text = f"d={diameter_um:.2f} µm  C_io={C_io:.3f}"
    cv2.putText(overlay, text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50,50,50), 3, cv2.LINE_AA)
    cv2.putText(overlay, text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1, cv2.LINE_AA)

    results = {
        "diameter_px": float(diameter_px),
        "diameter_um": float(diameter_um),
        "center_px": (float(xc), float(yc)),
        "radius_px": float(r),
        "circularity_io": float(C_io),
        "r_in_px": float(r_in),
        "r_out_px": float(r_out),
        "radial_nonuniformity": float(rn),
        "seed_used": (float(seed[0]), float(seed[1])),
        "score": float(score),
    }
    return overlay, results

def analyze_nozzle_from_frame(
    bgr_frame,
    um_per_px=UM_PER_PX,
    lo=DEFAULT_LO, hi=DEFAULT_HI,
    seed_win_frac=SEED_WIN_FRAC, grid_n=GRID_N,
    p_lo=5, p_hi=95
):
    """Convenience: auto-crop ROI from a BGR frame, then analyze."""
    gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
    center, field_r = detect_field_robust(gray)
    roi = crop_central_roi(gray, center, field_r, roi_scale=0.62)
    return analyze_nozzle_from_roi(roi, um_per_px, lo, hi, seed_win_frac, grid_n, p_lo, p_hi), roi
