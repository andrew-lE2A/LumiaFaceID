package com.lumia.irisprobe;

import java.nio.ByteBuffer;

/** Copies a cropped, strided image plane into a tightly packed byte array. */
final class YuvPlaneCopier {
    private YuvPlaneCopier() { }

    static final class Crop {
        final int left;
        final int top;
        final int width;
        final int height;

        private Crop(int left, int top, int width, int height) {
            this.left = left;
            this.top = top;
            this.width = width;
            this.height = height;
        }
    }

    /** Maps an even-origin full-resolution crop into a 4:2:0 chroma plane. */
    static Crop chromaCrop(int left, int top, int right, int bottom) {
        if (left < 0 || top < 0 || right <= left || bottom <= top
                || (left & 1) != 0 || (top & 1) != 0) {
            throw new IllegalArgumentException("Invalid full-resolution crop");
        }
        int chromaLeft = left / 2;
        int chromaTop = top / 2;
        int width = (right - left + 1) / 2;
        int height = (bottom - top + 1) / 2;
        return new Crop(chromaLeft, chromaTop,
                width, height);
    }

    static byte[] copy(ByteBuffer source, int rowStride, int pixelStride,
                       int planeWidth, int planeHeight, int cropLeft, int cropTop,
                       int width, int height) {
        if (source == null || rowStride <= 0 || pixelStride <= 0 || cropLeft < 0 || cropTop < 0
                || planeWidth <= 0 || planeHeight <= 0 || width <= 0 || height <= 0
                || (long) cropLeft + width > planeWidth
                || (long) cropTop + height > planeHeight) {
            throw new IllegalArgumentException("Invalid source plane geometry");
        }
        long length = (long) width * height;
        long rowSpan = (long) (width - 1) * pixelStride + 1;
        long base = source.position();
        long lastOffset = base + (long) (cropTop + (long) height - 1) * rowStride
                + (long) (cropLeft + (long) width - 1) * pixelStride;
        if (rowSpan > rowStride || length > Integer.MAX_VALUE || lastOffset >= source.limit()) {
            throw new IllegalArgumentException("Plane crop exceeds buffer bounds");
        }

        ByteBuffer buffer = source.duplicate();
        byte[] packed = new byte[(int) length];
        int index = 0;
        for (int row = 0; row < height; row++) {
            int rowStart = (int) (base + (cropTop + (long) row) * rowStride
                    + (long) cropLeft * pixelStride);
            for (int column = 0; column < width; column++) {
                packed[index++] = buffer.get(rowStart + column * pixelStride);
            }
        }
        return packed;
    }
}
