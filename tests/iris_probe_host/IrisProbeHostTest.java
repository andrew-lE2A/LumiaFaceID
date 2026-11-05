package com.lumia.irisprobe;

import java.util.Locale;
import java.nio.ByteBuffer;

/** Synthetic host checks for geometry, circular proposals, and phase-code mechanics. */
public final class IrisProbeHostTest {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static byte[] eyePattern(boolean flat, boolean occluded, int pupilOffsetX) {
        int width = 240, height = 200;
        byte[] data = new byte[width * height];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            double dx = x - 120.0, dy = y - 100.0;
            double irisRadius = Math.sqrt(dx * dx + dy * dy);
            double px = x - (120.0 + pupilOffsetX), py = y - 100.0;
            double pupilRadius = Math.sqrt(px * px + py * py);
            double angle = Math.atan2(dy, dx);
            int value = flat ? 100 : pupilRadius < 22 ? 28 : irisRadius < 52
                    ? (int) (104 + 18 * Math.sin(angle * 13) + 12 * Math.cos(angle * 7 + irisRadius))
                    : 190;
            if (occluded && y < 80) value = 70;
            data[y * width + x] = (byte) value;
        }
        return data;
    }

    private static void testGeometry() {
        for (int rotation : new int[]{0, 90, 180, 270}) {
            float x = 600.0f * 320 / 1920;
            float y = 390.0f * 180 / 1080;
            float dx, dy;
            switch (rotation) {
                case 90: dx = 179 - y; dy = x; break;
                case 180: dx = 319 - x; dy = 179 - y; break;
                case 270: dx = y; dy = 319 - x; break;
                default: dx = x; dy = y;
            }
            EyeRegionGeometry.Point mapped = EyeRegionGeometry.detectorToSensor(
                    dx, dy, 1920, 1080, 320, 180, rotation);
            check(Math.abs(mapped.x - 600) <= 1 && Math.abs(mapped.y - 390) <= 1,
                    "coordinate round trip failed for rotation " + rotation);
            EyeRegionGeometry.Pair pair = EyeRegionGeometry.fromFaceDetection(
                    90, 160, 48, 1920, 1080, 320, 180, rotation);
            check(pair.detectorLeftEye.cropRight > pair.detectorLeftEye.cropLeft
                    && pair.detectorRightEye.cropBottom > pair.detectorRightEye.cropTop,
                    "empty eye box for rotation " + rotation);
        }
    }

    private static void testDiagnosticFrameQualityGate() {
        check(!DiagnosticFrameQuality.hasUsableLumaSignal(3),
                "near-black covered frame passed the provisional quality gate");
        check(!DiagnosticFrameQuality.hasUsableLumaSignal(25),
                "low-signal covered AE frame passed the provisional quality gate");
        check(DiagnosticFrameQuality.hasUsableLumaSignal(32),
                "quality gate rejected its configured boundary");
    }

    private static void testYuvPlaneCropCopy() {
        boolean oddOriginRejected = false;
        try {
            YuvPlaneCopier.chromaCrop(1, 1, 5, 5);
        } catch (IllegalArgumentException expected) {
            oddOriginRejected = true;
        }
        check(oddOriginRejected, "odd-origin chroma crop was packed without rephasing");
        YuvPlaneCopier.Crop evenCrop = YuvPlaneCopier.chromaCrop(2, 4, 7, 9);
        check(evenCrop.left == 1 && evenCrop.top == 2 && evenCrop.width == 3
                        && evenCrop.height == 3,
                "even-origin chroma crop did not map to half-resolution bounds");

        ByteBuffer source = ByteBuffer.allocate(40);
        source.position(3);
        int base = source.position();
        int rowStride = 10;
        int pixelStride = 2;
        for (int row = 0; row < 3; row++) for (int column = 0; column < 4; column++) {
            source.put(base + row * rowStride + column * pixelStride, (byte) (10 * row + column));
        }
        byte[] cropped = YuvPlaneCopier.copy(source, rowStride, pixelStride,
                4, 3, 1, 1, 2, 2);
        check(cropped.length == 4 && (cropped[0] & 0xff) == 11 && (cropped[1] & 0xff) == 12
                        && (cropped[2] & 0xff) == 21 && (cropped[3] & 0xff) == 22,
                "cropped plane copy ignored row/pixel stride or crop origin");
        check(source.position() == base, "plane copy changed the caller's buffer position");

        boolean boundsRejected = false;
        try {
            YuvPlaneCopier.copy(source, rowStride, pixelStride, 3, 3, 2, 1, 2, 1);
        } catch (IllegalArgumentException expected) {
            boundsRejected = true;
        }
        check(boundsRejected, "plane copy accepted a crop that extends into row padding");
        java.util.Arrays.fill(cropped, (byte) 0);
    }

    private static void testCircularProposal() {
        CircularBoundaryProposal.Proposal clear = CircularBoundaryProposal.find(
                eyePattern(false, false, 0), 240, 200, 20, 10, 220, 190);
        check(clear.valid, "clean synthetic annulus was rejected");
        check(Math.abs(clear.pupilCenterX - 120) <= 6 && Math.abs(clear.pupilCenterY - 100) <= 6,
                "clean pupil center outside tolerance");
        check(Math.abs(clear.pupilRadius - 22) <= 6 && Math.abs(clear.irisRadius - 52) <= 8,
                "clean synthetic radii outside tolerance");

        CircularBoundaryProposal.Proposal occluded = CircularBoundaryProposal.find(
                eyePattern(false, true, 2), 240, 200, 20, 10, 220, 190);
        check(occluded.valid, "partial lid-like occlusion was rejected");
        check(Math.abs(occluded.pupilCenterX - 122) <= 5 && Math.abs(occluded.pupilCenterY - 100) <= 5,
                "offset pupil center outside tolerance");
        check(Math.abs(occluded.pupilRadius - 22) <= 6 && Math.abs(occluded.irisRadius - 52) <= 10,
                "occluded synthetic radii outside tolerance");

        CircularBoundaryProposal.Proposal flat = CircularBoundaryProposal.find(
                eyePattern(true, false, 0), 240, 200, 20, 10, 220, 190);
        check(!flat.valid, "flat image produced a boundary proposal");

        byte[] wholeFrameEye = eyePattern(false, false, 0);
        CircularBoundaryProposal.Proposal fullFrame = CircularBoundaryProposal.find(
                wholeFrameEye, 240, 200, 0, 0, 240, 200);
        check(fullFrame.valid && Math.abs(fullFrame.pupilCenterX - 120) <= 6
                        && Math.abs(fullFrame.pupilCenterY - 100) <= 6,
                "whole-frame eye proposal failed");

        byte[] brightPupil = wholeFrameEye.clone();
        for (int i = 0; i < brightPupil.length; i++)
            brightPupil[i] = (byte) (255 - (brightPupil[i] & 0xff));
        CircularBoundaryProposal.Proposal bright = CircularBoundaryProposal.find(
                brightPupil, 240, 200, 0, 0, 240, 200);
        check(bright.valid && Math.abs(bright.pupilCenterX - 120) <= 6
                        && Math.abs(bright.pupilCenterY - 100) <= 6,
                "bright-pupil whole-frame proposal failed");
    }

    private static byte[] annularTexture(int rotation, boolean flat, double visibleFraction) {
        return annularTexture(rotation, flat, visibleFraction, 0);
    }

    private static byte[] annularTexture(int rotation, boolean flat, double visibleFraction,
                                         int syntheticIdentity) {
        int width = 256, height = 256;
        byte[] image = new byte[width * height];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            double dx = x - 128.0, dy = y - 128.0;
            double radius = Math.sqrt(dx * dx + dy * dy);
            double angle = Math.atan2(dy, dx) * 256.0 / (2.0 * Math.PI) - rotation;
            double radial = radius - 48.0;
            double value;
            if (flat) {
                value = 120;
            } else if (syntheticIdentity == 0) {
                value = 125 + 42 * Math.sin(angle * 2 * Math.PI / 18.0)
                        + 27 * Math.sin(angle * 2 * Math.PI / 31.0 + radial * 0.08)
                        + 16 * Math.cos(angle * 2 * Math.PI / 11.0 - radial * 0.11);
            } else {
                value = 125 + 42 * Math.sin(angle * 2 * Math.PI / 23.0 + 0.7)
                        + 27 * Math.sin(angle * 2 * Math.PI / 37.0 + radial * 0.13 + 1.1)
                        + 16 * Math.cos(angle * 2 * Math.PI / 9.0 - radial * 0.04 + 0.3);
            }
            double wrappedAngle = (angle - 40 + 512) % 256;
            boolean clipped = visibleFraction < 1.0 && wrappedAngle >= visibleFraction * 256
                    && radius > 50 && radius < 105;
            image[y * width + x] = (byte) (clipped ? 255 : (radius >= 48 && radius < 108
                    ? Math.max(15, Math.min(240, (int) Math.round(value))) : 120));
        }
        return image;
    }

    private static void testPhaseCodeMechanics() {
        LogGaborIrisCodePrototype.Template first = LogGaborIrisCodePrototype.encode(
                annularTexture(0, false, 1.0), 256, 256, 128, 128, 48, 108);
        LogGaborIrisCodePrototype.Template rotated = LogGaborIrisCodePrototype.encode(
                annularTexture(5, false, 1.0), 256, 256, 128, 128, 48, 108);
        LogGaborIrisCodePrototype.Score aligned = LogGaborIrisCodePrototype.compare(first, rotated, 8);
        LogGaborIrisCodePrototype.Score unaligned = LogGaborIrisCodePrototype.compare(first, rotated, 0);
        check(Math.abs(aligned.angularShift) == 5, "five-sample rotation not recovered");
        check(aligned.maskedHammingDistance < unaligned.maskedHammingDistance,
                "rotation alignment did not reduce synthetic distance");

        LogGaborIrisCodePrototype.Template impostor = LogGaborIrisCodePrototype.encode(
                annularTexture(0, false, 1.0, 1), 256, 256, 128, 128, 48, 108);
        LogGaborIrisCodePrototype.Score impostorScore =
                LogGaborIrisCodePrototype.compare(first, impostor, 8);
        check(!Double.isNaN(impostorScore.maskedHammingDistance)
                        && impostorScore.maskedHammingDistance > aligned.maskedHammingDistance + 0.15,
                "distinct synthetic texture was not separated from aligned genuine texture");

        LogGaborIrisCodePrototype.Template occluded = LogGaborIrisCodePrototype.encode(
                annularTexture(0, false, 0.82), 256, 256, 128, 128, 48, 108);
        LogGaborIrisCodePrototype.Score masked = LogGaborIrisCodePrototype.compare(first, occluded, 0);
        check(masked.maskedHammingDistance < 0.08 && masked.overlapFraction > 0.5
                        && masked.overlapFraction < 1.0,
                "clipped sector was not masked with usable overlap");
        System.out.printf(Locale.US,
                "Synthetic phase-code scores: aligned genuine=%.4f (overlap %.3f), "
                        + "unrotated genuine=%.4f, occluded genuine=%.4f (overlap %.3f), "
                        + "distinct synthetic impostor=%.4f (overlap %.3f)%n",
                aligned.maskedHammingDistance, aligned.overlapFraction,
                unaligned.maskedHammingDistance, masked.maskedHammingDistance,
                masked.overlapFraction, impostorScore.maskedHammingDistance,
                impostorScore.overlapFraction);

        LogGaborIrisCodePrototype.Template lowCoverage = LogGaborIrisCodePrototype.encode(
                annularTexture(0, false, 0.30), 256, 256, 128, 128, 48, 108);
        LogGaborIrisCodePrototype.Score insufficient = LogGaborIrisCodePrototype.compare(first, lowCoverage, 8);
        check(Double.isNaN(insufficient.maskedHammingDistance) && insufficient.overlapFraction == 0,
                "low-overlap code was not rejected");

        LogGaborIrisCodePrototype.Template blank = LogGaborIrisCodePrototype.encode(
                annularTexture(0, true, 1.0), 256, 256, 128, 128, 48, 108);
        LogGaborIrisCodePrototype.Score noData = LogGaborIrisCodePrototype.compare(first, blank, 8);
        check(Double.isNaN(noData.maskedHammingDistance) && noData.overlapFraction == 0,
                "flat template was not masked out");

        LogGaborIrisCodePrototype.DiagnosticEnrollment enrollment =
                new LogGaborIrisCodePrototype.DiagnosticEnrollment(3);
        check(enrollment.add(first), "first diagnostic sample was rejected");
        check(enrollment.add(rotated), "rotated diagnostic sample was rejected");
        check(!enrollment.add(blank), "blank diagnostic sample was accepted");
        boolean incompleteRejected = false;
        try {
            enrollment.consensus();
        } catch (IllegalStateException expected) {
            incompleteRejected = true;
        }
        check(incompleteRejected, "incomplete enrollment produced a template");

        LogGaborIrisCodePrototype.Template rotatedOtherWay = LogGaborIrisCodePrototype.encode(
                annularTexture(-3, false, 1.0), 256, 256, 128, 128, 48, 108);
        check(enrollment.add(rotatedOtherWay), "oppositely rotated sample was rejected");
        check(!enrollment.add(first), "enrollment accepted more than its configured sample count");
        LogGaborIrisCodePrototype.Template consensus = enrollment.consensus();
        LogGaborIrisCodePrototype.Score enrolled = LogGaborIrisCodePrototype.compare(first, consensus, 8);
        check(!Double.isNaN(enrolled.maskedHammingDistance) && enrolled.overlapFraction >= 0.5
                        && enrolled.maskedHammingDistance < 0.12,
                "rotation-aligned diagnostic consensus did not match its source samples");

        enrollment.clear();
        check(enrollment.sampleCount() == 0, "cleared enrollment retained sample references");
        check(first.validFraction() == 0 && rotated.validFraction() == 0
                        && rotatedOtherWay.validFraction() == 0,
                "cleared enrollment did not zero sample validity state");
        check(Double.isNaN(LogGaborIrisCodePrototype.compare(first, consensus, 8)
                        .maskedHammingDistance),
                "cleared enrollment codes remained comparable");
        boolean clearedEnrollmentRejected = false;
        try {
            enrollment.consensus();
        } catch (IllegalStateException expected) {
            clearedEnrollmentRejected = true;
        }
        check(clearedEnrollmentRejected, "cleared enrollment produced a consensus");
        consensus.clear();
        check(consensus.validFraction() == 0, "consensus validity state was not cleared");
    }

    public static void main(String[] args) {
        testYuvPlaneCropCopy();
        testGeometry();
        testDiagnosticFrameQualityGate();
        testCircularProposal();
        testPhaseCodeMechanics();
        System.out.println("Eye geometry, circular proposal, and phase-code synthetic checks passed");
    }
}
