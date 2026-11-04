package com.lumia.irisprobe;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.graphics.Matrix;
import android.graphics.RectF;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import android.util.Size;
import android.view.Gravity;
import android.view.Surface;
import android.view.TextureView;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Minimal Camera2 diagnostic. It finds the 1920x1088 iris metadata and opens only that ID. */
public final class IrisProbeActivity extends Activity {
    private static final String TAG = "LumiaIrisProbe";
    private static final int IRIS_SENSOR_WIDTH = 1920;
    private static final int IRIS_SENSOR_HEIGHT = 1088;
    private static final int REQUEST_CAMERA = 100;
    private static final int TORCH_PORT = 18761;

    private final AtomicInteger completedFrames = new AtomicInteger();
    private TextView status;
    private AspectTextureView preview;
    private AspectRatioFrame previewContainer;
    private CameraDevice camera;
    private CameraCaptureSession session;
    private ImageReader frameReader;
    private HandlerThread cameraThread;
    private Handler cameraHandler;
    private Surface previewSurface;
    private Size previewSize;
    private Size frameSize;
    private int sensorOrientation = 90;
    private int lensFacing = CameraCharacteristics.LENS_FACING_FRONT;
    private String irisCameraId;
    private boolean surfaceReady;
    private int previewRotationOffset;
    private Button irButton;
    private boolean pulseUsed;
    private Button rotateButton;
    private Button captureButton;
    private volatile boolean saveNextFrame;
    private boolean frameSaved;

    private void logLine(String text) {
        Log.i(TAG, text);
        runOnUiThread(() -> {
            if (status != null) status.append(text + "\n");
        });
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);

