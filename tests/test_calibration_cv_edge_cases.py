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


def test_characterize_droplet_returns_multiple_for_similar_dual_blobs():
    cam = _camera_stub()
    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    img = bg.copy()
    cv2.circle(img, (130, 210), 30, (255, 255, 255), -1)
    cv2.circle(img, (300, 220), 28, (255, 255, 255), -1)

    result, _ = cam.characterize_droplet(img, bg)
    assert result == "Multiple"


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
