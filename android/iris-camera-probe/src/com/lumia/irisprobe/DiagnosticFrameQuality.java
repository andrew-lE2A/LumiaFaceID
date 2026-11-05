package com.lumia.irisprobe;

/** Provisional signal floor for experimental geometry and in-memory enrollment only. */
final class DiagnosticFrameQuality {
    // Both can-covered phone captures (p95 3 in manual mode, 25 in AE) must be rejected.
    // This is a diagnostic safeguard, not a calibrated iris-image quality threshold.
    static final int MIN_LUMA_P95 = 32;

    private DiagnosticFrameQuality() { }

    static boolean hasUsableLumaSignal(int p95) {
        return p95 >= MIN_LUMA_P95;
    }
}
