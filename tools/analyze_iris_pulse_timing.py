#!/usr/bin/env python3
"""Summarize iris probe pulse/capture log timing without reading image data."""

import argparse
import json
import re
import sys


FIELDS = (
    "pulseRequestElapsedRealtimeNs",
    "onAckElapsedRealtimeNs",
    "stopRequestElapsedRealtimeNs",
    "offAckElapsedRealtimeNs",
)
FIELD_RE = re.compile(r"(\w+)=(-?\d+)")
FRAME_RE = re.compile(r"ONE-FRAME (SAVE|ANALYZE|COMPARE) RESULT\b")
REQUEST_RE = re.compile(r"ONE-FRAME REQUEST\b")
IMAGE_RE = re.compile(r"ONE-FRAME YUV IMAGE\b")
HELPER_RE = re.compile(r"IR capture helper result:")


def flag_in(line, name):
    match = re.search(r"\b" + re.escape(name) + r"=(true|false)\b", line)
    return match.group(1) == "true" if match else False


def fields_in(line):
    return {key: int(value) for key, value in FIELD_RE.findall(line)}


def parse_log(lines):
    frames = []
    requests = []
    images = []
    pulses = []
    for line in lines:
        values = fields_in(line)
        frame_match = FRAME_RE.search(line)
        if frame_match:
            needed = ("sensorTimestampNs", "exposureNs", "sensorTimestampSource",
                      "callbackElapsedRealtimeNs", "frame")
            if all(key in values for key in needed):
                frame = {key: values[key] for key in needed}
                frame["kind"] = frame_match.group(1)
                frame["pulseSequenceActive"] = flag_in(line, "pulseSequenceActive")
                frames.append(frame)
        elif REQUEST_RE.search(line) and "submitElapsedRealtimeNs" in values:
            requests.append({
                "submitElapsedRealtimeNs": values["submitElapsedRealtimeNs"],
                "pulseSequenceActive": flag_in(line, "pulseSequenceActive"),
                "sensorTimestampSource": values.get("sensorTimestampSource"),
            })
        elif IMAGE_RE.search(line) and "timestampNs" in values:
            images.append({
                "timestampNs": values["timestampNs"],
                "callbackElapsedRealtimeNs": values.get("callbackElapsedRealtimeNs", 0),
                "pulseSequenceActive": flag_in(line, "pulseSequenceActive"),
            })
        elif HELPER_RE.search(line) and all(key in values for key in FIELDS):
            pulse = {key: values[key] for key in FIELDS if key in values}
            pulse["offConfirmed"] = "OFF confirmed by helper" in line
            pulses.append(pulse)
    return frames, requests, images, pulses


