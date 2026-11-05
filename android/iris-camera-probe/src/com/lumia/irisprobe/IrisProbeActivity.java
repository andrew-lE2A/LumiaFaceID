package com.lumia.irisprobe;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.PointF;
import android.graphics.RectF;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.FaceDetector;
import android.media.ImageReader;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import android.util.Log;
import android.util.Size;
import android.view.Gravity;
import android.view.MotionEvent;
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
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Minimal Camera2 diagnostic. It finds the 1920x1088 iris metadata and opens only that ID. */
public final class IrisProbeActivity extends Activity {
    private static final String TAG = "LumiaIrisProbe";
    private static final int IRIS_SENSOR_WIDTH = 1920;
    private static final int IRIS_SENSOR_HEIGHT = 1088;
    private static final int REQUEST_CAMERA = 100;
    private static final int TORCH_PORT = 18761;
    private static final long WINDOWS_BASELINE_EXPOSURE_NS = 30_000_000L;
    private static final long WINDOWS_BASELINE_FRAME_DURATION_NS = 33_500_000L;
    private static final int WINDOWS_BASELINE_SENSITIVITY_ISO = 100;

    private final AtomicInteger completedFrames = new AtomicInteger();
    private TextView status;
    private AspectTextureView preview;
    private AspectRatioFrame previewContainer;
    private RoiOverlayView roiOverlay;
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
    private boolean manualSensorSupported;
    private int sensorTimestampSource = -1;
    private volatile boolean manualExposureMode;
    private int previewRotationOffset;
    private Button irButton;
    private boolean pulseUsed;
    private Button rotateButton;
    private Button captureButton;
    private Button analyzeButton;
    private Button selectRoiButton;
    private Button enrollButton;
    private Button compareButton;
    private Button exposureButton;
    private volatile boolean saveNextFrame;
    private volatile boolean analyzeNextFrame;
    private volatile boolean compareNextFrame;
    private volatile boolean frameOperationBusy;
    private volatile boolean pulseSequenceActive;
    private volatile boolean manualRoiSelected;
    private volatile boolean roiSelectionMode;
    private volatile float manualRoiXFraction;
    private volatile float manualRoiYFraction;
    private volatile LogGaborIrisCodePrototype.DiagnosticEnrollment diagnosticEnrollment;
    private volatile LogGaborIrisCodePrototype.Template diagnosticConsensus;
    private final Object pendingSaveLock = new Object();
    private Runnable pendingSaveCompletion;
    private boolean frameSaved;

    private void logLine(String text) {
        Log.i(TAG, text);
        runOnUiThread(() -> {
            if (status != null) status.append(text + "\n");
        });
    }

    /** Show biometric-derived diagnostics in this app only; never copy them to Logcat. */
    private void showPrivateDiagnostic(String text) {
        runOnUiThread(() -> {
            if (status != null && camera != null) status.append(text + "\n");
        });
    }

    /** Saved-frame aggregate diagnostics are allowed while the camera is closed. */
    private void showSavedFrameDiagnostic(String text) {
        runOnUiThread(() -> {
            if (status != null && !isFinishing() && !isDestroyed()) status.append(text + "\n");
        });
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);

