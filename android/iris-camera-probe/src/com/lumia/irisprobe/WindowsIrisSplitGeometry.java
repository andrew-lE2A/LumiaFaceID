package com.lumia.irisprobe;

/**
 * Diagnostic geometry copied from the recovered Windows iris engine's two-view split.
 * It models rectangles only; it does not rotate, normalize, or interpret pixel data.
 */
final class WindowsIrisSplitGeometry {
    static final int OVERLAP_PIXELS = 300;

    private WindowsIrisSplitGeometry() { }

    static Layout forFrame(int width, int height, int rotationDegrees) {
        if (width <= 0 || height <= 0) {
            throw new IllegalArgumentException("Frame dimensions must be positive");
        }
        int normalized = ((rotationDegrees % 360) + 360) % 360;
        int orientation = ((normalized + 45) / 90) & 3;
        boolean splitAlongX = (orientation & 1) == 0;
        int axisLength = splitAlongX ? width : height;
        if (axisLength < 2 * OVERLAP_PIXELS) {
            throw new IllegalArgumentException(
                    "Recovered split dimensions are unresolved below 600 pixels on the split axis");
        }

        int viewExtent = (axisLength + OVERLAP_PIXELS) / 2;
        int secondStart = (axisLength - OVERLAP_PIXELS) / 2;
        View first = splitAlongX
                ? new View(0, 0, viewExtent, height)
                : new View(0, 0, width, viewExtent);
        View second = splitAlongX
                ? new View(secondStart, 0, viewExtent, height)
                : new View(0, secondStart, width, viewExtent);
        if ((orientation & 2) != 0) {
            View swap = first;
            first = second;
            second = swap;
        }
        return new Layout(width, height, normalized, orientation, first, second);
    }

    static final class Layout {
        final int sourceWidth;
        final int sourceHeight;
        final int normalizedRotationDegrees;
        final int orientationIndex;
        final int overlap = OVERLAP_PIXELS;
        final View first;
        final View second;

        Layout(int sourceWidth, int sourceHeight, int normalizedRotationDegrees,
               int orientationIndex, View first, View second) {
            this.sourceWidth = sourceWidth;
            this.sourceHeight = sourceHeight;
            this.normalizedRotationDegrees = normalizedRotationDegrees;
            this.orientationIndex = orientationIndex;
            this.first = first;
            this.second = second;
        }
    }

    static final class View {
        final int x;
        final int y;
        final int width;
        final int height;

        View(int x, int y, int width, int height) {
            this.x = x;
            this.y = y;
            this.width = width;
            this.height = height;
        }
    }
}
