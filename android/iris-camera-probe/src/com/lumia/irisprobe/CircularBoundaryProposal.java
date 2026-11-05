package com.lumia.irisprobe;

/** Coarse circular pupil/limbus edge proposal for one eye crop; not a segmenter. */
final class CircularBoundaryProposal {
    private static final int ANGULAR_SAMPLES = 64;
    private static final int BOUNDARY_BAND = 2;
    private static final int MAX_IRIS_TO_PUPIL_RADIUS_RATIO = 8;
    private static final double[] UNIT_X = new double[ANGULAR_SAMPLES];
    private static final double[] UNIT_Y = new double[ANGULAR_SAMPLES];

    static {
        for (int i = 0; i < ANGULAR_SAMPLES; i++) {
            double angle = 2.0 * Math.PI * i / ANGULAR_SAMPLES;
            UNIT_X[i] = Math.cos(angle);
            UNIT_Y[i] = Math.sin(angle);
        }
    }

    private CircularBoundaryProposal() { }

    static Proposal find(byte[] luma, int imageWidth, int imageHeight,
                         int left, int top, int right, int bottom) {
        return find(luma, imageWidth, imageHeight, left, top, right, bottom, 48, 64);
    }

    static Proposal findCoarse(byte[] luma, int imageWidth, int imageHeight,
                               int left, int top, int right, int bottom) {
        return find(luma, imageWidth, imageHeight, left, top, right, bottom, 32, 40);
    }

    private static Proposal find(byte[] luma, int imageWidth, int imageHeight,
                                 int left, int top, int right, int bottom,
                                 int centerDivisor, int radiusDivisor) {
        if (luma == null || imageWidth <= 0 || imageHeight <= 0
                || luma.length < imageWidth * (long) imageHeight
                || left < 0 || top < 0 || right > imageWidth || bottom > imageHeight
                || right - left < 24 || bottom - top < 24) {
            return Proposal.invalid();
        }

        int minDimension = Math.min(right - left, bottom - top);
        int minRadius = 4;
        int maxPupilRadius = minDimension / 4;
        int centerStep = Math.max(1, minDimension / centerDivisor);
        int radiusStep = Math.max(1, minDimension / radiusDivisor);
        int bestX = -1, bestY = -1, bestRadius = -1;
        double bestPupilContrast = 0;

        for (int cy = top + maxPupilRadius + BOUNDARY_BAND;
             cy < bottom - maxPupilRadius - BOUNDARY_BAND; cy += centerStep) {
            for (int cx = left + maxPupilRadius + BOUNDARY_BAND;
                 cx < right - maxPupilRadius - BOUNDARY_BAND; cx += centerStep) {
                for (int radius = minRadius; radius <= maxPupilRadius; radius += radiusStep) {
                    double inside = circleMean(luma, imageWidth, cx, cy, radius - BOUNDARY_BAND);
                    double outside = circleMean(luma, imageWidth, cx, cy, radius + BOUNDARY_BAND);
                    double contrast = Math.abs(outside - inside) / 255.0;
                    if (contrast > bestPupilContrast) {
                        bestPupilContrast = contrast;
                        bestX = cx;
                        bestY = cy;
                        bestRadius = radius;
                    }
                }
            }
        }
        if (bestRadius < 0) return Proposal.invalid();

        int minIrisRadius = bestRadius + Math.max(6, bestRadius / 2);
        int maxIrisRadius = Math.min(minDimension / 2 - BOUNDARY_BAND,
                Math.min(Math.min(bestX - left, right - 1 - bestX),
                        Math.min(bestY - top, bottom - 1 - bestY))
                        - BOUNDARY_BAND);
        int bestIrisRadius = -1;
        double bestLimbusContrast = 0;
        for (int radius = minIrisRadius; radius <= maxIrisRadius; radius += radiusStep) {
            double inside = circleMean(luma, imageWidth, bestX, bestY, radius - BOUNDARY_BAND);
            double outside = circleMean(luma, imageWidth, bestX, bestY, radius + BOUNDARY_BAND);
            double contrast = Math.abs(outside - inside) / 255.0;
            if (contrast > bestLimbusContrast) {
                bestLimbusContrast = contrast;
                bestIrisRadius = radius;
            }
        }
        if (bestIrisRadius <= bestRadius
                || bestIrisRadius > bestRadius * MAX_IRIS_TO_PUPIL_RADIUS_RATIO) {
            return Proposal.invalid();
        }
        return new Proposal(true, bestX, bestY, bestRadius, bestIrisRadius,
                bestPupilContrast, bestLimbusContrast);
    }

    private static double circleMean(byte[] luma, int width, int cx, int cy, int radius) {
        if (radius <= 0) return luma[cy * width + cx] & 0xff;
        double sum = 0;
        for (int i = 0; i < ANGULAR_SAMPLES; i++) {
            int x = (int) Math.round(cx + radius * UNIT_X[i]);
            int y = (int) Math.round(cy + radius * UNIT_Y[i]);
            sum += luma[y * width + x] & 0xff;
        }
        return sum / ANGULAR_SAMPLES;
    }

    static final class Proposal {
        final boolean valid;
        final int pupilCenterX;
        final int pupilCenterY;
        final int pupilRadius;
        final int irisRadius;
        final double pupilBoundaryStrength;
        final double limbusBoundaryStrength;

        private Proposal(boolean valid, int x, int y, int pupilRadius, int irisRadius,
                         double pupilStrength, double limbusStrength) {
            this.valid = valid;
            pupilCenterX = x;
            pupilCenterY = y;
            this.pupilRadius = pupilRadius;
            this.irisRadius = irisRadius;
            pupilBoundaryStrength = pupilStrength;
            limbusBoundaryStrength = limbusStrength;
        }

        static Proposal invalid() {
            return new Proposal(false, -1, -1, 0, 0, 0, 0);
        }
    }
}
