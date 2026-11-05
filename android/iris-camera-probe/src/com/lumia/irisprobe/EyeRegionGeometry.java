package com.lumia.irisprobe;

/** Converts coarse eye-pair detections from a rotated detector bitmap to sensor-frame ROIs. */
final class EyeRegionGeometry {
    private EyeRegionGeometry() { }

    static Pair fromFaceDetection(float midX, float midY, float eyeSeparation,
                                  int sourceWidth, int sourceHeight,
                                  int detectorWidth, int detectorHeight, int rotationDegrees) {
        if (sourceWidth <= 0 || sourceHeight <= 0 || detectorWidth <= 0 || detectorHeight <= 0
                || !Float.isFinite(midX) || !Float.isFinite(midY)
                || !Float.isFinite(eyeSeparation) || eyeSeparation <= 0) {
            throw new IllegalArgumentException("Invalid face detection geometry");
        }
        int rotation = ((rotationDegrees % 360) + 360) % 360;
        if (rotation % 90 != 0) throw new IllegalArgumentException("Rotation must be a right angle");

        float halfSeparation = eyeSeparation / 2.0f;
        float cropHalfWidth = eyeSeparation * 0.35f;
        float cropHalfHeight = eyeSeparation * 0.28f;
        Candidate first = candidate(midX - halfSeparation, midY, cropHalfWidth, cropHalfHeight,
                sourceWidth, sourceHeight, detectorWidth, detectorHeight, rotation);
        Candidate second = candidate(midX + halfSeparation, midY, cropHalfWidth, cropHalfHeight,
                sourceWidth, sourceHeight, detectorWidth, detectorHeight, rotation);
        return new Pair(first, second);
    }

    private static Candidate candidate(float detectorX, float detectorY, float halfWidth, float halfHeight,
                                       int sourceWidth, int sourceHeight, int detectorWidth,
                                       int detectorHeight, int rotation) {
        Point center = detectorToSensor(detectorX, detectorY, sourceWidth, sourceHeight,
                detectorWidth, detectorHeight, rotation);
        Point[] corners = {
                detectorToSensor(detectorX - halfWidth, detectorY - halfHeight, sourceWidth,
                        sourceHeight, detectorWidth, detectorHeight, rotation),
                detectorToSensor(detectorX + halfWidth, detectorY - halfHeight, sourceWidth,
                        sourceHeight, detectorWidth, detectorHeight, rotation),
                detectorToSensor(detectorX - halfWidth, detectorY + halfHeight, sourceWidth,
                        sourceHeight, detectorWidth, detectorHeight, rotation),
                detectorToSensor(detectorX + halfWidth, detectorY + halfHeight, sourceWidth,
                        sourceHeight, detectorWidth, detectorHeight, rotation)
        };
        float left = center.x, right = center.x, top = center.y, bottom = center.y;
        for (Point p : corners) {
            left = Math.min(left, p.x); right = Math.max(right, p.x);
            top = Math.min(top, p.y); bottom = Math.max(bottom, p.y);
        }
        return new Candidate(center.x, center.y,
                clamp((int) Math.floor(left), 0, sourceWidth),
                clamp((int) Math.floor(top), 0, sourceHeight),
                clamp((int) Math.ceil(right), 0, sourceWidth),
                clamp((int) Math.ceil(bottom), 0, sourceHeight));
    }

    static Point detectorToSensor(float x, float y, int sourceWidth, int sourceHeight,
                                  int detectorWidth, int detectorHeight, int rotationDegrees) {
        int rotation = ((rotationDegrees % 360) + 360) % 360;
        float detectorX;
        float detectorY;
        switch (rotation) {
            case 90:
                detectorX = y;
                detectorY = detectorHeight - 1 - x;
                break;
            case 180:
                detectorX = detectorWidth - 1 - x;
                detectorY = detectorHeight - 1 - y;
                break;
            case 270:
                detectorX = detectorWidth - 1 - y;
                detectorY = x;
                break;
            default:
                detectorX = x;
                detectorY = y;
                break;
        }
        return new Point(detectorX * sourceWidth / detectorWidth,
                detectorY * sourceHeight / detectorHeight);
    }

    private static int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }

    static final class Point {
        final float x;
        final float y;
        Point(float x, float y) { this.x = x; this.y = y; }
    }

    static final class Candidate {
        final float centerX;
        final float centerY;
        final int cropLeft;
        final int cropTop;
        final int cropRight;
        final int cropBottom;
        Candidate(float x, float y, int left, int top, int right, int bottom) {
            centerX = x; centerY = y;
            cropLeft = left; cropTop = top; cropRight = right; cropBottom = bottom;
        }
    }

    static final class Pair {
        final Candidate detectorLeftEye;
        final Candidate detectorRightEye;
        Pair(Candidate left, Candidate right) {
            detectorLeftEye = left; detectorRightEye = right;
        }
    }
}