def correlate(frames, requests, images, pulses):
    unused = set(range(len(frames)))
    unused_images = set(range(len(images)))
    image_to_frame = {}
    for frame_index, frame in enumerate(frames):
        matching_images = [index for index in unused_images
                           if images[index]["timestampNs"] == frame["sensorTimestampNs"]]
        if matching_images:
            image_index = matching_images[0]
            unused_images.remove(image_index)
            image_to_frame[image_index] = frame_index
    matched_pairs = [
        {"frame": frames[frame_index], "image": images[image_index],
         "timestamp_matches": True}
        for image_index, frame_index in sorted(image_to_frame.items())
    ]
    matched_frame_ids = set(image_to_frame.values())
    matched_image_ids = set(image_to_frame)
    unused_images = set(range(len(images)))
    results = []
    for pulse in pulses:
        start = pulse["pulseRequestElapsedRealtimeNs"]
        on_ack = pulse["onAckElapsedRealtimeNs"]
        stop = pulse["stopRequestElapsedRealtimeNs"]
        off_ack = pulse["offAckElapsedRealtimeNs"]
        request_candidates = [request for request in requests
                              if request["pulseSequenceActive"]
                              and on_ack <= request["submitElapsedRealtimeNs"] <= stop]
        request = request_candidates[-1] if request_candidates else None
        matching_images = [index for index in unused_images
                           if images[index]["pulseSequenceActive"]
                           and on_ack <= images[index]["callbackElapsedRealtimeNs"] <= stop]
        image_index = matching_images[0] if matching_images else None
        image = images[image_index] if image_index is not None else None
        if image_index is not None:
            unused_images.remove(image_index)

        frame_index = image_to_frame.get(image_index) if image_index is not None else None
        if frame_index is not None and frame_index not in unused:
            frame_index = None
        frame = frames[frame_index] if frame_index is not None else None
        if frame_index is not None:
            unused.remove(frame_index)

        request_bracketed = bool(request and on_ack <= request["submitElapsedRealtimeNs"] <= stop)
        image_bracketed = bool(image and image["pulseSequenceActive"]
                               and on_ack <= image["callbackElapsedRealtimeNs"] <= stop)
        frame_identity_matches = bool(frame and image)
        transaction_bracketed = bool(pulse["offConfirmed"] and request_bracketed
                                     and image_bracketed and frame_identity_matches)

        result = {
            "frame": frame,
            "request": request,
            "image": image,
            "pulse": pulse,
            "clock_comparable": bool(frame and frame["sensorTimestampSource"] == 1),
            "request_submitted_after_on_ack": request_bracketed,
            "matching_yuv_image_delivered_before_stop": image_bracketed,
            "capture_result_matches_yuv_timestamp": frame_identity_matches,
            "capture_transaction_bracketed_by_helper": transaction_bracketed,
            "interpretation": (
                "No matching still result was found between the helper ON and OFF acknowledgements."
                if frame is None else
                "Camera timestamp source is UNKNOWN; use the result/image timestamp equality and request ordering, not cross-clock subtraction."
                if frame["sensorTimestampSource"] != 1 else
                "The interval is a software request/ack envelope, not a measured optical LED interval."
            ),
        }

        if frame and frame["sensorTimestampSource"] == 1:
            exposure_start = frame["sensorTimestampNs"]
            exposure_end = exposure_start + frame["exposureNs"]
            # The helper writes the LED after receiving PULSE and before ON,
            # then writes zero after STOP and before OFF. These are only outer
            # software bounds; they say nothing about optical transition lag.
            result["first_row_exposure"] = {
                "start_elapsed_realtime_ns": exposure_start,
                "end_elapsed_realtime_ns": exposure_end,
            }
            result["exposure_start_minus_pulse_request_ns"] = exposure_start - start
            result["exposure_start_minus_on_ack_ns"] = exposure_start - on_ack
            result["exposure_end_minus_stop_request_ns"] = exposure_end - stop
            result["exposure_end_minus_off_ack_ns"] = exposure_end - off_ack
            bounds_valid = (pulse["offConfirmed"] and start > 0 and on_ack >= start
                            and stop >= on_ack and off_ack >= stop)
            result["software_bounds_valid"] = bounds_valid
            if bounds_valid:
                overlap_start = max(exposure_start, start)
                overlap_end = min(exposure_end, off_ack)
                result["software_envelope_overlap_ns"] = max(0, overlap_end - overlap_start)
        results.append(result)

    return {
        "schema": "lumia-iris-pulse-timing-summary-v2",
        "privacy": "Only parsed timing metadata is processed; no image or biometric data is read.",
        "pulse_count": len(pulses),
        "still_result_count": len(frames),
        "still_request_count": len(requests),
        "yuv_image_count": len(images),
        "matched_capture_result_yuv_pairs": matched_pairs,
        "capture_result_yuv_match_count": len(matched_pairs),
        "results": results,
        "still_results_without_pulse_association": [frames[i] for i in sorted(unused)],
        "capture_results_without_yuv_match": [
            frames[i] for i in range(len(frames)) if i not in matched_frame_ids
        ],
        "yuv_images_without_capture_result_match": [
            images[i] for i in range(len(images)) if i not in matched_image_ids
        ],
        "limits": [
            "Overlap is evaluated for the first-row exposure interval reported by Camera2.",
            "A positive software-envelope overlap is compatible with illumination during exposure, not proof of it.",
            "A zero overlap means the recorded helper request/ack envelope did not intersect the first-row exposure.",
            "A bracketed request and matching YUV image prove transaction order and frame identity, not optical output or eye safety.",
            "Even with a REALTIME sensor timestamp, optical turn-on/off latency and rolling-row coverage are not measured.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", default="-",
                        help="probe log file, or - to read stdin (default)")
    args = parser.parse_args()
    try:
        stream = sys.stdin if args.log == "-" else open(args.log, encoding="utf-8")
        try:
            frames, requests, images, pulses = parse_log(stream)
        finally:
            if stream is not sys.stdin:
                stream.close()
    except OSError as exc:
        parser.error(str(exc))
    json.dump(correlate(frames, requests, images, pulses), sys.stdout,
              indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