        TextView title = new TextView(this);
        title.setText("Lumia iris diagnostic — no enrollment or unlock");
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER_VERTICAL);
        title.setPadding(12, 8, 12, 8);
        root.addView(title, new LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT));

        previewContainer = new AspectRatioFrame(this);
        previewContainer.setBackgroundColor(Color.BLACK);
        previewContainer.setAspectRatio(3, 4);
        preview = new AspectTextureView(this);
        preview.setSurfaceTextureListener(new TextureView.SurfaceTextureListener() {
            @Override public void onSurfaceTextureAvailable(SurfaceTexture texture, int width, int height) {
                surfaceReady = true;
                logLine("Preview texture ready: view=" + width + "x" + height);
                configureTransform(width, height);
            }
            @Override public void onSurfaceTextureSizeChanged(SurfaceTexture texture, int width, int height) {
                configureTransform(width, height);
            }
            @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture texture) {
                surfaceReady = false;
                closeCamera();
                return true;
            }
            @Override public void onSurfaceTextureUpdated(SurfaceTexture texture) { }
        });
        FrameLayout.LayoutParams previewLayout = new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER);
        previewContainer.addView(preview, previewLayout);
        root.addView(previewContainer, new LinearLayout.LayoutParams(-1, 0, 1.0f));

        LinearLayout buttons = new LinearLayout(this);
        Button start = new Button(this);
        start.setText("Open iris");
        start.setOnClickListener(v -> openIris());
        Button stop = new Button(this);
        stop.setText("Close");
        stop.setOnClickListener(v -> closeCamera());
        captureButton = new Button(this);
        captureButton.setText("Save one YUV frame");
        captureButton.setEnabled(false);
        captureButton.setOnClickListener(v -> captureOneFrame());
        buttons.addView(start, new LinearLayout.LayoutParams(0, -2, 1));
        buttons.addView(captureButton, new LinearLayout.LayoutParams(0, -2, 1));
        buttons.addView(stop, new LinearLayout.LayoutParams(0, -2, 1));
        root.addView(buttons);

        LinearLayout controls = new LinearLayout(this);
        rotateButton = new Button(this);
        rotateButton.setText("Rotate +90°");
        rotateButton.setTextColor(Color.BLACK);
        rotateButton.setOnClickListener(v -> {
            previewRotationOffset = (previewRotationOffset + 90) % 360;
            updatePreviewGeometry();
            logLine("Preview rotation adjustment=" + previewRotationOffset + "°.");
        });
        controls.addView(rotateButton, new LinearLayout.LayoutParams(0, -2, 1));
        irButton = new Button(this);
        irButton.setText("IR pulse (min, 1 s)");
        irButton.setEnabled(false);
        irButton.setOnClickListener(v -> pulseIrOnce());
        controls.addView(irButton, new LinearLayout.LayoutParams(0, -2, 1));
        root.addView(controls);

        ScrollView scroll = new ScrollView(this);
        status = new TextView(this);
        status.setTextColor(Color.GREEN);
        status.setTextSize(13);
        status.setPadding(12, 8, 12, 8);
        scroll.addView(status);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 0.45f));
        setContentView(root);

        cameraThread = new HandlerThread("iris-camera2");
        cameraThread.start();
        cameraHandler = new Handler(cameraThread.getLooper());
        logLine("Ready. Finds the iris by its 1920x1088 sensor metadata, then opens only that ID.");
        summarizeLatestPrivateFrame();
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQUEST_CAMERA);
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == REQUEST_CAMERA && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED)
            logLine("Camera permission granted. Tap Open iris.");
        else if (requestCode == REQUEST_CAMERA) logLine("Camera permission denied.");
    }

    private void openIris() {
        if (!surfaceReady || preview.getSurfaceTexture() == null) {
            logLine("Waiting for preview texture.");
            return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQUEST_CAMERA);
            logLine("Camera permission required.");
            return;
        }
        if (camera != null) {
            logLine("The iris camera is already open.");
            return;
        }
        completedFrames.set(0);
        try {
            CameraManager manager = (CameraManager) getSystemService(Context.CAMERA_SERVICE);
            irisCameraId = findIrisCameraId(manager);
            if (irisCameraId == null) {
                logLine("No 1920x1088 front-facing iris camera found; no camera was opened.");
                return;
            }
            CameraCharacteristics characteristics = manager.getCameraCharacteristics(irisCameraId);
            Integer facing = characteristics.get(CameraCharacteristics.LENS_FACING);
            Integer orientation = characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION);
            lensFacing = facing == null ? CameraCharacteristics.LENS_FACING_FRONT : facing;
            sensorOrientation = orientation == null ? 90 : orientation;
            StreamConfigurationMap map = characteristics.get(
                    CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            Size[] outputs = map.getOutputSizes(SurfaceTexture.class);
            if (outputs == null || outputs.length == 0) {
                logLine("No SurfaceTexture output sizes for iris camera ID " + irisCameraId + ".");
                return;
            }
            previewSize = choosePreviewSize(outputs);
            Size[] yuvOutputs = map.getOutputSizes(ImageFormat.YUV_420_888);
            if (yuvOutputs == null || yuvOutputs.length == 0) {
                logLine("No YUV_420_888 output sizes for iris camera ID " + irisCameraId + ".");
                return;
            }
            frameSize = chooseFrameSize(yuvOutputs);
            frameReader = ImageReader.newInstance(frameSize.getWidth(), frameSize.getHeight(),
                    ImageFormat.YUV_420_888, 2);
            frameReader.setOnImageAvailableListener(reader -> {
                Image image = null;
                try {
                    image = reader.acquireNextImage();
                    if (image != null && saveNextFrame) {
                        saveNextFrame = false;
                        saveYuvFrame(image);
                    }
                } catch (Exception e) {
                    saveNextFrame = false;
                    runOnUiThread(() -> {
                        logLine("YUV frame save failed: " + e);
                        if (captureButton != null && camera != null && !frameSaved)
                            captureButton.setEnabled(true);
                    });
                } finally {
                    if (image != null) image.close();
                }
            }, cameraHandler);
            int displayDegrees = displayRotationDegrees();
            int relativeRotation = lensFacing == CameraCharacteristics.LENS_FACING_FRONT
                    ? (sensorOrientation + displayDegrees) % 360
                    : (sensorOrientation - displayDegrees + 360) % 360;
            boolean swapped = (relativeRotation + previewRotationOffset) % 180 != 0;
            previewContainer.setAspectRatio(swapped ? previewSize.getHeight() : previewSize.getWidth(),
                                            swapped ? previewSize.getWidth() : previewSize.getHeight());
            SurfaceTexture texture = preview.getSurfaceTexture();
            texture.setDefaultBufferSize(previewSize.getWidth(), previewSize.getHeight());
            previewSurface = new Surface(texture);
            updatePreviewGeometry();
            logLine("Selected iris camera ID " + irisCameraId + "; facing=" + facing + " sensorOrientation=" + sensorOrientation
                    + " displayRotation=" + displayDegrees + " stream=" + previewSize
                    + " one-frame YUV=" + frameSize
                    + " displayed=" + (swapped ? previewSize.getHeight() + "x" + previewSize.getWidth()
                                                 : previewSize.getWidth() + "x" + previewSize.getHeight()));
            manager.openCamera(irisCameraId, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice device) {
                    camera = device;
                    logLine("OPENED iris camera ID " + irisCameraId);
                    createPreviewSession(device);
                }
                @Override public void onDisconnected(CameraDevice device) {
                    logLine("DISCONNECTED iris camera ID " + irisCameraId);
                    device.close();
                    if (camera == device) camera = null;
                }
                @Override public void onError(CameraDevice device, int error) {
                    logLine("CAMERA ERROR iris ID " + irisCameraId + " code=" + error);
                    device.close();
                    if (camera == device) camera = null;
                }
            }, cameraHandler);
        } catch (SecurityException e) {
            logLine("SECURITY ERROR: " + e);
        } catch (CameraAccessException e) {
            logLine("OPEN ERROR: reason=" + e.getReason() + " " + e);
        } catch (RuntimeException e) {
            logLine("OPEN RUNTIME ERROR: " + e);
        }
    }

    private String findIrisCameraId(CameraManager manager) throws CameraAccessException {
        String match = null;
        for (String id : manager.getCameraIdList()) {
            CameraCharacteristics c = manager.getCameraCharacteristics(id);
            Size pixels = c.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE);
            Integer facing = c.get(CameraCharacteristics.LENS_FACING);
            logLine("Metadata camera " + id + ": " + pixels + " facing=" + facing);
            if (pixels != null && pixels.getWidth() == IRIS_SENSOR_WIDTH
                    && pixels.getHeight() == IRIS_SENSOR_HEIGHT
                    && facing != null && facing == CameraCharacteristics.LENS_FACING_FRONT) {
                if (match != null) {
                    logLine("More than one camera matches iris dimensions; refusing to open any camera.");
                    return null;
                }
                match = id;
            }
        }
        return match;
    }

    private Size choosePreviewSize(Size[] sizes) {
        Size best = sizes[0];
        double targetRatio = 1920.0 / 1088.0;
        double bestRatioError = Double.MAX_VALUE;
        long bestArea = -1;
        logLine("SurfaceTexture outputs:");
        for (Size size : sizes) {
            double ratioError = Math.abs((double) size.getWidth() / size.getHeight() - targetRatio);
            long area = (long) size.getWidth() * size.getHeight();
            logLine("  " + size.getWidth() + "x" + size.getHeight());
            if (ratioError < bestRatioError || (Math.abs(ratioError - bestRatioError) < 0.0001 && area > bestArea)) {
                best = size;
                bestRatioError = ratioError;
                bestArea = area;
            }
        }
        return best;
    }

    private Size chooseFrameSize(Size[] sizes) {
        Size best = sizes[0];
        double targetRatio = 1920.0 / 1088.0;
        double bestRatioError = Double.MAX_VALUE;
        long bestArea = -1;
        logLine("YUV_420_888 outputs:");
        for (Size size : sizes) {
            double ratioError = Math.abs((double) size.getWidth() / size.getHeight() - targetRatio);
            long area = (long) size.getWidth() * size.getHeight();
            logLine("  " + size.getWidth() + "x" + size.getHeight());
            if (ratioError < bestRatioError || (Math.abs(ratioError - bestRatioError) < 0.0001 && area > bestArea)) {
                best = size;
                bestRatioError = ratioError;
                bestArea = area;
            }
        }
        return best;
    }

    private void captureOneFrame() {
        if (camera == null || session == null || frameReader == null || saveNextFrame) {
            logLine("One-frame capture is not ready or is already pending.");
            return;
        }
        try {
            CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            request.addTarget(frameReader.getSurface());
            saveNextFrame = true;
            captureButton.setEnabled(false);
            logLine("Requesting one " + frameSize + " YUV frame; it will be saved in app-private storage.");
            cameraHandler.postDelayed(() -> {
                if (saveNextFrame) {
                    saveNextFrame = false;
                    runOnUiThread(() -> {
                        logLine("One-frame capture timed out; no image was saved.");
                        if (captureButton != null && camera != null && !frameSaved)
                            captureButton.setEnabled(true);
                    });
                }
            }, 5000);
            session.capture(request.build(), new CameraCaptureSession.CaptureCallback() {
                @Override public void onCaptureFailed(CameraCaptureSession s, CaptureRequest r,
                                                       android.hardware.camera2.CaptureFailure failure) {
                    saveNextFrame = false;
                    runOnUiThread(() -> {
                        logLine("One-frame capture failed: reason=" + failure.getReason());
                        if (captureButton != null && camera != null) captureButton.setEnabled(true);
                    });
                }
            }, cameraHandler);
        } catch (CameraAccessException | RuntimeException e) {
            saveNextFrame = false;
            logLine("Could not request YUV frame: " + e);
            if (captureButton != null) captureButton.setEnabled(camera != null && !frameSaved);
        }
    }

    private void saveYuvFrame(Image image) throws Exception {
        int width = image.getWidth();
        int height = image.getHeight();
        File frameFile = new File(getFilesDir(), String.format(Locale.US,
                "iris-frame-%d-%dx%d-i420.yuv", System.currentTimeMillis(), width, height));
        File metadataFile = new File(frameFile.getAbsolutePath() + ".json");
        try (FileOutputStream out = new FileOutputStream(frameFile)) {
            Image.Plane[] planes = image.getPlanes();
            writePackedPlane(out, planes[0], width, height);
            writePackedPlane(out, planes[1], (width + 1) / 2, (height + 1) / 2);
            writePackedPlane(out, planes[2], (width + 1) / 2, (height + 1) / 2);
        }
        String metadata = String.format(Locale.US,
                "{\"format\":\"I420\",\"width\":%d,\"height\":%d,\"timestampNs\":%d,\"sensorOrientation\":%d,\"cameraId\":\"%s\"}%n",
                width, height, image.getTimestamp(), sensorOrientation, irisCameraId);
        try (FileOutputStream out = new FileOutputStream(metadataFile)) {
            out.write(metadata.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        runOnUiThread(() -> {
            logLine("Saved one I420 frame and metadata inside app-private storage: " + frameFile.getName());
            frameSaved = true;
            if (captureButton != null) captureButton.setEnabled(false);
        });
    }

    private static void writePackedPlane(FileOutputStream out, Image.Plane plane, int width, int height)
            throws Exception {
        ByteBuffer buffer = plane.getBuffer().duplicate();
        int rowStride = plane.getRowStride();
        int pixelStride = plane.getPixelStride();
        byte[] packed = new byte[width * height];
        int index = 0;
        int base = buffer.position();
        for (int row = 0; row < height; row++) {
            int rowStart = base + row * rowStride;
            for (int column = 0; column < width; column++) {
                packed[index++] = buffer.get(rowStart + column * pixelStride);
            }
        }
        out.write(packed);
    }

    private void summarizeLatestPrivateFrame() {
        File[] files = getFilesDir().listFiles((dir, name) -> name.endsWith("-i420.yuv"));
        if (files == null || files.length == 0) return;
        File latest = files[0];
        for (File file : files) if (file.lastModified() > latest.lastModified()) latest = file;
        final File frame = latest;
        Matcher matcher = Pattern.compile("iris-frame-[0-9]+-([0-9]+)x([0-9]+)-i420\\.yuv")
                .matcher(frame.getName());
        if (!matcher.matches()) {
            logLine("Saved YUV exists but its filename dimensions could not be read.");
            return;
        }
        int width = Integer.parseInt(matcher.group(1));
        int height = Integer.parseInt(matcher.group(2));
        long yCount = (long) width * height;
        long cCount = (long) ((width + 1) / 2) * ((height + 1) / 2);
        long expected = yCount + 2 * cCount;
        if (frame.length() != expected) {
            logLine("Saved YUV length mismatch: " + frame.length() + " bytes, expected " + expected + ".");
            return;
        }
        new Thread(() -> {
            PlaneStats[] stats = {new PlaneStats(), new PlaneStats(), new PlaneStats()};
            LumaQualityStats quality = new LumaQualityStats(width, height);
            byte[] bytes = new byte[32768];
            long offset = 0;
            try (FileInputStream in = new FileInputStream(frame)) {
                int count;
                while ((count = in.read(bytes)) != -1) {
                    for (int i = 0; i < count; i++, offset++) {
                        int plane = offset < yCount ? 0 : (offset < yCount + cCount ? 1 : 2);
                        int value = bytes[i] & 0xff;
                        stats[plane].add(value);
                        if (plane == 0) {
                            quality.add((int) (offset % width), (int) (offset / width), value);
                        }
                    }
                }
                logLine("On-device summary of private frame " + frame.getName() + " (no image exported): "
                        + "Y " + stats[0] + "; U " + stats[1] + "; V " + stats[2]
                        + "; spatial Y " + quality);
            } catch (Exception e) {
                logLine("Could not summarize saved private YUV: " + e);
            }
        }, "iris-yuv-summary").start();
    }

    private static final class PlaneStats {
        private long count;
        private long sum;
        private long sumSquares;
        private int min = 256;
        private int max = -1;
        void add(int value) {
            count++;
            sum += value;
            sumSquares += (long) value * value;
            min = Math.min(min, value);
            max = Math.max(max, value);
        }
        @Override public String toString() {
            double mean = count == 0 ? 0 : (double) sum / count;
            double variance = count == 0 ? 0 : (double) sumSquares / count - mean * mean;
            return String.format(Locale.US, "mean=%.2f sd=%.2f range=%d..%d", mean,
                    Math.sqrt(Math.max(0, variance)), min, max);
        }
    }

    /** Aggregate spatial metrics only; never retains, displays or exports frame pixels. */
    private static final class LumaQualityStats {
        private static final int TILE_COLUMNS = 8;
        private static final int TILE_ROWS = 6;
        private final int width;
        private final int height;
        private final byte[] previousRow;
        private final long[] histogram = new long[256];
        private final long[] tileSums = new long[TILE_COLUMNS * TILE_ROWS];
        private final long[] tileSumSquares = new long[TILE_COLUMNS * TILE_ROWS];
        private final long[] tileCounts = new long[TILE_COLUMNS * TILE_ROWS];
        private long horizontalGradient;
        private long verticalGradient;
        private long lowClipped;
        private long highClipped;
        private long count;

        LumaQualityStats(int width, int height) {
            this.width = width;
            this.height = height;
            previousRow = new byte[width];
        }

        void add(int x, int y, int value) {
            count++;
            histogram[value]++;
            if (value <= 16) lowClipped++;
            if (value >= 240) highClipped++;
            if (x > 0) horizontalGradient += Math.abs(value - (previousRow[x - 1] & 0xff));
            if (y > 0) verticalGradient += Math.abs(value - (previousRow[x] & 0xff));
            previousRow[x] = (byte) value;
            int tile = Math.min(TILE_ROWS - 1, y * TILE_ROWS / height) * TILE_COLUMNS
                    + Math.min(TILE_COLUMNS - 1, x * TILE_COLUMNS / width);
            tileSums[tile] += value;
            tileSumSquares[tile] += (long) value * value;
            tileCounts[tile]++;
        }

        private int percentile(double fraction) {
            long target = Math.max(1, (long) Math.ceil(count * fraction));
            long accumulated = 0;
            for (int value = 0; value < histogram.length; value++) {
                accumulated += histogram[value];
                if (accumulated >= target) return value;
            }
            return 255;
        }

        private double[] tileSpread() {
            double min = Double.POSITIVE_INFINITY;
            double max = 0;
            for (int i = 0; i < tileCounts.length; i++) {
                long n = tileCounts[i];
                if (n == 0) continue;
                double mean = (double) tileSums[i] / n;
                double variance = (double) tileSumSquares[i] / n - mean * mean;
                double deviation = Math.sqrt(Math.max(0, variance));
                min = Math.min(min, deviation);
                max = Math.max(max, deviation);
            }
            return new double[]{Double.isFinite(min) ? min : 0, max};
        }

        @Override public String toString() {
            double[] tileStdDev = tileSpread();
            return String.format(Locale.US,
                    "p05=%d p50=%d p95=%d meanAbsGradient(H/V)=%.2f/%.2f "
                            + "clipped(<=16/>=240)=%.2f%%/%.2f%% tileStdDev(min/max)=%.2f/%.2f (%dx%d grid)",
                    percentile(0.05), percentile(0.50), percentile(0.95),
                    (double) horizontalGradient / Math.max(1, height * (long) (width - 1)),
                    (double) verticalGradient / Math.max(1, (height - 1L) * width),
                    100.0 * lowClipped / Math.max(1, count),
                    100.0 * highClipped / Math.max(1, count),
                    tileStdDev[0], tileStdDev[1], TILE_COLUMNS, TILE_ROWS);
        }
    }

    private int displayRotationDegrees() {
        switch (getWindowManager().getDefaultDisplay().getRotation()) {
            case Surface.ROTATION_90: return 90;
            case Surface.ROTATION_180: return 180;
            case Surface.ROTATION_270: return 270;
            default: return 0;
        }
    }

    private void configureTransform(int viewWidth, int viewHeight) {
        if (preview == null || previewSize == null || viewWidth <= 0 || viewHeight <= 0) return;
        int displayDegrees = displayRotationDegrees();
        int sign = lensFacing == CameraCharacteristics.LENS_FACING_FRONT ? 1 : -1;
        int rotation = (sensorOrientation - displayDegrees * sign + previewRotationOffset + 360) % 360;
        float width = previewSize.getWidth();
        float height = previewSize.getHeight();
        boolean swap = rotation % 180 != 0;
        float rotatedWidth = swap ? height : width;
        float rotatedHeight = swap ? width : height;
        float scale = Math.min(viewWidth / rotatedWidth, viewHeight / rotatedHeight);
        float left = (viewWidth - rotatedWidth * scale) / 2.0f;
        float top = (viewHeight - rotatedHeight * scale) / 2.0f;
        float[] source = {0, 0, width, 0, width, height, 0, height};
        float[] destination;
        switch (rotation) {
            case 90:
                destination = new float[]{left + rotatedWidth * scale, top,
                        left + rotatedWidth * scale, top + rotatedHeight * scale,
                        left, top + rotatedHeight * scale, left, top};
                break;
            case 180:
                destination = new float[]{left + rotatedWidth * scale, top + rotatedHeight * scale,
                        left, top + rotatedHeight * scale, left, top,
                        left + rotatedWidth * scale, top};
                break;
            case 270:
                destination = new float[]{left, top + rotatedHeight * scale,
                        left, top, left + rotatedWidth * scale, top,
                        left + rotatedWidth * scale, top + rotatedHeight * scale};
                break;
            default:
                destination = new float[]{left, top, left + rotatedWidth * scale, top,
                        left + rotatedWidth * scale, top + rotatedHeight * scale,
                        left, top + rotatedHeight * scale};
                break;
        }
        Matrix transform = new Matrix();
        if (!transform.setPolyToPoly(source, 0, destination, 0, 4)) {
            logLine("Could not map camera buffer into preview; keeping prior transform.");
            return;
        }
        preview.setTransform(transform);
    }

    private void updatePreviewGeometry() {
        if (previewSize == null) return;
        int displayDegrees = displayRotationDegrees();
        int sign = lensFacing == CameraCharacteristics.LENS_FACING_FRONT ? 1 : -1;
        int rotation = (sensorOrientation - displayDegrees * sign + previewRotationOffset + 360) % 360;
        boolean swapped = rotation % 180 != 0;
        previewContainer.setAspectRatio(swapped ? previewSize.getHeight() : previewSize.getWidth(),
                                        swapped ? previewSize.getWidth() : previewSize.getHeight());
        configureTransform(preview.getWidth(), preview.getHeight());
        if (rotateButton != null)
            rotateButton.setText("Rotate " + rotation + "° (+90)");
    }

    private void pulseIrOnce() {
        if (camera == null || completedFrames.get() == 0) {
            logLine("IR pulse blocked: first iris frame callback has not arrived.");
            return;
        }
        if (pulseUsed) {
            logLine("IR pulse blocked: this app session allows one pulse only.");
            return;
        }
        pulseUsed = true;
        irButton.setEnabled(false);
        logLine("Requesting one minimum-current IR pulse (hardware code 1, maximum 1 second).");
        new Thread(() -> {
            String response;
            try (Socket socket = new Socket(InetAddress.getByName("127.0.0.1"), TORCH_PORT);
                 PrintWriter out = new PrintWriter(socket.getOutputStream(), true);
                 BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()))) {
                socket.setSoTimeout(2500);
                out.println("PULSE");
                response = in.readLine();
            } catch (Exception e) {
                response = "ERROR " + e.getClass().getSimpleName() + ": " + e.getMessage();
            }
            String result = response;
            runOnUiThread(() -> logLine("IR pulse result: " + result + "."));
        }, "iris-torch-pulse").start();
    }

    private void createPreviewSession(CameraDevice device) {
        try {
            CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            request.addTarget(previewSurface);
            java.util.List<Surface> outputs = new java.util.ArrayList<>();
            outputs.add(previewSurface);
            outputs.add(frameReader.getSurface());
            device.createCaptureSession(outputs, new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession configured) {
                    if (camera == null) {
                        configured.close();
                        return;
                    }
                    session = configured;
                    runOnUiThread(() -> {
                        if (captureButton != null) captureButton.setEnabled(!frameSaved);
                    });
                    try {
                        configured.setRepeatingRequest(request.build(), new CameraCaptureSession.CaptureCallback() {
                            @Override public void onCaptureCompleted(CameraCaptureSession s, CaptureRequest r,
                                                                    android.hardware.camera2.TotalCaptureResult result) {
                                int n = completedFrames.incrementAndGet();
                                if (n == 1 && irButton != null && !pulseUsed)
                                    runOnUiThread(() -> irButton.setEnabled(true));
                                if (n == 1 || n % 30 == 0) logLine("CAPTURE RESULT callback #" + n + " frame=" + result.getFrameNumber());
                            }
                            @Override public void onCaptureFailed(CameraCaptureSession s, CaptureRequest r,
                                                                 android.hardware.camera2.CaptureFailure failure) {
                                logLine("CAPTURE FAILED reason=" + failure.getReason() + " frame=" + failure.getFrameNumber());
                            }
                        }, cameraHandler);
                        logLine("Capture session configured; repeating preview request submitted.");
                    } catch (CameraAccessException | RuntimeException e) {
                        logLine("REPEATING REQUEST ERROR: " + e);
                    }
                }
                @Override public void onConfigureFailed(CameraCaptureSession failed) {
                    logLine("SESSION CONFIGURE FAILED for iris camera ID " + irisCameraId + ".");
                }
                @Override public void onClosed(CameraCaptureSession closed) {
                    if (session == closed) session = null;
                    logLine("Capture session closed.");
                }
            }, cameraHandler);
        } catch (CameraAccessException | RuntimeException e) {
            logLine("SESSION CREATE ERROR: " + e);
        }
    }

    private void closeCamera() {
        if (irButton != null) irButton.setEnabled(false);
        saveNextFrame = false;
        if (captureButton != null) captureButton.setEnabled(false);
        if (session != null) {
            try { session.stopRepeating(); } catch (CameraAccessException ignored) { }
            session.close();
            session = null;
        }
        if (camera != null) {
            camera.close();
            camera = null;
            logLine("Camera closed after " + completedFrames.get() + " capture-result callbacks.");
        }
        if (previewSurface != null) {
            previewSurface.release();
            previewSurface = null;
        }
        if (frameReader != null) {
            frameReader.close();
            frameReader = null;
        }
    }

    @Override protected void onPause() {
        closeCamera();
        super.onPause();
    }

    @Override protected void onDestroy() {
        closeCamera();
        if (cameraThread != null) cameraThread.quitSafely();
        super.onDestroy();
    }

    private static final class AspectTextureView extends TextureView {
        AspectTextureView(Context context) { super(context); }
    }

    private static final class AspectRatioFrame extends FrameLayout {
        private int ratioWidth;
        private int ratioHeight;
        AspectRatioFrame(Context context) { super(context); }
        void setAspectRatio(int width, int height) {
            if (width <= 0 || height <= 0) throw new IllegalArgumentException("aspect ratio must be positive");
            ratioWidth = width;
            ratioHeight = height;
            requestLayout();
        }
        @Override protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
            int width = MeasureSpec.getSize(widthMeasureSpec);
            int height = MeasureSpec.getSize(heightMeasureSpec);
            setMeasuredDimension(width, height);
            if (getChildCount() == 0) return;
            int childWidth = width;
            int childHeight = height;
            if (ratioWidth > 0 && ratioHeight > 0) {
                if (childWidth < childHeight * (double) ratioWidth / ratioHeight) {
                    childHeight = (int) (childWidth * (double) ratioHeight / ratioWidth);
                } else {
                    childWidth = (int) (childHeight * (double) ratioWidth / ratioHeight);
                }
            }
            getChildAt(0).measure(MeasureSpec.makeMeasureSpec(childWidth, MeasureSpec.EXACTLY),
                                  MeasureSpec.makeMeasureSpec(childHeight, MeasureSpec.EXACTLY));
        }
        @Override protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
            if (getChildCount() == 0) return;
            android.view.View child = getChildAt(0);
            int width = child.getMeasuredWidth();
            int height = child.getMeasuredHeight();
            int childLeft = (getWidth() - width) / 2;
            int childTop = (getHeight() - height) / 2;
            child.layout(childLeft, childTop, childLeft + width, childTop + height);
        }
    }
}
