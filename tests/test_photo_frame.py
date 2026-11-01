import pytest

from coshoot.detect import Detector
from coshoot.frame import check_frame
from coshoot.photo import check_photo


class FakeDetector(Detector):
    def __init__(self, boxes, blur=100.0):
        self.boxes, self._blur = boxes, blur

    def faces(self, path):
        return list(self.boxes)

    def blur(self, path):
        return self._blur


def big_png(tmp_path, png_factory, name="me.png", w=800, h=1000):
    path = tmp_path / name
    path.write_bytes(png_factory(w, h))
    return path


def codes(report):
    return [f.code for f in report.findings]


def test_missing_file_blocks(tmp_path):
    report = check_photo(tmp_path / "none.png", detector=None)
    assert report.to_dict()["level"] == "block" and codes(report) == ["missing_file"]


def test_unsupported_format_blocks(tmp_path):
    path = tmp_path / "a.gif"
    path.write_bytes(b"GIF89a....")
    assert codes(check_photo(path, detector=None)) == ["unsupported_format"]


def test_without_detector_degrades_to_info(tmp_path, png_factory):
    report = check_photo(big_png(tmp_path, png_factory), detector=None)
    assert report.faces is None
    assert "detector_unavailable" in codes(report) and report.to_dict()["level"] == "info"


def test_low_resolution_warns(tmp_path, png_factory):
    path = tmp_path / "s.png"
    path.write_bytes(png_factory(300, 300))
    assert "low_resolution" in codes(check_photo(path, detector=None))


def test_no_face_requires_confirmation(tmp_path, png_factory):
    report = check_photo(big_png(tmp_path, png_factory), detector=FakeDetector([]))
    assert "no_face_detected" in codes(report) and report.to_dict()["level"] == "confirm"


def test_multiple_faces_require_confirmation(tmp_path, png_factory):
    report = check_photo(big_png(tmp_path, png_factory),
                         detector=FakeDetector([(0, 0, 200, 200), (300, 0, 200, 200)]))
    assert report.faces == 2 and "multiple_faces" in codes(report)


def test_small_face_warns(tmp_path, png_factory):
    report = check_photo(big_png(tmp_path, png_factory), detector=FakeDetector([(0, 0, 60, 60)]))
    assert "face_too_small" in codes(report) and report.to_dict()["level"] == "warn"


def test_good_photo_has_only_info(tmp_path, png_factory):
    report = check_photo(big_png(tmp_path, png_factory), detector=FakeDetector([(200, 200, 300, 300)]))
    assert report.to_dict()["level"] == "info" and sorted(codes(report)) == ["angle_guide", "beauty_filter_unknown"]


def test_blurry_warns(tmp_path, png_factory):
    report = check_photo(big_png(tmp_path, png_factory),
                         detector=FakeDetector([(200, 200, 300, 300)], blur=10.0))
    assert "blurry" in codes(report)


def test_frame_without_detector(tmp_path, png_factory):
    out = check_frame(big_png(tmp_path, png_factory), "knee_up", detector=None)
    assert out["faces"] is None and out["findings"][0]["code"] == "detector_unavailable"


def test_frame_one_face_is_expected(tmp_path, png_factory):
    out = check_frame(big_png(tmp_path, png_factory), "knee_up", detector=FakeDetector([(100, 100, 150, 150)]))
    assert out["findings"] == [] and out["faces"] == 1


def test_frame_no_face_warns(tmp_path, png_factory):
    out = check_frame(big_png(tmp_path, png_factory), "knee_up", detector=FakeDetector([]))
    assert [f["code"] for f in out["findings"]] == ["faces_not_found"]


def test_frame_extra_face_warns(tmp_path, png_factory):
    out = check_frame(big_png(tmp_path, png_factory), "waist_up",
                      detector=FakeDetector([(0, 0, 100, 100), (400, 0, 200, 200)]))
    assert [f["code"] for f in out["findings"]] == ["extra_faces"]


def test_frame_drift_when_face_tiny(tmp_path, png_factory):
    out = check_frame(big_png(tmp_path, png_factory), "knee_up", detector=FakeDetector([(0, 0, 50, 50)]))
    assert [f["code"] for f in out["findings"]] == ["framing_drift"]


def test_opencv_without_haar_degrades_to_none(monkeypatch):
    import sys
    import types
    from coshoot.detect import default_detector
    monkeypatch.setitem(sys.modules, "cv2", types.ModuleType("cv2"))
    assert default_detector() is None


def test_opencv_detector_runs_on_blank_image(tmp_path, png_factory):
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "CascadeClassifier"):
        pytest.skip("OpenCV 5 has no Haar cascades; the degrade path is covered separately")
    from coshoot.detect import OpenCVDetector
    path = big_png(tmp_path, png_factory, w=200, h=200)
    detector = OpenCVDetector()
    assert detector.faces(path) == [] and isinstance(detector.blur(path), float)


class RaisingDetector(Detector):
    def faces(self, path):
        raise ValueError("cannot read image")

    def blur(self, path):
        raise ValueError("cannot read image")


def test_photo_detector_failure_degrades(tmp_path, png_factory):
    report = check_photo(big_png(tmp_path, png_factory), detector=RaisingDetector())
    assert report.faces is None and "detector_failed" in codes(report)
    assert report.to_dict()["level"] == "info"


def test_photo_blur_failure_degrades(tmp_path, png_factory):
    class BlurBroken(FakeDetector):
        def blur(self, path):
            raise ValueError("boom")
    report = check_photo(big_png(tmp_path, png_factory), detector=BlurBroken([(200, 200, 300, 300)]))
    assert "detector_failed" in codes(report)


def test_frame_detector_failure_degrades(tmp_path, png_factory):
    out = check_frame(big_png(tmp_path, png_factory), "knee_up", detector=RaisingDetector())
    assert out["faces"] is None and [f["code"] for f in out["findings"]] == ["detector_failed"]


def test_default_detector_survives_broken_cv2(monkeypatch):
    import sys
    from coshoot.detect import default_detector

    class Broken:
        def __getattr__(self, name):
            raise AttributeError(name)
    monkeypatch.setitem(sys.modules, "cv2", Broken())
    assert default_detector() is None


def test_photo_check_always_gives_angle_guide(tmp_path, png_factory):
    p = tmp_path / "me.png"
    p.write_bytes(png_factory(600, 600))
    report = check_photo(p, detector=None).to_dict()
    assert any(f["code"] == "angle_guide" for f in report["findings"])


def test_frame_small_texture_faces_are_ignored(tmp_path, png_factory):
    out = check_frame(big_png(tmp_path, png_factory), "waist_up",
                      detector=FakeDetector([(0, 0, 200, 200), (400, 0, 60, 60), (500, 300, 40, 40)]))
    assert out["findings"] == [] and out["faces"] == 3
