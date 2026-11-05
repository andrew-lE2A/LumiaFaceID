package com.lumia.irisprobe;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Experimental one-dimensional log-Gabor phase coder for a supplied iris annulus.
 * This is not a complete iris-recognition system: geometry and occlusion masks
 * are supplied/approximated, and no biometric threshold is defined.
 */
final class LogGaborIrisCodePrototype {
    static final int RADIAL_ROWS = 24;
    static final int ANGULAR_SAMPLES = 256;
    private static final double CENTER_FREQUENCY = 1.0 / 18.0;
    private static final double BANDWIDTH = 0.55;
    private static final double MIN_RESPONSE = 0.75;
    private static final double MIN_OVERLAP_FRACTION = 0.50;
    private static final int ENROLLMENT_MAX_ANGULAR_SHIFT = 16;
    private static final int MASK_GUARD_SAMPLES = 8;
    private static final int CLIP_LOW = 12;
    private static final int CLIP_HIGH = 243;

    private LogGaborIrisCodePrototype() { }

    static Template encode(byte[] luma, int width, int height, double centerX, double centerY,
                           double pupilRadius, double irisRadius) {
        if (luma == null || width < 2 || height < 2 || luma.length < width * (long) height
                || pupilRadius <= 0 || irisRadius <= pupilRadius
                || centerX - irisRadius < 0 || centerY - irisRadius < 0
                || centerX + irisRadius >= width || centerY + irisRadius >= height) {
            throw new IllegalArgumentException("Invalid image or annulus geometry");
        }

        int codeLength = RADIAL_ROWS * ANGULAR_SAMPLES * 2;
        boolean[] bits = new boolean[codeLength];
        boolean[] valid = new boolean[codeLength];
        double[] real = new double[ANGULAR_SAMPLES];
        double[] imag = new double[ANGULAR_SAMPLES];
        boolean[] sourceValid = new boolean[ANGULAR_SAMPLES];
        boolean templateCreated = false;
        try {
            for (int row = 0; row < RADIAL_ROWS; row++) {
                double fraction = (row + 0.5) / RADIAL_ROWS;
                double radius = pupilRadius + fraction * (irisRadius - pupilRadius);
                double mean = 0;
                int validCount = 0;
                for (int angle = 0; angle < ANGULAR_SAMPLES; angle++) {
                    double theta = 2.0 * Math.PI * angle / ANGULAR_SAMPLES;
                    double x = centerX + radius * Math.cos(theta);
                    double y = centerY + radius * Math.sin(theta);
                    int value = sampleBilinear(luma, width, height, x, y);
                    real[angle] = value;
                    imag[angle] = 0;
                    sourceValid[angle] = value > CLIP_LOW && value < CLIP_HIGH;
                    if (sourceValid[angle]) {
                        mean += value;
                        validCount++;
                    }
                }
                if (validCount < ANGULAR_SAMPLES / 2) continue;
                mean /= validCount;
                for (int angle = 0; angle < ANGULAR_SAMPLES; angle++)
                    real[angle] = sourceValid[angle] ? real[angle] - mean : 0;

                fft(real, imag, false);
                for (int k = 0; k < ANGULAR_SAMPLES; k++) {
                    double frequency = (double) k / ANGULAR_SAMPLES;
                    if (k == 0 || k > ANGULAR_SAMPLES / 2) {
                        real[k] = 0;
                        imag[k] = 0;
                        continue;
                    }
                    double logRatio = Math.log(frequency / CENTER_FREQUENCY);
                    double exponent = -(logRatio * logRatio)
                            / (2.0 * Math.log(BANDWIDTH) * Math.log(BANDWIDTH));
                    double response = Math.exp(exponent);
                    real[k] *= response;
                    imag[k] *= response;
                }
                fft(real, imag, true);

                int rowOffset = row * ANGULAR_SAMPLES * 2;
                for (int angle = 0; angle < ANGULAR_SAMPLES; angle++) {
                    int realBit = rowOffset + angle * 2;
                    int imagBit = realBit + 1;
                    bits[realBit] = real[angle] >= 0;
                    bits[imagBit] = imag[angle] >= 0;
                    boolean neighborhoodValid = true;
                    for (int delta = -MASK_GUARD_SAMPLES; delta <= MASK_GUARD_SAMPLES; delta++) {
                        if (!sourceValid[(angle + delta + ANGULAR_SAMPLES) % ANGULAR_SAMPLES]) {
                            neighborhoodValid = false;
                            break;
                        }
                    }
                    boolean responseValid = Math.hypot(real[angle], imag[angle]) >= MIN_RESPONSE;
                    valid[realBit] = neighborhoodValid && responseValid;
                    valid[imagBit] = neighborhoodValid && responseValid;
                }
            }
            Template result = new Template(bits, valid);
            templateCreated = true;
            return result;
        } finally {
            Arrays.fill(real, 0.0);
            Arrays.fill(imag, 0.0);
            Arrays.fill(sourceValid, false);
            if (!templateCreated) {
                Arrays.fill(bits, false);
                Arrays.fill(valid, false);
            }
        }
    }

