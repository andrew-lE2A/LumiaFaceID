# IR0861 matcher and segmentation research

## Current project evidence

The experimental `LogGaborIrisCodePrototype` is a phase-code mechanics sample,
not a recognition implementation. It expects caller-supplied pupil and iris
circles. `CircularBoundaryProposal` searches for contrast boundaries in a
user-selected eye crop, assumes concentric circles, and deliberately describes
itself as a proposal rather than a segmenter. It does not produce a pixel mask
for eyelids, eyelashes, reflections, or other occluded iris regions.

The only stored-frame analysis in the project was performed on-device on one
1920x1080 I420 frame captured with IR off under uncontrolled room lighting.
The generic face detector did not yield an eye box. The frame has not been
shown to contain an iris, and no camera pixels were transferred to this host.
The synthetic matcher study uses generated patterns and cannot support a match
threshold or error-rate estimate. Keep the current code in the diagnostic path.

## What the research changes

The recognized pipeline needs independent stages for (1) locating iris
boundaries, (2) identifying valid iris pixels and occlusions, (3) normalizing
those pixels for scale and rotation, (4) encoding features, and (5) comparing
with an overlap-aware score. The [OSIRIS reference paper](https://www.sciencedirect.com/science/article/pii/S0167865515002986)
describes segmentation, normalization, feature extraction, and template
matching as distinct modules, and reports evaluation on public iris datasets.

A newer [University of Notre Dame CVRL repository](https://github.com/CVRL/OpenSourceIrisRecognition)
reports IREX-submitted C++ methods and explicitly uses polar-normalized iris
inputs. Its documented segmentation estimates both a per-pixel valid-iris mask
and circular boundary parameters. Its ArcIris model takes 512x64 normalized
images derived from 640x480 inputs; that is a research reference, not evidence
that its network or weights will fit a 32-bit MSM8994 phone or generalize to the
Lumia IR0861 optics. The repository's license note asks users to discuss terms
for closed-source or commercial distributions, so do not copy or bundle its
code or weights without resolving licensing and provenance.

NIST's [IREX program](https://www.nist.gov/programs-projects/iris-exchange-irex-overview)
tracks image quality assessment separately from recognition performance.
That supports treating frame quality as an explicit gate before enrollment or
matching. Current `MIN_LUMA_P95` is only a weak diagnostic floor; it cannot
replace iris-area, occlusion, sharpness, saturation, and segmentation-confidence
checks.

### Research baseline review (2026-11-05)

The Notre Dame CVRL repository is a stronger evaluation target than the
prototype's assumed concentric annulus. Its IREX C++/Python segmenter predicts
a pixel-level valid-iris mask for eyelid/eyelash occlusion and a separate
regression of inner/outer boundary circles. Its HDBIF matcher uses the two
masks to compare only overlapping valid regions and normalizes the fractional
Hamming score. This is directly relevant to the prototype's missing mask and
the risk that low-overlap samples score deceptively well. The ArcIris route
uses a ResNet-100 on a 512x64 polar-normalized crop; that is a much heavier
candidate for Cityman's aging 32-bit application processor than a classical
CPU baseline, and none of its public-dataset results establish performance on
IR0861. See the [CVRL method descriptions](https://github.com/CVRL/OpenSourceIrisRecognition).

NIST VASIR documents the end-to-end stages (video eye extraction and quality
selection, segmentation, polar normalization, feature encoding and matching),
but NIST marks its released beta source as incomplete and lists a 2013-era
Qt 4.8 / OpenCV 2.3.1 environment. It is useful as a pipeline checklist, not
as a drop-in Android dependency. See [NIST VASIR](https://www.nist.gov/services-resources/software/video-based-automatic-system-iris-recognition-vasir).

The CVRL repository describes the software as research-use and asks users to
discuss licensing for commercial or closed-source distribution; no model or
source was copied into this project. Before any adoption, inspect the exact
license and provenance of the selected method, model weights, and dependencies.
The near-term implementation target remains a local segmentation contract
(inner/outer boundaries, valid-pixel mask, confidence, and quality gates),
then compare a lightweight classical implementation against a research model
on suitable data. Do not use the experimental encoder for unlock or treat
cross-sensor research results as IR0861 accuracy.

### Lower-cost boundary-localization candidate

NIST's 2024 IrisFinder work is a more practical immediate comparison for the
current circle proposal than deploying a neural segmenter. The report describes
morphological enhancement, pupil Hough initialization, and gradient-based
boundary refinement, with reported boundary localization on 99.3% of ND-Iris
0405 images and 99.2% of OPS-4 images. The supplied C++ project depends on
OpenCV and is explicitly alpha; it localizes boundaries, but it does not
provide occlusion masks, feature encoding, matching, liveness, or evidence on
the Lumia sensor. NIST describes the source as public domain/no license
requirements, but the repository itself does not expose a conventional license
file. Preserve attribution and recheck source provenance before porting. See
the [NIST report](https://www.nist.gov/publications/open-source-iris-segmentation-algorithm-non-ideal-images),
[report PDF/source notice](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=935825),
and [IrisFinder C++ implementation](https://github.com/gwquinn/IrisFinder).

The next algorithm experiment should compare this boundary locator against the
existing circular proposal on public evaluation images, then against diagnostic
IR0861 captures after the phone is uncovered. Keep mask estimation as a separate
stage: a good pair of circles alone does not handle eyelids or reflections and
cannot serve as a biometric decision.

Source inspection narrows the porting work: IrisFinder's C++ uses an inverted
intensity pupil mask, gradient-thresholded contours, Zhang-Suen thinning from
OpenCV `ximgproc`, a radius-voting accumulator for the pupil, separate left and
right limbus arcs, then `DownhillSolver` refinement of elliptical boundaries.
Its image loader selects the red channel from color input. The Lumia IR stream
is currently consumed as YUV and has shown color-channel overlays, so a port
must explicitly decide whether to feed the luma plane or a channel after
checking controlled IR0861 captures; do not blindly reuse the red-channel
choice. The algorithm also requires OpenCV contrib APIs that the current probe
build does not bundle. Treat a JNI/OpenCV port as a candidate only after
benchmarking the algorithm and its OpenCV ARMv7 build cost, not as a drop-in
patch. The implementation details are visible in the [IrisFinder C++ source](https://github.com/gwquinn/IrisFinder/blob/master/src/irisFinder.cpp).

## Implementation direction

1. Preserve the current synthetic coder only as a unit-level mechanics
   prototype. Do not tune a biometric threshold from the synthetic score JSON.
2. Build a segmentation interface that returns inner/outer contours, a
   per-pixel validity mask, confidence, and a compact quality summary. Do not
   encode when the segmentation or quality gate fails.
3. Compare an interpretable CPU path (classical boundary/occlusion estimation)
   with a small inference path only after suitable representative IR0861 frames
   exist. Public NIR datasets can check basic implementation behavior, but
   cross-sensor results cannot establish Lumia accuracy.
4. Keep any future frames and templates private to the phone. Record only
   aggregate quality and score distributions on the host unless the user
   explicitly authorizes a different privacy model.
5. Before any Keyguard connection, collect consented repeated captures over
   separate sessions and evaluate genuine/impostor distributions, enrollment
   stability, presentation attacks, and failure handling. A segmentation
   benchmark or a successful frame callback is not unlock evidence.

## Source references

- Othman et al., [OSIRIS: An open source iris recognition software](https://www.sciencedirect.com/science/article/pii/S0167865515002986), *Pattern Recognition Letters* 82 (2016), 124-131.
- CVRL, [Notre Dame Open-Source Iris Recognition](https://github.com/CVRL/OpenSourceIrisRecognition), repository README and cited methods.
- NIST, [Iris Exchange (IREX) overview](https://www.nist.gov/programs-projects/iris-exchange-irex-overview).
- NIST, [IREX II Image Quality and Calibration Evaluation](https://www.nist.gov/itl/iad/btg/irex-ii-iqce).
- NIST, [Video-based Automatic System for Iris Recognition (VASIR)](https://www.nist.gov/services-resources/software/video-based-automatic-system-iris-recognition-vasir), including its incomplete beta status and pipeline stages.
- AOSP, [biometric security guide](https://source.android.com/docs/security/features/biometric), and Android CDD, [biometric sensor requirements](https://android.googlesource.com/platform/compatibility/cdd/+/8e8a1dc3a488c0fa41471855ad29539856d7bab7/7_hardware-compatibility/7_3_sensors.md), for lockscreen class requirements.
