from trafficcam.analysis.traffic_detector import TrafficDetector
from trafficcam.analysis.scene_classifier import SceneClassifier


def test_analysis_scaffolds_return_simple_results():
    detector = TrafficDetector()
    classifier = SceneClassifier()
    assert detector.analyze("sample.jpg")["label"] == "unknown"
    assert classifier.classify("sample.jpg")["scene"] == "unknown"