    static Score compare(Template first, Template second, int maxAngularShift) {
        if (first == null || second == null || first.bits.length != second.bits.length
                || maxAngularShift < 0 || maxAngularShift >= ANGULAR_SAMPLES / 2) {
            throw new IllegalArgumentException("Incompatible iris codes or shift range");
        }
        int bestErrors = Integer.MAX_VALUE;
        int bestCompared = 0;
        int bestShift = 0;
        for (int shift = -maxAngularShift; shift <= maxAngularShift; shift++) {
            int errors = 0;
            int compared = 0;
            for (int row = 0; row < RADIAL_ROWS; row++) {
                int rowOffset = row * ANGULAR_SAMPLES * 2;
                for (int angle = 0; angle < ANGULAR_SAMPLES; angle++) {
                    int otherAngle = (angle + shift + ANGULAR_SAMPLES) % ANGULAR_SAMPLES;
                    for (int phaseBit = 0; phaseBit < 2; phaseBit++) {
                        int a = rowOffset + angle * 2 + phaseBit;
                        int b = rowOffset + otherAngle * 2 + phaseBit;
                        if (first.valid[a] && second.valid[b]) {
                            compared++;
                            if (first.bits[a] != second.bits[b]) errors++;
                        }
                    }
                }
            }
            if (compared >= first.bits.length * MIN_OVERLAP_FRACTION && (bestCompared == 0
                    || errors * (long) bestCompared < bestErrors * (long) compared
                    || (errors * (long) bestCompared == bestErrors * (long) compared
                    && compared > bestCompared))) {
                bestErrors = errors;
                bestCompared = compared;
                bestShift = shift;
            }
        }
        int totalBits = first.bits.length;
        return bestCompared == 0 ? new Score(Double.NaN, 0, bestShift)
                : new Score((double) bestErrors / bestCompared,
                        (double) bestCompared / totalBits, bestShift);
    }

    /**
     * Builds an in-memory consensus code from repeated diagnostic captures.
     * This is not persisted and is not suitable for system authentication.
     */
    static final class DiagnosticEnrollment {
        private final int requiredSamples;
        private final List<Template> samples = new ArrayList<>();
        private boolean cleared;

        DiagnosticEnrollment(int requiredSamples) {
            if (requiredSamples < 3) {
                throw new IllegalArgumentException("Diagnostic enrollment needs at least three samples");
            }
            this.requiredSamples = requiredSamples;
        }

        boolean add(Template sample) {
            if (cleared || sample == null || sample.validFraction() == 0
                    || samples.size() >= requiredSamples) {
                return false;
            }
            if (!samples.isEmpty() && sample.bits.length != samples.get(0).bits.length) {
                return false;
            }
            if (!samples.isEmpty() && Double.isNaN(compare(samples.get(0), sample,
                    ENROLLMENT_MAX_ANGULAR_SHIFT).maskedHammingDistance)) {
                return false;
            }
            samples.add(sample);
            return true;
        }

        int sampleCount() { return samples.size(); }