        TextView title = new TextView(this);
        title.setText("Lumia iris diagnostic — no system unlock");
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
        roiOverlay = new RoiOverlayView(this);
        previewContainer.addView(roiOverlay, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        roiOverlay.setOnTouchListener((view, event) -> {
            if (!roiSelectionMode) return false;
            if (event.getAction() == MotionEvent.ACTION_UP) {
                selectManualRoi(event.getX(), event.getY());
                return true;
            }
            return true;
        });
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

        analyzeButton = new Button(this);
        analyzeButton.setText("Analyze one live frame (no save)");
        analyzeButton.setEnabled(false);
        analyzeButton.setOnClickListener(v -> analyzeOneLiveFrame());
        root.addView(analyzeButton, new LinearLayout.LayoutParams(-1, -2));

        selectRoiButton = new Button(this);
        selectRoiButton.setText("Select eye ROI (tap preview)");
        selectRoiButton.setEnabled(false);
        selectRoiButton.setOnClickListener(v -> {
            if (frameOperationBusy) {
                logLine("Manual ROI selection is unavailable while a frame operation is pending.");
                return;
            }
            roiSelectionMode = true;
            roiOverlay.setSelectionMode(true);
            selectRoiButton.setText("Tap the center of one iris");
            logLine("Manual ROI selection active. Tap the preview center of one eye; coordinates stay in RAM only.");
        });
        root.addView(selectRoiButton, new LinearLayout.LayoutParams(-1, -2));

        enrollButton = new Button(this);
        enrollButton.setText("Start 3-frame diagnostic enrollment (RAM only)");
        enrollButton.setOnClickListener(v -> startDiagnosticEnrollment());
        root.addView(enrollButton, new LinearLayout.LayoutParams(-1, -2));

        compareButton = new Button(this);
        compareButton.setText("Compare next frame (no threshold)");
        compareButton.setEnabled(false);
        compareButton.setOnClickListener(v -> compareOneLiveFrame());
        root.addView(compareButton, new LinearLayout.LayoutParams(-1, -2));

        exposureButton = new Button(this);
        exposureButton.setText("Use manual 30 ms / ISO 100 baseline");
        exposureButton.setEnabled(false);
        exposureButton.setOnClickListener(v -> toggleExposureMode());
        root.addView(exposureButton, new LinearLayout.LayoutParams(-1, -2));

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
        irButton.setText("IR + capture (min, 1 s)");
        irButton.setEnabled(false);
        irButton.setOnClickListener(v -> pulseAndCaptureOnce());
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
                    if (image != null) {
                        logLine("ONE-FRAME YUV IMAGE timestampNs=" + image.getTimestamp()
                                + " callbackElapsedRealtimeNs=" + SystemClock.elapsedRealtimeNanos()
                                + " pulseSequenceActive=" + pulseSequenceActive);
                    }
                    if (image != null && saveNextFrame) {
                        saveNextFrame = false;
                        saveYuvFrame(image);
                        frameOperationBusy = false;
                        finishPendingSave();
                    } else if (image != null && analyzeNextFrame) {
                        analyzeNextFrame = false;
                        boolean compare = compareNextFrame;
                        compareNextFrame = false;
                        analyzeImageInMemory(image, compare);
                    }
                } catch (Exception e) {
                    saveNextFrame = false;
                    analyzeNextFrame = false;
                    compareNextFrame = false;
                    frameOperationBusy = false;
                    finishPendingSave();
                    runOnUiThread(() -> {
                        logLine("YUV frame operation failed: " + e);
                        if (captureButton != null && camera != null && !frameSaved)
                            captureButton.setEnabled(true);
                        if (analyzeButton != null && camera != null)
                            analyzeButton.setEnabled(true);
                        if (compareButton != null && camera != null && diagnosticConsensus != null)
                            compareButton.setEnabled(true);
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
        manualSensorSupported = false;
        for (String id : manager.getCameraIdList()) {
            CameraCharacteristics c = manager.getCameraCharacteristics(id);
            Size pixels = c.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE);
            Integer facing = c.get(CameraCharacteristics.LENS_FACING);
            Integer timestampSource = c.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE);
            Object exposureRange = c.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE);
            Object sensitivityRange = c.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE);
            int[] capabilities = c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
            int[] aeModes = c.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES);
            boolean manualSensor = false;
            if (capabilities != null) {
                for (int capability : capabilities) {
                    if (capability == CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR)
                        manualSensor = true;
                }
            }
            logLine("Metadata camera " + id + ": " + pixels + " facing=" + facing
                    + " exposureRangeNs=" + exposureRange + " sensitivityRangeIso=" + sensitivityRange
                    + " timestampSource=" + timestampSource
                    + " manualSensor=" + manualSensor
                    + " aeModes=" + java.util.Arrays.toString(aeModes));
            if (pixels != null && pixels.getWidth() == IRIS_SENSOR_WIDTH
                    && pixels.getHeight() == IRIS_SENSOR_HEIGHT
                    && facing != null && facing == CameraCharacteristics.LENS_FACING_FRONT) {
                if (match != null) {
                    logLine("More than one camera matches iris dimensions; refusing to open any camera.");
                    return null;
                }
                match = id;
                manualSensorSupported = manualSensor;
                sensorTimestampSource = timestampSource == null ? -1 : timestampSource;
            }
        }
        return match;
    }

    private void toggleExposureMode() {
        if (camera == null || session == null || !manualSensorSupported) {
            logLine("Exposure control unavailable: iris preview is closed or manual-sensor capability is absent.");
            return;
        }
        boolean enableManual = !manualExposureMode;
        try {
            CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            request.addTarget(previewSurface);
            request.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);
            request.set(CaptureRequest.CONTROL_AE_MODE, enableManual
                    ? CaptureRequest.CONTROL_AE_MODE_OFF : CaptureRequest.CONTROL_AE_MODE_ON);
            if (enableManual) {
                request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, WINDOWS_BASELINE_EXPOSURE_NS);
                request.set(CaptureRequest.SENSOR_SENSITIVITY, WINDOWS_BASELINE_SENSITIVITY_ISO);
                request.set(CaptureRequest.SENSOR_FRAME_DURATION, WINDOWS_BASELINE_FRAME_DURATION_NS);
            }
            session.setRepeatingRequest(request.build(), previewCaptureCallback(), cameraHandler);
            manualExposureMode = enableManual;
            exposureButton.setText(enableManual
                    ? "Use AE auto (restore)"
                    : "Use manual 30 ms / ISO 100 baseline");
            logLine(enableManual
                    ? "Requested manual sensor baseline: exposure=30,000,000 ns (about 1000 source-derived lines), "
                            + "ISO=100, frame duration=33,500,000 ns; IR remains off."
                    : "Restored AE auto mode; IR remains off.");
        } catch (CameraAccessException | RuntimeException e) {
            logLine("Could not change Camera2 exposure mode: " + e);
        }
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
        captureOneFrame(null);
    }

    private void captureOneFrame(Runnable completion) {
        if (camera == null || session == null || frameReader == null || frameOperationBusy) {
            logLine("One-frame capture is not ready or is already pending.");
            if (completion != null) completion.run();
            return;
        }
        try {
            CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            applyCurrentExposure(request);
            request.addTarget(frameReader.getSurface());
            synchronized (pendingSaveLock) {
                pendingSaveCompletion = completion;
            }
            frameOperationBusy = true;
            saveNextFrame = true;
            captureButton.setEnabled(false);
            if (analyzeButton != null) analyzeButton.setEnabled(false);
            logLine("Requesting one " + frameSize + " YUV frame; it will be saved in app-private storage.");
            cameraHandler.postDelayed(() -> {
                if (saveNextFrame) {
                    saveNextFrame = false;
                    frameOperationBusy = false;
                    finishPendingSave();
                    runOnUiThread(() -> {
                        logLine("One-frame capture timed out; no image was saved.");
                        if (captureButton != null && camera != null && !frameSaved)
                            captureButton.setEnabled(true);
                        if (analyzeButton != null && camera != null) analyzeButton.setEnabled(true);
                    });
                }
            }, 5000);
            logLine("ONE-FRAME REQUEST submitElapsedRealtimeNs="
                    + SystemClock.elapsedRealtimeNanos()
                    + " sensorTimestampSource=" + sensorTimestampSource
                    + " pulseSequenceActive=" + pulseSequenceActive);
            session.capture(request.build(), new CameraCaptureSession.CaptureCallback() {
                @Override public void onCaptureCompleted(CameraCaptureSession s, CaptureRequest r,
                                                        android.hardware.camera2.TotalCaptureResult result) {
                    logOneFrameCaptureResult("SAVE", result);
                }
                @Override public void onCaptureFailed(CameraCaptureSession s, CaptureRequest r,
                                                       android.hardware.camera2.CaptureFailure failure) {
                    saveNextFrame = false;
                    frameOperationBusy = false;
                    finishPendingSave();
                    runOnUiThread(() -> {
                        logLine("One-frame capture failed: reason=" + failure.getReason());
                        if (captureButton != null && camera != null) captureButton.setEnabled(true);
                        if (analyzeButton != null && camera != null) analyzeButton.setEnabled(true);
                    });
                }
            }, cameraHandler);
        } catch (CameraAccessException | RuntimeException e) {
            saveNextFrame = false;
            frameOperationBusy = false;
            finishPendingSave();
            logLine("Could not request YUV frame: " + e);
            if (captureButton != null) captureButton.setEnabled(camera != null && !frameSaved);
            if (analyzeButton != null) analyzeButton.setEnabled(camera != null);
        }
    }

    private void finishPendingSave() {
        Runnable completion;
        synchronized (pendingSaveLock) {
            completion = pendingSaveCompletion;
            pendingSaveCompletion = null;
        }
        if (completion != null) completion.run();
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
            if (analyzeButton != null && camera != null) analyzeButton.setEnabled(true);
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

    private void startDiagnosticEnrollment() {
        if (frameOperationBusy || roiSelectionMode) {
            logLine("Cannot start diagnostic enrollment while a frame operation or ROI selection is pending.");
            return;
        }
        clearDiagnosticEnrollment();
        diagnosticEnrollment = new LogGaborIrisCodePrototype.DiagnosticEnrollment(3);
        if (compareButton != null) compareButton.setEnabled(false);
        logLine("Started transient diagnostic enrollment: collect three usable eye-ROI annulus codes. "
                + "Codes stay in memory and are discarded when the app exits; this is not Android enrollment.");
    }

    private void selectManualRoi(float viewX, float viewY) {
        if (frameOperationBusy) {
            roiSelectionMode = false;
            roiOverlay.setSelectionMode(false);
            logLine("Manual ROI selection cancelled because a frame operation is pending.");
            return;
        }
        if (preview == null || previewSize == null || frameSize == null) {
            logLine("Manual ROI selection failed: preview geometry is unavailable.");
            return;
        }
        Matrix transform = new Matrix();
        Matrix inverse = new Matrix();
        preview.getTransform(transform);
        float[] point = {viewX, viewY};
        if (!transform.invert(inverse)) {
            logLine("Manual ROI selection failed: preview transform is not invertible.");
            return;
        }
        inverse.mapPoints(point);
        if (point[0] < 0 || point[1] < 0
                || point[0] >= previewSize.getWidth() || point[1] >= previewSize.getHeight()) {
            logLine("Tap landed outside the camera image; tap inside the preview image.");
            return;
        }
        float[] roundTrip = {point[0], point[1]};
        transform.mapPoints(roundTrip);
        float transformErrorPx = (float) Math.hypot(roundTrip[0] - viewX, roundTrip[1] - viewY);
        manualRoiXFraction = point[0] / previewSize.getWidth();
        manualRoiYFraction = point[1] / previewSize.getHeight();
        manualRoiSelected = true;
        roiSelectionMode = false;
        roiOverlay.setSelectionMode(false);
        updateRoiOverlay();
        clearDiagnosticEnrollment();
        if (compareButton != null) compareButton.setEnabled(false);
        if (selectRoiButton != null) selectRoiButton.setText("Reselect eye ROI (tap preview)");
        logLine(String.format(Locale.US,
                "Manual eye ROI selected; touch/buffer/screen round-trip error=%.3f px; "
                        + "coordinates remain in RAM only. Previous diagnostic codes cleared.",
                transformErrorPx));
    }

    private void updateRoiOverlay() {
        if (roiOverlay == null) return;
        if (!manualRoiSelected || preview == null || previewSize == null || frameSize == null) {
            roiOverlay.setRoi(false, 0, 0, 0);
            return;
        }
        float centerX = manualRoiXFraction * previewSize.getWidth();
        float centerY = manualRoiYFraction * previewSize.getHeight();
        float halfSize = Math.min(previewSize.getWidth(), previewSize.getHeight()) * 0.25f;
        float[] points = {centerX, centerY, centerX + halfSize, centerY};
        Matrix transform = new Matrix();
        preview.getTransform(transform);
        transform.mapPoints(points);
        float radius = (float) Math.hypot(points[2] - points[0], points[3] - points[1]);
        roiOverlay.setRoi(true, points[0], points[1], radius);
    }

    private void clearDiagnosticEnrollment() {
        LogGaborIrisCodePrototype.DiagnosticEnrollment enrollment = diagnosticEnrollment;
        LogGaborIrisCodePrototype.Template consensus = diagnosticConsensus;
        diagnosticEnrollment = null;
        diagnosticConsensus = null;
        if (enrollment != null) enrollment.clear();
        if (consensus != null) consensus.clear();
    }

    private void clearDiagnosticEnrollmentAfterCameraWork() {
        if (cameraHandler != null && cameraHandler.post(this::clearDiagnosticEnrollment)) return;
        clearDiagnosticEnrollment();
    }

    private void analyzeOneLiveFrame() {
        requestLiveFrameAnalysis(false);
    }

    private void compareOneLiveFrame() {
        if (diagnosticConsensus == null) {
            logLine("Comparison unavailable: collect three usable samples first.");
            return;
        }
        requestLiveFrameAnalysis(true);
    }

    private void requestLiveFrameAnalysis(boolean compare) {
        if (roiSelectionMode) {
            logLine("Finish manual ROI selection before starting a frame analysis.");
            return;
        }
        if (camera == null || session == null || frameReader == null || frameOperationBusy) {
            logLine("Frame analysis requires the iris preview to be open and idle.");
            return;
        }
        frameOperationBusy = true;
        analyzeNextFrame = true;
        compareNextFrame = compare;
        analyzeButton.setEnabled(false);
        if (compareButton != null) compareButton.setEnabled(false);
        if (captureButton != null) captureButton.setEnabled(false);
        logLine(compare
                ? "Comparing one live frame against the transient diagnostic code; no image is saved and IR remains off."
                : "Analyzing the next iris YUV frame in memory; no image is saved and IR remains off.");
        try {
            CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            applyCurrentExposure(request);
            request.addTarget(frameReader.getSurface());
            logLine("ONE-FRAME REQUEST submitElapsedRealtimeNs="
                    + SystemClock.elapsedRealtimeNanos()
                    + " sensorTimestampSource=" + sensorTimestampSource
                    + " pulseSequenceActive=" + pulseSequenceActive);
            session.capture(request.build(), new CameraCaptureSession.CaptureCallback() {
                @Override public void onCaptureCompleted(CameraCaptureSession s, CaptureRequest r,
                                                        android.hardware.camera2.TotalCaptureResult result) {
                    logOneFrameCaptureResult(compare ? "COMPARE" : "ANALYZE", result);
                }
                @Override public void onCaptureFailed(CameraCaptureSession s, CaptureRequest r,
                                                     android.hardware.camera2.CaptureFailure failure) {
                    analyzeNextFrame = false;
                    compareNextFrame = false;
                    frameOperationBusy = false;
                    runOnUiThread(() -> {
                        logLine("One-frame eye-region capture failed: reason=" + failure.getReason());
                        if (analyzeButton != null && camera != null) analyzeButton.setEnabled(true);
                        if (compareButton != null && camera != null && diagnosticConsensus != null)
                            compareButton.setEnabled(true);
                        if (captureButton != null && camera != null && !frameSaved) captureButton.setEnabled(true);
                    });
                }
            }, cameraHandler);
        } catch (CameraAccessException | RuntimeException e) {
            analyzeNextFrame = false;
            compareNextFrame = false;
            frameOperationBusy = false;
            logLine("Could not request eye-region frame: " + e);
            analyzeButton.setEnabled(camera != null);
            if (compareButton != null)
                compareButton.setEnabled(camera != null && diagnosticConsensus != null);
            if (captureButton != null) captureButton.setEnabled(camera != null && !frameSaved);
            return;
        }
        cameraHandler.postDelayed(() -> {
            if (analyzeNextFrame) {
                analyzeNextFrame = false;
                compareNextFrame = false;
                frameOperationBusy = false;
                runOnUiThread(() -> {
                    logLine("One-frame eye-region analysis timed out.");
                    if (analyzeButton != null && camera != null) analyzeButton.setEnabled(true);
                    if (compareButton != null && camera != null && diagnosticConsensus != null)
                        compareButton.setEnabled(true);
                    if (captureButton != null && camera != null && !frameSaved) captureButton.setEnabled(true);
                });
            }
        }, 5000);
    }

    private void applyCurrentExposure(CaptureRequest.Builder request) {
        request.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);
        if (manualSensorSupported && manualExposureMode) {
            request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
            request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, WINDOWS_BASELINE_EXPOSURE_NS);
            request.set(CaptureRequest.SENSOR_SENSITIVITY, WINDOWS_BASELINE_SENSITIVITY_ISO);
            request.set(CaptureRequest.SENSOR_FRAME_DURATION, WINDOWS_BASELINE_FRAME_DURATION_NS);
        } else {
            request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
        }
    }

    private void logOneFrameCaptureResult(String kind, CaptureResult result) {
        logLine("ONE-FRAME " + kind + " RESULT frame=" + result.getFrameNumber()
                + " requestedMode=" + (manualExposureMode ? "manual" : "AE")
                + " exposureNs=" + result.get(CaptureResult.SENSOR_EXPOSURE_TIME)
                + " sensitivityIso=" + result.get(CaptureResult.SENSOR_SENSITIVITY)
                + " frameDurationNs=" + result.get(CaptureResult.SENSOR_FRAME_DURATION)
                + " aeState=" + result.get(CaptureResult.CONTROL_AE_STATE)
                + " sensorTimestampNs=" + result.get(CaptureResult.SENSOR_TIMESTAMP)
                + " sensorTimestampSource=" + sensorTimestampSource
                + " pulseSequenceActive=" + pulseSequenceActive
                + " callbackElapsedRealtimeNs=" + SystemClock.elapsedRealtimeNanos());
    }

    private void analyzeImageInMemory(Image image, boolean compare) {
        int width = image.getWidth();
        int height = image.getHeight();
        final int detectorWidth = 320;
        final int detectorHeight = 180;
        int[] sums = new int[detectorWidth * detectorHeight];
        int[] counts = new int[sums.length];
        byte[] luma = new byte[width * height];
        byte[] detectorLuma = null;
        LumaQualityStats quality = new LumaQualityStats(width, height);
        AnnulusCandidate annulus = null;
        boolean retainAnnulusCode = false;
        try {
            Image.Plane yPlane = image.getPlanes()[0];
            ByteBuffer buffer = yPlane.getBuffer().duplicate();
            int base = buffer.position();
            int rowStride = yPlane.getRowStride();
            int pixelStride = yPlane.getPixelStride();
            for (int y = 0; y < height; y++) {
                int rowStart = base + y * rowStride;
                int dy = y * detectorHeight / height;
                for (int x = 0; x < width; x++) {
                    int value = buffer.get(rowStart + x * pixelStride) & 0xff;
                    luma[y * width + x] = (byte) value;
                    quality.add(x, y, value);
                    int dx = x * detectorWidth / width;
                    int index = dy * detectorWidth + dx;
                    sums[index] += value;
                    counts[index]++;
                }
            }
            detectorLuma = new byte[sums.length];
            for (int i = 0; i < sums.length; i++) {
                if (counts[i] > 0) detectorLuma[i] = (byte) (sums[i] / counts[i]);
            }
            EyeDetection detection = detectEyeRegion(sums, counts, detectorWidth, detectorHeight,
                    width, height, sensorOrientation);
            int lumaP95 = quality.percentileValue(0.95);
            boolean usableLumaSignal = DiagnosticFrameQuality.hasUsableLumaSignal(lumaP95);
            LogGaborIrisCodePrototype.DiagnosticEnrollment enrollment = diagnosticEnrollment;
            boolean collecting = !compare && enrollment != null && enrollment.sampleCount() < 3;
            String diagnosticOnlyFullFrame = null;
            if (usableLumaSignal && manualRoiSelected) {
                annulus = findManualRoiCandidate(luma, width, height,
                        manualRoiXFraction, manualRoiYFraction);
            } else if (usableLumaSignal && detection.candidates != null && (collecting || compare)) {
                annulus = findEyeAnnulusCandidate(luma, width, height, detection.candidates);
            } else if (usableLumaSignal && detection.candidates == null && !collecting && !compare) {
                // Keep the coarse whole-frame search as a visual diagnostic only.
                // Never allow it to supply enrollment or comparison codes.
                diagnosticOnlyFullFrame = findFullFrameProposal(detectorLuma, detectorWidth,
                        detectorHeight, width, height);
            }
            StringBuilder result = new StringBuilder("spatial Y ").append(quality)
                    .append("; ").append(detection.summary);
            if (!usableLumaSignal) {
                result.append(String.format(Locale.US,
                        "; low-signal frame rejected for candidate analysis/enrollment (p95=%d < %d; provisional quality floor)",
                        lumaP95, DiagnosticFrameQuality.MIN_LUMA_P95));
            } else if (manualRoiSelected) {
                result.append("; manually selected ROI annulus ")
                        .append(annulus == null ? "no boundary candidate" : annulus.summary);
            } else if (detection.candidates != null) {
                if (collecting || compare) {
                    result.append("; eye-ROI annulus ")
                            .append(annulus == null ? "no boundary candidate" : annulus.summary);
                } else {
                    result.append("; circular boundary proposals ")
                            .append(formatBoundaryProposal(luma, width, height,
                                    detection.candidates.detectorLeftEye))
                            .append(" / ")
                            .append(formatBoundaryProposal(luma, width, height,
                                    detection.candidates.detectorRightEye));
                }
            } else {
                result.append("; no frontal-face/eye-pair ROI; whole-frame contrast proposal ")
                        .append(diagnosticOnlyFullFrame == null
                                ? "no candidate (contrast heuristic only)"
                                : diagnosticOnlyFullFrame + " (display-only; excluded from matcher)");
            }
            if (compare) {
                if (annulus == null) {
                    result.append("; diagnostic comparison unavailable: no selected or detected eye-ROI candidate");
                } else if (diagnosticConsensus == null) {
                    result.append("; diagnostic comparison unavailable: no in-memory enrollment");
                } else {
                    LogGaborIrisCodePrototype.Score score = LogGaborIrisCodePrototype.compare(
                            diagnosticConsensus, annulus.code, 16);
                    result.append(String.format(Locale.US,
                            "; experimental code distance=%.4f overlap=%.1f%% angular-shift=%d "
                                    + "(no threshold; not an identity decision)",
                            score.maskedHammingDistance, 100.0 * score.overlapFraction,
                            score.angularShift));
                }
            } else if (collecting) {
                if (annulus == null) {
                    result.append("; diagnostic enrollment sample rejected: select an eye ROI or detect a face-derived eye ROI; ")
                            .append(enrollment.sampleCount()).append("/3 retained");
                } else if (!enrollment.add(annulus.code)) {
                    result.append("; diagnostic enrollment sample rejected: unusable code or low overlap; ")
                            .append(enrollment.sampleCount()).append("/3 retained");
                } else {
                    retainAnnulusCode = true;
                    result.append("; diagnostic enrollment sample accepted: ")
                            .append(enrollment.sampleCount()).append("/3 in memory");
                    if (enrollment.sampleCount() == 3) {
                        try {
                            LogGaborIrisCodePrototype.Template consensus = enrollment.consensus();
                            if (consensus.validFraction() == 0) {
                                consensus.clear();
                                result.append("; consensus rejected because no phase bits have majority support");
                            } else {
                                diagnosticConsensus = consensus;
                                result.append(String.format(Locale.US,
                                        "; transient consensus ready, valid bits=%.1f%%",
                                        100.0 * consensus.validFraction()));
                            }
                        } finally {
                            diagnosticEnrollment = null;
                            enrollment.clear();
                            retainAnnulusCode = false;
                        }
                    }
                }
            }
            if (annulus != null && !retainAnnulusCode) annulus.code.clear();
            showPrivateDiagnostic("One-frame eye-region result (pixels discarded; local UI only): " + result);
            frameOperationBusy = false;
            runOnUiThread(() -> {
                if (analyzeButton != null && camera != null) analyzeButton.setEnabled(true);
                if (compareButton != null && camera != null && diagnosticConsensus != null)
                    compareButton.setEnabled(true);
                if (captureButton != null && camera != null && !frameSaved) captureButton.setEnabled(true);
            });
        } finally {
            Arrays.fill(luma, (byte) 0);
            Arrays.fill(sums, 0);
            Arrays.fill(counts, 0);
            if (detectorLuma != null) Arrays.fill(detectorLuma, (byte) 0);
            quality.clear();
            if (annulus != null && !retainAnnulusCode) annulus.code.clear();
        }
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
            final int detectorWidth = 320;
            final int detectorHeight = 180;
            int[] detectorLumaSums = new int[detectorWidth * detectorHeight];
            int[] detectorLumaCounts = new int[detectorWidth * detectorHeight];
            byte[] detectorLuma = new byte[detectorWidth * detectorHeight];
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
                            int x = (int) (offset % width);
                            int y = (int) (offset / width);
                            quality.add(x, y, value);
                            int dx = x * detectorWidth / width;
                            int dy = y * detectorHeight / height;
                            int detectorIndex = dy * detectorWidth + dx;
                            detectorLumaSums[detectorIndex] += value;
                            detectorLumaCounts[detectorIndex]++;
                        }
                    }
                }
                for (int i = 0; i < detectorLuma.length; i++) {
                    if (detectorLumaCounts[i] > 0)
                        detectorLuma[i] = (byte) (detectorLumaSums[i] / detectorLumaCounts[i]);
                }
                EyeDetection eyeDetection = detectEyeRegion(detectorLumaSums, detectorLumaCounts,
                        detectorWidth, detectorHeight, width, height, sensorOrientation, false);
                String eyeSummary = eyeDetection.candidates == null
                        ? "no generic face-derived eye-box proposal (not proof no eye is present)"
                        : "generic face-derived eye-box proposal present; coordinates withheld";
                String wholeFrameSummary;
                if (!DiagnosticFrameQuality.hasUsableLumaSignal(quality.percentileValue(0.95))) {
                    wholeFrameSummary = "skipped by provisional low-signal gate";
                } else {
                    CircularBoundaryProposal.Proposal proposal = CircularBoundaryProposal.findCoarse(
                            detectorLuma, detectorWidth, detectorHeight, 0, 0,
                            detectorWidth, detectorHeight);
                    wholeFrameSummary = proposal.valid
                            ? "contrast candidate (display-only heuristic; coordinates withheld)"
                            : "no whole-frame contrast candidate";
                }
                showSavedFrameDiagnostic("On-device summary of private frame (no image exported): "
                        + "Y " + stats[0] + "; U " + stats[1] + "; V " + stats[2]
                        + "; spatial Y " + quality
                        + "; coarse eye-region probe " + eyeSummary
                        + "; whole-frame contrast fallback " + wholeFrameSummary);
            } catch (Exception e) {
                logLine("Could not summarize saved private YUV: " + e);
            } finally {
                Arrays.fill(bytes, (byte) 0);
                Arrays.fill(detectorLumaSums, 0);
                Arrays.fill(detectorLumaCounts, 0);
                Arrays.fill(detectorLuma, (byte) 0);
                quality.clear();
                for (PlaneStats plane : stats) plane.clear();
            }
        }, "iris-yuv-summary").start();
    }

    /** Runs Android's generic frontal-face detector on a downsampled luma image in memory. */
    private static String estimateEyeRegion(int[] lumaSums, int[] lumaCounts, int width,
                                            int height, int sourceWidth, int sourceHeight,
                                            int rotationDegrees) {
        return detectEyeRegion(lumaSums, lumaCounts, width, height,
                sourceWidth, sourceHeight, rotationDegrees).summary;
    }

    private static EyeDetection detectEyeRegion(int[] lumaSums, int[] lumaCounts, int width,
                                                 int height, int sourceWidth, int sourceHeight,
                                                 int rotationDegrees) {
        return detectEyeRegion(lumaSums, lumaCounts, width, height, sourceWidth, sourceHeight,
                rotationDegrees, true);
    }

    private static EyeDetection detectEyeRegion(int[] lumaSums, int[] lumaCounts, int width,
                                                 int height, int sourceWidth, int sourceHeight,
                                                 int rotationDegrees, boolean includeDetails) {
        boolean swapDimensions = rotationDegrees % 180 != 0;
        int outputWidth = swapDimensions ? height : width;
        int outputHeight = swapDimensions ? width : height;
        int[] grayscalePixels = new int[outputWidth * outputHeight];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int source = y * width + x;
                int gray = lumaCounts[source] == 0 ? 0 : lumaSums[source] / lumaCounts[source];
                int destX;
                int destY;
                switch ((rotationDegrees % 360 + 360) % 360) {
                    case 90:
                        destX = height - 1 - y;
                        destY = x;
                        break;
                    case 180:
                        destX = width - 1 - x;
                        destY = height - 1 - y;
                        break;
                    case 270:
                        destX = y;
                        destY = width - 1 - x;
                        break;
                    default:
                        destX = x;
                        destY = y;
                        break;
                }
                grayscalePixels[destY * outputWidth + destX] = Color.rgb(gray, gray, gray);
            }
        }
        Bitmap bitmap = Bitmap.createBitmap(outputWidth, outputHeight, Bitmap.Config.RGB_565);
        try {
            bitmap.setPixels(grayscalePixels, 0, outputWidth, 0, 0, outputWidth, outputHeight);
            FaceDetector detector = new FaceDetector(outputWidth, outputHeight, 1);
            FaceDetector.Face[] faces = new FaceDetector.Face[1];
            int faceCount = detector.findFaces(bitmap, faces);
            if (faceCount == 0 || faces[0] == null) {
                return new EyeDetection("no frontal-face candidate at " + outputWidth + "x" + outputHeight
                        + " (not evidence that no eye is present)", null);
            }
            FaceDetector.Face face = faces[0];
            PointF eyePairMidpoint = new PointF();
            face.getMidPoint(eyePairMidpoint);
            EyeRegionGeometry.Pair pair = EyeRegionGeometry.fromFaceDetection(
                    eyePairMidpoint.x, eyePairMidpoint.y, face.eyesDistance(),
                    sourceWidth, sourceHeight, width, height, rotationDegrees);
            String summary = includeDetails ? String.format(Locale.US,
                    "frontal-face candidate confidence=%.2f eye-pair-midpoint=(%.1f,%.1f) "
                            + "eye-separation=%.1f px at %dx%d; sensor eye candidates A=(%.0f,%.0f) "
                            + "crop=[%d,%d..%d,%d], B=(%.0f,%.0f) crop=[%d,%d..%d,%d]; "
                            + "heuristic boxes only, not iris localization",
                    face.confidence(), eyePairMidpoint.x, eyePairMidpoint.y,
                    face.eyesDistance(), outputWidth, outputHeight,
                    pair.detectorLeftEye.centerX, pair.detectorLeftEye.centerY,
                    pair.detectorLeftEye.cropLeft, pair.detectorLeftEye.cropTop,
                    pair.detectorLeftEye.cropRight, pair.detectorLeftEye.cropBottom,
                    pair.detectorRightEye.centerX, pair.detectorRightEye.centerY,
                    pair.detectorRightEye.cropLeft, pair.detectorRightEye.cropTop,
                    pair.detectorRightEye.cropRight, pair.detectorRightEye.cropBottom)
                    : "generic frontal-face candidate and heuristic eye-box proposals available";
            return new EyeDetection(summary, pair);
        } catch (RuntimeException e) {
            return new EyeDetection("unavailable: " + e.getClass().getSimpleName(), null);
        } finally {
            Arrays.fill(grayscalePixels, 0);
            bitmap.eraseColor(Color.BLACK);
            bitmap.recycle();
        }
    }

    private static String formatBoundaryProposal(byte[] luma, int width, int height,
                                                  EyeRegionGeometry.Candidate eye) {
        CircularBoundaryProposal.Proposal proposal = CircularBoundaryProposal.find(luma, width, height,
                eye.cropLeft, eye.cropTop, eye.cropRight, eye.cropBottom);
        if (!proposal.valid) return "no circular boundary candidate";
        return String.format(Locale.US,
                "pupil=(%d,%d) r=%d iris-r=%d edge-strength=%.3f/%.3f (proposal only)",
                proposal.pupilCenterX, proposal.pupilCenterY, proposal.pupilRadius,
                proposal.irisRadius, proposal.pupilBoundaryStrength,
                proposal.limbusBoundaryStrength);
    }

    private static AnnulusCandidate findEyeAnnulusCandidate(byte[] luma, int width, int height,
                                                             EyeRegionGeometry.Pair eyes) {
        CircularBoundaryProposal.Proposal left = CircularBoundaryProposal.find(luma, width, height,
                eyes.detectorLeftEye.cropLeft, eyes.detectorLeftEye.cropTop,
                eyes.detectorLeftEye.cropRight, eyes.detectorLeftEye.cropBottom);
        CircularBoundaryProposal.Proposal right = CircularBoundaryProposal.find(luma, width, height,
                eyes.detectorRightEye.cropLeft, eyes.detectorRightEye.cropTop,
                eyes.detectorRightEye.cropRight, eyes.detectorRightEye.cropBottom);
        CircularBoundaryProposal.Proposal selected;
        if (!left.valid) selected = right;
        else if (!right.valid) selected = left;
        else selected = Math.min(left.pupilBoundaryStrength, left.limbusBoundaryStrength)
                >= Math.min(right.pupilBoundaryStrength, right.limbusBoundaryStrength) ? left : right;
        if (!selected.valid) return null;

        LogGaborIrisCodePrototype.Template code = LogGaborIrisCodePrototype.encode(
                luma, width, height, selected.pupilCenterX, selected.pupilCenterY,
                selected.pupilRadius, selected.irisRadius);
        if (code.validFraction() == 0) {
            code.clear();
            return null;
        }
        String summary = String.format(Locale.US,
                "pupil=(%d,%d) r=%d iris-r=%d edge-strength=%.3f/%.3f phase-bits-valid=%.3f "
                        + "(face-derived eye ROI; experimental only)",
                selected.pupilCenterX, selected.pupilCenterY, selected.pupilRadius,
                selected.irisRadius, selected.pupilBoundaryStrength,
                selected.limbusBoundaryStrength, code.validFraction());
        return new AnnulusCandidate(code, summary);
    }

    private static AnnulusCandidate findManualRoiCandidate(byte[] luma, int width, int height,
                                                            float xFraction, float yFraction) {
        double centerX = xFraction * width;
        double centerY = yFraction * height;
        int halfSize = Math.min(width, height) / 4;
        if (centerX < halfSize || centerY < halfSize
                || centerX + halfSize >= width || centerY + halfSize >= height) {
            return null;
        }
        int left = (int) Math.floor(centerX - halfSize);
        int top = (int) Math.floor(centerY - halfSize);
        int right = (int) Math.ceil(centerX + halfSize);
        int bottom = (int) Math.ceil(centerY + halfSize);
        CircularBoundaryProposal.Proposal proposal = CircularBoundaryProposal.find(
                luma, width, height, left, top, right, bottom);
        if (!proposal.valid) return null;
        LogGaborIrisCodePrototype.Template code = LogGaborIrisCodePrototype.encode(
                luma, width, height, proposal.pupilCenterX, proposal.pupilCenterY,
                proposal.pupilRadius, proposal.irisRadius);
        if (code.validFraction() == 0) {
            code.clear();
            return null;
        }
        String summary = String.format(Locale.US,
                "pupil=(%d,%d) r=%d iris-r=%d edge-strength=%.3f/%.3f phase-bits-valid=%.3f "
                        + "(user-selected square ROI; experimental only)",
                proposal.pupilCenterX, proposal.pupilCenterY, proposal.pupilRadius,
                proposal.irisRadius, proposal.pupilBoundaryStrength,
                proposal.limbusBoundaryStrength, code.validFraction());
        return new AnnulusCandidate(code, summary);
    }

    private static String findFullFrameProposal(byte[] detectorLuma, int detectorWidth,
                                                int detectorHeight, int sourceWidth,
                                                int sourceHeight) {
        CircularBoundaryProposal.Proposal proposal = CircularBoundaryProposal.findCoarse(
                detectorLuma, detectorWidth, detectorHeight, 0, 0, detectorWidth, detectorHeight);
        if (!proposal.valid) return null;
        double scaleX = (double) sourceWidth / detectorWidth;
        double scaleY = (double) sourceHeight / detectorHeight;
        double centerX = proposal.pupilCenterX * scaleX;
        double centerY = proposal.pupilCenterY * scaleY;
        double scale = (scaleX + scaleY) * 0.5;
        return String.format(Locale.US,
                "candidate center=(%.0f,%.0f) sensor px pupil-r=%.0f iris-r=%.0f "
                        + "edge-strength=%.3f/%.3f "
                        + "(whole-frame contrast heuristic; not iris localization)",
                centerX, centerY, proposal.pupilRadius * scale, proposal.irisRadius * scale,
                proposal.pupilBoundaryStrength, proposal.limbusBoundaryStrength);
    }

    private static final class AnnulusCandidate {
        final LogGaborIrisCodePrototype.Template code;
        final String summary;
        AnnulusCandidate(LogGaborIrisCodePrototype.Template code, String summary) {
            this.code = code;
            this.summary = summary;
        }
    }

    private static final class EyeDetection {
        final String summary;
        final EyeRegionGeometry.Pair candidates;
        EyeDetection(String summary, EyeRegionGeometry.Pair candidates) {
            this.summary = summary;
            this.candidates = candidates;
        }
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
        void clear() {
            count = 0;
            sum = 0;
            sumSquares = 0;
            min = 256;
            max = -1;
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

        int percentileValue(double fraction) {
            return percentile(fraction);
        }

        void clear() {
            Arrays.fill(previousRow, (byte) 0);
            Arrays.fill(histogram, 0);
            Arrays.fill(tileSums, 0);
            Arrays.fill(tileSumSquares, 0);
            Arrays.fill(tileCounts, 0);
            horizontalGradient = 0;
            verticalGradient = 0;
            lowClipped = 0;
            highClipped = 0;
            count = 0;
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
        updateRoiOverlay();
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

    private void pulseAndCaptureOnce() {
        if (camera == null || completedFrames.get() == 0) {
            logLine("IR capture blocked: first iris frame callback has not arrived.");
            return;
        }
        if (frameOperationBusy) {
            logLine("IR capture blocked: another one-frame operation is pending.");
            return;
        }
        if (pulseUsed) {
            logLine("IR capture blocked: this app session allows one pulse only.");
            return;
        }
        pulseUsed = true;
        pulseSequenceActive = true;
        frameOperationBusy = true;
        irButton.setEnabled(false);
        logLine("Starting one minimum-current IR pulse (hardware code 1, maximum 1 second); one YUV capture will be requested while it is on.");
        new Thread(() -> {
            String response;
            long pulseRequestElapsedNs = 0;
            long onAckElapsedNs = 0;
            long stopRequestElapsedNs = 0;
            long offAckElapsedNs = 0;
            try (Socket socket = new Socket(InetAddress.getByName("127.0.0.1"), TORCH_PORT);
                 PrintWriter out = new PrintWriter(socket.getOutputStream(), true);
                 BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()))) {
                socket.setSoTimeout(2500);
                pulseRequestElapsedNs = SystemClock.elapsedRealtimeNanos();
                out.println("PULSE");
                String state = in.readLine();
                onAckElapsedNs = SystemClock.elapsedRealtimeNanos();
                if ("ON".equals(state)) {
                    CountDownLatch frameComplete = new CountDownLatch(1);
                    runOnUiThread(() -> {
                        if (!pulseSequenceActive || camera == null || session == null) {
                            logLine("IR capture cancelled because the camera activity closed.");
                            frameComplete.countDown();
                            return;
                        }
                        logLine("Minimum IR level is on; requesting one frame now.");
                        frameOperationBusy = false;
                        captureOneFrame(frameComplete::countDown);
                    });
                    boolean delivered = frameComplete.await(850, TimeUnit.MILLISECONDS);
                    pulseSequenceActive = false;
                    if (!delivered) {
                        saveNextFrame = false;
                        frameOperationBusy = false;
                        finishPendingSave();
                        runOnUiThread(() -> {
                            logLine("IR frame did not arrive before the bounded pulse window; cancelling the pending save.");
                            if (captureButton != null && camera != null && !frameSaved)
                                captureButton.setEnabled(true);
                            if (analyzeButton != null && camera != null) analyzeButton.setEnabled(true);
                        });
                    }
                    stopRequestElapsedNs = SystemClock.elapsedRealtimeNanos();
                    out.println("STOP");
                    String finalState = in.readLine();
                    offAckElapsedNs = SystemClock.elapsedRealtimeNanos();
                    response = "OFF".equals(finalState) ? "OFF confirmed by helper" : "unexpected helper reply: " + finalState;
                } else {
                    response = "pulse rejected before LED-on: " + state;
                }
            } catch (Exception e) {
                response = "ERROR " + e.getClass().getSimpleName() + ": " + e.getMessage();
            }
            String result = response + " pulseRequestElapsedRealtimeNs=" + pulseRequestElapsedNs
                    + " onAckElapsedRealtimeNs=" + onAckElapsedNs
                    + " stopRequestElapsedRealtimeNs=" + stopRequestElapsedNs
                    + " offAckElapsedRealtimeNs=" + offAckElapsedNs;
            runOnUiThread(() -> {
                pulseSequenceActive = false;
                if (!saveNextFrame && !analyzeNextFrame) frameOperationBusy = false;
                logLine("IR capture helper result: " + result + ".");
            });
        }, "iris-torch-capture").start();
    }

    private void createPreviewSession(CameraDevice device) {
        try {
            CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            request.addTarget(previewSurface);
            request.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);
            if (manualSensorSupported) {
                request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
                request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, WINDOWS_BASELINE_EXPOSURE_NS);
                request.set(CaptureRequest.SENSOR_SENSITIVITY, WINDOWS_BASELINE_SENSITIVITY_ISO);
                request.set(CaptureRequest.SENSOR_FRAME_DURATION, WINDOWS_BASELINE_FRAME_DURATION_NS);
                manualExposureMode = true;
                logLine("Starting iris preview at source-derived manual baseline: 30 ms, ISO 100, "
                        + "33.5 ms frame duration; IR remains off.");
            } else {
                request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
                manualExposureMode = false;
            }
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
                        if (analyzeButton != null) analyzeButton.setEnabled(true);
                        if (selectRoiButton != null) selectRoiButton.setEnabled(true);
                        if (compareButton != null)
                            compareButton.setEnabled(diagnosticConsensus != null);
                        if (exposureButton != null)
                            exposureButton.setEnabled(manualSensorSupported);
                        if (exposureButton != null && manualSensorSupported)
                            exposureButton.setText("Use AE auto (restore)");
                    });
                    try {
                        configured.setRepeatingRequest(request.build(), previewCaptureCallback(), cameraHandler);
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

    private CameraCaptureSession.CaptureCallback previewCaptureCallback() {
        return new CameraCaptureSession.CaptureCallback() {
            @Override public void onCaptureCompleted(CameraCaptureSession s, CaptureRequest r,
                                                    android.hardware.camera2.TotalCaptureResult result) {
                int n = completedFrames.incrementAndGet();
                if (n == 1 && irButton != null && !pulseUsed)
                    runOnUiThread(() -> irButton.setEnabled(true));
                if (n == 1 || n % 30 == 0) {
                    Long exposureNs = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
                    Integer sensitivityIso = result.get(CaptureResult.SENSOR_SENSITIVITY);
                    Long frameDurationNs = result.get(CaptureResult.SENSOR_FRAME_DURATION);
                    Integer aeState = result.get(CaptureResult.CONTROL_AE_STATE);
                    Long sensorTimestampNs = result.get(CaptureResult.SENSOR_TIMESTAMP);
                    logLine("CAPTURE RESULT callback #" + n + " frame=" + result.getFrameNumber()
                            + " mode=" + (manualExposureMode ? "manual" : "AE")
                            + " exposureNs=" + exposureNs + " sensitivityIso=" + sensitivityIso
                            + " frameDurationNs=" + frameDurationNs + " aeState=" + aeState
                            + " sensorTimestampNs=" + sensorTimestampNs);
                }
            }

            @Override public void onCaptureFailed(CameraCaptureSession s, CaptureRequest r,
                                                 android.hardware.camera2.CaptureFailure failure) {
                logLine("CAPTURE FAILED reason=" + failure.getReason()
                        + " frame=" + failure.getFrameNumber());
            }
        };
    }

    private void closeCamera() {
        if (irButton != null) irButton.setEnabled(false);
        pulseSequenceActive = false;
        saveNextFrame = false;
        analyzeNextFrame = false;
        frameOperationBusy = false;
        finishPendingSave();
        if (captureButton != null) captureButton.setEnabled(false);
        if (analyzeButton != null) analyzeButton.setEnabled(false);
        if (selectRoiButton != null) selectRoiButton.setEnabled(false);
        roiSelectionMode = false;
        if (roiOverlay != null) roiOverlay.setSelectionMode(false);
        if (compareButton != null) compareButton.setEnabled(false);
        manualRoiSelected = false;
        manualRoiXFraction = 0;
        manualRoiYFraction = 0;
        updateRoiOverlay();
        clearDiagnosticEnrollmentAfterCameraWork();
        if (status != null) status.setText("Preview closed; transient diagnostic data cleared.");
        manualExposureMode = false;
        if (exposureButton != null) {
            exposureButton.setEnabled(false);
            exposureButton.setText("Use manual 30 ms / ISO 100 baseline");
        }
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

    private static final class RoiOverlayView extends android.view.View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private boolean selected;
        private boolean selectionMode;
        private float centerX;
        private float centerY;
        private float radius;

        RoiOverlayView(Context context) {
            super(context);
            setWillNotDraw(false);
            paint.setColor(Color.YELLOW);
            paint.setStrokeWidth(3.0f);
            paint.setStyle(Paint.Style.STROKE);
        }

        void setSelectionMode(boolean active) {
            selectionMode = active;
            invalidate();
        }

        void setRoi(boolean visible, float x, float y, float roiRadius) {
            selected = visible;
            centerX = x;
            centerY = y;
            radius = roiRadius;
            setContentDescription(visible ? "Manually selected diagnostic ROI" : null);
            invalidate();
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (selected) {
                canvas.drawCircle(centerX, centerY, radius, paint);
                canvas.drawLine(centerX - 12, centerY, centerX + 12, centerY, paint);
                canvas.drawLine(centerX, centerY - 12, centerX, centerY + 12, paint);
            }
            if (selectionMode) {
                paint.setStyle(Paint.Style.FILL);
                paint.setTextSize(22.0f);
                canvas.drawText("Tap the center of one iris", 16, 30, paint);
                paint.setStyle(Paint.Style.STROKE);
            }
        }
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
            for (int i = 0; i < getChildCount(); i++)
                getChildAt(i).measure(MeasureSpec.makeMeasureSpec(childWidth, MeasureSpec.EXACTLY),
                                      MeasureSpec.makeMeasureSpec(childHeight, MeasureSpec.EXACTLY));
        }
        @Override protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
            if (getChildCount() == 0) return;
            for (int i = 0; i < getChildCount(); i++) {
                android.view.View child = getChildAt(i);
                int width = child.getMeasuredWidth();
                int height = child.getMeasuredHeight();
                int childLeft = (getWidth() - width) / 2;
                int childTop = (getHeight() - height) / 2;
                child.layout(childLeft, childTop, childLeft + width, childTop + height);
            }
        }
    }
}
