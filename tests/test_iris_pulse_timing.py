"""Check that the timing analyzer recognizes the IR in-memory capture path."""
import unittest

from tools.analyze_iris_pulse_timing import correlate, parse_log


class IrisPulseTimingTests(unittest.TestCase):
    def test_ir_analysis_request_result_and_yuv_are_correlated(self):
        sensor_timestamp = 3000
        lines = [
            "IR-ANALYZE REQUEST submitElapsedRealtimeNs=2100 "
            "sensorTimestampSource=0 pulseSequenceActive=true",
            "ONE-FRAME IR_ANALYZE RESULT frame=42 exposureNs=30000000 "
            f"sensorTimestampNs={sensor_timestamp} sensorTimestampSource=0 "
            "callbackElapsedRealtimeNs=4100 pulseSequenceActive=true",
            f"ONE-FRAME YUV IMAGE timestampNs={sensor_timestamp} "
            "callbackElapsedRealtimeNs=4200 pulseSequenceActive=true",
            "IR capture helper result: OFF confirmed by helper "
            "pulseRequestElapsedRealtimeNs=1000 onAckElapsedRealtimeNs=2000 "
            "stopRequestElapsedRealtimeNs=5000 offAckElapsedRealtimeNs=6000.",
        ]
        frames, requests, images, pulses = parse_log(lines)
        summary = correlate(frames, requests, images, pulses)

        self.assertEqual(summary["still_request_count"], 1)
        self.assertEqual(summary["still_result_count"], 1)
        self.assertEqual(summary["yuv_image_count"], 1)
        self.assertEqual(summary["capture_result_yuv_match_count"], 1)
        result = summary["results"][0]
        self.assertTrue(result["request_submitted_after_on_ack"])
        self.assertTrue(result["matching_yuv_image_delivered_before_stop"])
        self.assertTrue(result["capture_transaction_bracketed_by_helper"])
        self.assertFalse(result["clock_comparable"])


if __name__ == "__main__":
    unittest.main()
