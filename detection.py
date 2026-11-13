"""
Module phat hien hanh vi - THIET KE DE "CAM" MODEL AI THAT VAO SAU NAY.

Hien tai chi co MotionDetector: mot bo PLACEHOLDER don gian dua tren
background subtraction (OpenCV MOG2) de phat hien CHUYEN DONG MANH/DOT NGOT.
Day KHONG PHAI la AI phan tich hanh vi bao luc that su - chi dung de kiem
tra toan bo luong he thong (quay clip, luu anh, ghi log, xem lai) truoc khi
co model AI that.

=> DE CAM MODEL AI THAT VAO:
   1. Tao 1 class ke thua BaseDetector (vi du class ViolenceModelDetector).
   2. Trong __init__: load model da train (TensorFlow/PyTorch/ONNX...).
   3. Cai dat process_frame(frame) -> DetectionResult, trong do frame la
      1 anh numpy (BGR, dung dinh dang OpenCV).
   4. Mo camera_manager.py, tim dong "self.detector = MotionDetector(...)"
      va thay bang "self.detector = ViolenceModelDetector(...)".
"""


class DetectionResult:
    def __init__(self, triggered, confidence, label, description):
        self.triggered = triggered      # True/False: co canh bao hay khong
        self.confidence = confidence    # 0.0 - 1.0
        self.label = label              # nhan ngan, vi du "motion_spike"
        self.description = description  # mo ta chi tiet, hien thi cho nguoi dung


class BaseDetector:
    """Giao dien chuan ma moi bo phat hien (placeholder hoac AI that) phai theo."""

    def process_frame(self, frame):
        """frame: anh numpy BGR (1 khung hinh tu camera). Tra ve DetectionResult."""
        raise NotImplementedError

    def reset(self):
        pass


class MotionDetector(BaseDetector):
    """
    PLACEHOLDER - khong phai AI. Phat hien chuyen dong manh bang MOG2.

    sensitivity: ty le (%) dien tich khung hinh thay doi de tinh la "chuyen
                 dong manh" (0.01 = 1%). Giam gia tri de nhay hon.
    trigger_frames: so khung LIEN TIEP vuot nguong truoc khi bao la co su kien
                    (giup loc bot nhieu/rung hinh nhat thoi).
    """

    def __init__(self, sensitivity=0.03, trigger_frames=4, warmup_frames=30):
        import cv2
        self._cv2 = cv2
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=32, detectShadows=False
        )
        self.sensitivity = sensitivity
        self.trigger_frames = trigger_frames
        self.warmup_frames = warmup_frames
        self._consecutive = 0
        self._seen = 0

    def reset(self):
        self._consecutive = 0

    def process_frame(self, frame):
        import numpy as np
        cv2 = self._cv2

        self._seen += 1
        fg = self.bg.apply(frame)
        fg = cv2.medianBlur(fg, 5)
        _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
        motion_ratio = float(np.count_nonzero(fg)) / fg.size

        if self._seen < self.warmup_frames:
            return DetectionResult(False, 0.0, "warmup", "")

        if motion_ratio > self.sensitivity:
            self._consecutive += 1
        else:
            self._consecutive = max(0, self._consecutive - 1)

        confidence = min(1.0, motion_ratio / (self.sensitivity * 4))

        if self._consecutive >= self.trigger_frames:
            self._consecutive = 0
            desc = (
                f"Phát hiện chuyển động mạnh/đột ngột trong khung hình "
                f"(vùng chuyển động ~{motion_ratio * 100:.1f}% diện tích khung hình). "
                f"Đây là cảnh báo từ bộ phát hiện chuyển động đơn giản (placeholder), "
                f"CHƯA PHẢI AI phân tích hành vi bạo lực thật sự."
            )
            return DetectionResult(True, confidence, "motion_spike", desc)

        return DetectionResult(False, confidence, "normal", "")