        Template consensus() {
            if (cleared || samples.size() != requiredSamples) {
                throw new IllegalStateException("Need " + requiredSamples
                        + " usable frames; have " + samples.size());
            }
            int length = samples.get(0).bits.length;
            boolean[] bits = new boolean[length];
            boolean[] valid = new boolean[length];
            int[] shifts = new int[samples.size()];
            boolean consensusCreated = false;
            try {
                for (int sampleIndex = 1; sampleIndex < samples.size(); sampleIndex++) {
                    Score alignment = compare(samples.get(0), samples.get(sampleIndex),
                            ENROLLMENT_MAX_ANGULAR_SHIFT);
                    if (Double.isNaN(alignment.maskedHammingDistance)) {
                        throw new IllegalStateException("Enrollment sample could not be aligned");
                    }
                    shifts[sampleIndex] = alignment.angularShift;
                }
                int minimumSupport = (requiredSamples + 1) / 2;
                for (int index = 0; index < length; index++) {
                    int support = 0;
                    int ones = 0;
                    int rowOffset = (index / (ANGULAR_SAMPLES * 2)) * ANGULAR_SAMPLES * 2;
                    int angleOffset = (index % (ANGULAR_SAMPLES * 2)) / 2;
                    int phaseBit = index % 2;
                    for (int sampleIndex = 0; sampleIndex < samples.size(); sampleIndex++) {
                        Template sample = samples.get(sampleIndex);
                        if (sample.bits.length != length) {
                            throw new IllegalArgumentException("Enrollment samples have different code sizes");
                        }
                        int alignedAngle = (angleOffset + shifts[sampleIndex] + ANGULAR_SAMPLES)
                                % ANGULAR_SAMPLES;
                        int sampleIndexInCode = rowOffset + alignedAngle * 2 + phaseBit;
                        if (sample.valid[sampleIndexInCode]) {
                            support++;
                            if (sample.bits[sampleIndexInCode]) ones++;
                        }
                    }
                    int zeros = support - ones;
                    if (support >= minimumSupport && ones != zeros) {
                        valid[index] = true;
                        bits[index] = ones > zeros;
                    }
                }
                Template result = new Template(bits, valid);
                consensusCreated = true;
                return result;
            } finally {
                Arrays.fill(shifts, 0);
                if (!consensusCreated) {
                    Arrays.fill(bits, false);
                    Arrays.fill(valid, false);
                }
            }
        }

        void clear() {
            if (cleared) return;
            cleared = true;
            for (Template sample : samples) sample.clear();
            samples.clear();
        }
    }

    private static void fft(double[] real, double[] imag, boolean inverse) {
        int n = real.length;
        for (int i = 1, j = 0; i < n; i++) {
            int bit = n >>> 1;
            for (; (j & bit) != 0; bit >>>= 1) j ^= bit;
            j ^= bit;
            if (i < j) {
                double temp = real[i]; real[i] = real[j]; real[j] = temp;
                temp = imag[i]; imag[i] = imag[j]; imag[j] = temp;
            }
        }
        for (int length = 2; length <= n; length <<= 1) {
            double angle = 2.0 * Math.PI / length * (inverse ? 1 : -1);
            double stepReal = Math.cos(angle);
            double stepImag = Math.sin(angle);
            for (int start = 0; start < n; start += length) {
                double wReal = 1;
                double wImag = 0;
                int half = length >>> 1;
                for (int j = 0; j < half; j++) {
                    int even = start + j;
                    int odd = even + half;
                    double oddReal = real[odd] * wReal - imag[odd] * wImag;
                    double oddImag = real[odd] * wImag + imag[odd] * wReal;
                    real[odd] = real[even] - oddReal;
                    imag[odd] = imag[even] - oddImag;
                    real[even] += oddReal;
                    imag[even] += oddImag;
                    double nextReal = wReal * stepReal - wImag * stepImag;
                    wImag = wReal * stepImag + wImag * stepReal;
                    wReal = nextReal;
                }
            }
        }
        if (inverse) for (int i = 0; i < n; i++) {
            real[i] /= n;
            imag[i] /= n;
        }
    }

    private static int sampleBilinear(byte[] image, int width, int height, double x, double y) {
        int x0 = (int) Math.floor(x);
        int y0 = (int) Math.floor(y);
        int x1 = Math.min(width - 1, x0 + 1);
        int y1 = Math.min(height - 1, y0 + 1);
        double fx = x - x0;
        double fy = y - y0;
        int p00 = image[y0 * width + x0] & 0xff;
        int p10 = image[y0 * width + x1] & 0xff;
        int p01 = image[y1 * width + x0] & 0xff;
        int p11 = image[y1 * width + x1] & 0xff;
        double top = p00 + fx * (p10 - p00);
        double bottom = p01 + fx * (p11 - p01);
        return (int) Math.round(top + fy * (bottom - top));
    }

    static final class Template {
        private final boolean[] bits;
        private final boolean[] valid;
        private volatile double validFraction;
        private volatile boolean cleared;

        private Template(boolean[] bits, boolean[] valid) {
            this.bits = bits;
            this.valid = valid;
            int validCount = 0;
            for (boolean bitValid : valid) if (bitValid) validCount++;
            validFraction = (double) validCount / valid.length;
        }

        double validFraction() { return validFraction; }

        void clear() {
            if (cleared) return;
            cleared = true;
            Arrays.fill(bits, false);
            Arrays.fill(valid, false);
            validFraction = 0;
        }
    }

    static final class Score {
        final double maskedHammingDistance;
        final double overlapFraction;
        final int angularShift;

        private Score(double distance, double overlap, int shift) {
            maskedHammingDistance = distance;
            overlapFraction = overlap;
            angularShift = shift;
        }
    }
}
