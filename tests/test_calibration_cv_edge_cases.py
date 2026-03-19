import cv2
import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import DropletCameraModel


def _camera_stub():
    cam = DropletCameraModel.__new__(DropletCameraModel)
    cam._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cam._last_droplet_center_px = None
    return cam


def test_identify_droplet_contour_handles_weak_contrast():
    cam = _camera_stub()
    bg = np.full((420, 420, 3), 120, dtype=np.uint8)
    img = bg.copy()
    cv2.circle(img, (210, 220), 30, (150, 150, 150), -1)

    contour, _ = cam.identify_droplet_contour(img, bg)
    assert contour is not None


def test_identify_droplet_contour_is_deterministic_with_dual_candidates():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.circle(img, (130, 130), 28, (255, 255, 255), -1)
    cv2.circle(img, (300, 310), 28, (255, 255, 255), -1)

    c1, _ = cam.identify_droplet_contour(img, bg)
    c2, _ = cam.identify_droplet_contour(img, bg)
    x1, y1, w1, h1 = cv2.boundingRect(c1)
    x2, y2, w2, h2 = cv2.boundingRect(c2)
    c1_mid = (x1 + w1 // 2, y1 + h1 // 2)
    c2_mid = (x2 + w2 // 2, y2 + h2 // 2)

    assert abs(c1_mid[0] - c2_mid[0]) <= 2
    assert abs(c1_mid[1] - c2_mid[1]) <= 2
    assert (y1 + h1 // 2) > 250


def test_identify_droplet_contour_accepts_edge_touching_blob():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.circle(img, (15, 260), 45, (255, 255, 255), -1)

    contour, _ = cam.identify_droplet_contour(img, bg)
    assert contour is not None


def test_identify_droplet_contour_rejects_low_signal_border_blob():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.rectangle(img, (0, 0), (210, 210), (6, 6, 6), -1)

    contour, _, details = cam.identify_droplet_contour(img, bg, return_details=True)
    assert contour is None
    assert details.get("status") == "none"
    assert details.get("reason") in {"low_signal", "border_blob", "oversize_blob", "background_artifact"}


def test_identify_droplet_contour_roi_fallback_to_full_frame():
    cam = _camera_stub()
    cam._last_droplet_center_px = (70, 70)
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    # Large stale ROI blob near top-left should be rejected by quality gates.
    cv2.rectangle(img, (0, 0), (180, 180), (40, 40, 40), -1)
    # Actual droplet elsewhere should be recovered by full-frame fallback.
    cv2.circle(img, (320, 300), 28, (255, 255, 255), -1)

    contour, _, details = cam.identify_droplet_contour(
        img,
        bg,
        return_details=True,
        roi_half_size_px=120,
    )
    assert contour is not None
    x, y, w, h = cv2.boundingRect(contour)
    cx, cy = (x + w // 2, y + h // 2)
    assert cx > 250 and cy > 240
    assert details.get("roi_fallback_to_full") is True


def test_characterize_droplet_returns_multiple_for_similar_dual_blobs():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.circle(img, (130, 210), 30, (255, 255, 255), -1)
    cv2.circle(img, (300, 220), 28, (255, 255, 255), -1)

    result, _ = cam.characterize_droplet(img, bg)
    assert result == "Multiple"


def test_characterize_droplet_normalizes_ellipse_roundness_when_fit_axes_are_swapped(monkeypatch):
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.ellipse(img, (210, 220), (50, 16), 0, 0, 360, (255, 255, 255), -1)

    monkeypatch.setattr(cv2, "fitEllipse", lambda _cnt: ((210.0, 220.0), (24.0, 72.0), 0.0))

    result, _annotated, details = cam.characterize_droplet(img, bg, return_details=True)

    assert isinstance(result, dict)
    assert abs(float(result["ellipse_roundness"]) - (24.0 / 72.0)) < 1e-6
    assert abs(float(result["circularity_ellipse"]) - float(result["ellipse_roundness"])) < 1e-9
    assert abs(float(details["ellipse_roundness"]) - float(result["ellipse_roundness"])) < 1e-9


def test_identify_nozzle_prefers_lowest_candidate_in_noisy_background():
    rng = np.random.default_rng(42)
    cam = _camera_stub()

    bg = rng.integers(95, 106, size=(420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.rectangle(img, (80, 50), (170, 120), (160, 160, 160), -1)
    cv2.rectangle(img, (220, 270), (330, 360), (190, 190, 190), -1)

    center1, focus1, _ = cam.identify_nozzle(bg, img)
    center2, focus2, _ = cam.identify_nozzle(bg, img)

    assert center1 is not None and center2 is not None
    assert center1 == center2
    assert center1[1] > 250
    assert focus1 is not None and focus2 is not None
