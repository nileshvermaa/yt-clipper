"""Stage 6: single-pass FFmpeg render: trim -> follow subject -> 9:16 -> captions -> H.264.

Best path: read the clip's range straight from the 4K stream, decode on NVDEC, crop+scale on the
GPU (scale_cuda), burn captions at 1080x1920, encode on NVENC. If a step fails it falls back:
4K+GPU filters -> 4K+CPU filters -> local 1080p copy.
"""
import shutil
import subprocess
from pathlib import Path

import cv2

from . import captions, config, download, reframe


def check_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found on PATH. Install: winget install Gyan.FFmpeg")


def _src_fps(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.release()
    return fps


def render(meta, segments, clip):
    cdir = Path(meta["workdir"]) / f"clip{clip['n']}"
    cdir.mkdir(exist_ok=True)
    if (cdir / "short.mp4").exists():
        return cdir / "short.mp4"

    def build_captions(layout):  # called once the layout is known, so captions can sit on the seam
        captions.build(segments, clip, meta["channel"], cdir / "subs.ass", cap_y=layout["cap_y"] if layout else None)

    return render_segment(meta, cdir, clip["start"], clip["end"], tag=f"clip{clip['n']}", on_layout=build_captions)


def source_fps(meta):
    """Frame rate the render will use for this video (before the OUT_FPS cap)."""
    stream = download.stream_inputs(meta, "vp09") or download.stream_inputs(meta, "av01")
    return stream["fps"] if stream else _src_fps(Path(meta["source"]))


def render_segment(meta, cdir, start, end, tag="segment", out_fps=None, on_layout=None):
    """Render [start, end] of meta's video to cdir/short.mp4, burning in cdir/subs.ass.

    on_layout(layout_or_None) is called once the framing is decided and must write subs.ass.
    """
    out = cdir / "short.mp4"
    local = Path(meta["source"]).resolve()
    framing = config.FRAMING
    frames, fw_, fh_ = reframe.sample(local, start, end)  # decoded once, shared by every analysis step
    layout = reframe.detect_reaction(local, start, end, frames, (fw_, fh_))  # facecam + screen recording?
    if layout:
        crop_w, path, W, used = None, None, layout["W"], "reaction"
    elif framing == "blur":
        crop_w, path, W, used = None, None, None, "blur"
    else:
        crop_w, path, W, used = reframe.crop_path(local, start, end, framing, frames, (fw_, fh_))
    del frames
    if on_layout:
        on_layout(layout)

    vp9, av1 = download.stream_inputs(meta, "vp09"), download.stream_inputs(meta, "av01")
    first = vp9 or av1
    if out_fps is None:
        fps = _src_fps(local) if not first else first["fps"]
        out_fps = min(60, round(fps)) if config.OUT_FPS == "auto" else int(config.OUT_FPS)

    # most to least preferred (lower CPU first):
    #  vulkan = AV1 decoded on the GPU, frames never leave it until the final 1080x1920 picture
    #  gpu    = VP9 decoded by NVDEC, crop/scale by libplacebo      cpu = same decode, CPU crop/scale
    def stream_rungs(vp9, av1):
        rungs = []
        if config.GPU_FILTERS and _has_vulkan():
            if av1:
                rungs.append((av1, "vulkan"))
            if vp9:
                rungs.append((vp9, "gpu"))
        if vp9 or av1:
            rungs.append((vp9 or av1, "cpu"))
        return rungs

    # stream rungs twice (the second time with freshly looked-up links, in case YouTube refused the first
    # ones with a transient 403), then the local 1080p copy
    def ladder():  # generator: later rungs are only prepared if the earlier ones fail
        first_rungs = stream_rungs(vp9, av1)
        yield from first_rungs
        if first_rungs:
            download._stream_cache.pop(meta["id"], None)
            yield from stream_rungs(download.stream_inputs(meta, "vp09"), download.stream_inputs(meta, "av01"))
        yield None, "cpu"

    last = None
    for stream, mode in ladder():
        src = f"{stream['codec']} {stream['height']}p" if stream else "local 1080p"
        for attempt in range(3):  # a truncated network read is checked for and redone
            try:
                _run(cdir, start, end, local, stream, crop_w, path, W, used, out_fps, layout, mode)
            except subprocess.CalledProcessError as e:
                last = e
                break
            if _complete(out, end - start):
                print(f"  {tag}: framing={used} source={src} {out_fps}fps filters={mode}")
                return out
            print(f"  {tag}: output was cut short, retrying")
            out.unlink(missing_ok=True)
        print(f"  render via {src}/{mode} failed, trying next")
    raise last or RuntimeError(f"{tag}: could not render a complete clip")


def _pan_expr(path, k, max_x):
    """Time-based crop_x for ffmpeg: linear pan between the tracked points (libplacebo evaluates t per frame)."""
    pts = [(t, min(max(int(round(x * k)), 0), max_x)) for t, x in path]
    expr = str(pts[-1][1])
    for (t0, x0), (t1, x1) in reversed(list(zip(pts, pts[1:]))):
        if t1 <= t0:
            continue
        seg = str(x0) if x0 == x1 else f"lerp({x0},{x1},(t-{t0})/{round(t1 - t0, 3)})"
        expr = f"if(lt(t,{t1}),{seg},{expr})"
    return expr


def _complete(path, want):
    """True if video and audio both last (almost) the full requested length."""
    def dur(sel):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", sel, "-show_entries", "stream=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        try:
            return float(r.stdout.strip().split()[0])
        except (ValueError, IndexError):
            return 0.0
    v, a = dur("v:0"), dur("a:0")
    return v >= want - 0.5 and a >= want - 0.5 and abs(v - a) < 0.3


def _pl(w, h, crop=None, down=False):
    """libplacebo (Vulkan) scale, optionally cropping first. crop = (x, y, w, h) values or ffmpeg expressions.
    down=True: the input is Vulkan frames, so bring the (small) result back to system memory."""
    c = "" if crop is None else ":crop_x={0}:crop_y={1}:crop_w={2}:crop_h={3}".format(*[f"'{v}'" for v in crop])
    d = ",hwdownload,format=yuv420p" if down else ""
    return f"libplacebo=w={w}:h={h}{c}:downscaler=lanczos:upscaler=ewa_lanczos:format=yuv420p{d}"


def _run(cdir, start, end, local, stream, crop_w, path, W, used, out_fps, layout=None, mode="cpu"):
    gpu = mode != "cpu"
    dn = mode == "vulkan"
    t = str(config.CPU_THREADS)
    nvenc = config.USE_GPU_ENCODE and _has_nvenc()
    # Relative filter paths (cwd=cdir) avoid Windows drive-letter escaping issues in filtergraphs.
    fonts = Path(config.FONTS_DIR).resolve().as_posix().replace(":", "\\:")
    ass = f"ass=subs.ass:fontsdir='{fonts}'"

    if stream:
        sw, sh = stream["width"], stream["height"]
    else:
        cap = cv2.VideoCapture(str(local))
        sw, sh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

    if used == "reaction":
        # screen-recorded commentary: main content on top, facecam below, blurred backdrop, no taskbar/chat
        k = sw / layout["W"]
        s = lambda box: tuple(int(round(v * k)) // 2 * 2 for v in box)
        ctx, cty, ctw, cth = s(layout["content"])
        cax, cay, caw, cah = s(layout["cam"])
        _, y1, ow, och = layout["out_content"]
        fx, fy, fw, fh = layout["out_cam"]
        if gpu:
            # backdrop: tiny cover-fit crop on the GPU, blur at that tiny size (cheap), scale back up on the GPU
            vf = (f"split=3[s0][s1][s2];"
                  f"[s0]{_pl(108, 192, ('(iw-cw)/2', 0, 'ih*9/16', 'ih'), dn)},boxblur=3:1[b0];"
                  f"[b0]{_pl(config.OUT_W, config.OUT_H)}[bg];"
                  f"[s1]{_pl(ow, och, (ctx, cty, ctw, cth), dn)}[ct];"
                  f"[s2]{_pl(fw, fh, (cax, cay, caw, cah), dn)}[fc];"
                  f"[bg][ct]overlay=0:{y1}[o1];[o1][fc]overlay={fx}:{fy},setsar=1,{ass}")
        else:
            vf = (f"split=3[s0][s1][s2];"
                  f"[s0]scale=135:240:force_original_aspect_ratio=increase,crop=135:240,"
                  f"scale={config.OUT_W}:{config.OUT_H}:flags=bilinear,boxblur=14:2[bg];"
                  f"[s1]crop={ctw}:{cth}:{ctx}:{cty},scale={ow}:{och}:flags=bicubic[ct];"
                  f"[s2]crop={caw}:{cah}:{cax}:{cay},scale={fw}:{fh}:flags=bicubic[fc];"
                  f"[bg][ct]overlay=0:{y1}[o1];[o1][fc]overlay={fx}:{fy},setsar=1,{ass}")
    elif used == "blur":
        # whole 16:9 frame in the middle, blurred zoomed copy behind it: nothing is ever cropped out
        if gpu:
            fgh = int(round(config.OUT_W * sh / sw)) // 2 * 2
            vf = (f"split[a][b];"
                  f"[a]{_pl(108, 192, ('(iw-cw)/2', 0, 'ih*9/16', 'ih'), dn)},boxblur=3:1[b0];[b0]{_pl(config.OUT_W, config.OUT_H)}[bg];"
                  f"[b]{_pl(config.OUT_W, fgh, None, dn)}[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,{ass}")
        else:
            vf = (f"split[a][b];[a]scale={config.OUT_W}:{config.OUT_H}:force_original_aspect_ratio=increase,"
                  f"crop={config.OUT_W}:{config.OUT_H},boxblur=40:6[bg];[b]scale={config.OUT_W}:-2[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,{ass}")
    else:
        k = sw / W  # analysis pixels -> render-source pixels
        cw = int(sh * 9 / 16) // 2 * 2
        if gpu:
            # one libplacebo pass: crop (following the tracked path over time) + Lanczos scale, all on the GPU
            vf = (f"{_pl(config.OUT_W, config.OUT_H, (_pan_expr(path, k, sw - cw), 0, cw, sh), dn)},setsar=1,{ass}")
        else:
            reframe.write_sendcmd(path, cdir / "crop.cmd", k)
            x0 = int(round(path[0][1] * k))
            vf = (f"sendcmd=f=crop.cmd,crop=w={cw}:h={sh}:x={x0}:y=0,"
                  f"scale={config.OUT_W}:{config.OUT_H}:flags=bicubic,setsar=1,{ass}")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-threads", t,
           "-filter_threads", t, "-filter_complex_threads", t]
    if mode == "vulkan":  # decode on Vulkan too, so 4K frames stay in GPU memory all the way to libplacebo
        hw = ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk", "-hwaccel", "vulkan",
              "-hwaccel_output_format", "vulkan"]
    elif gpu:  # NVDEC decode, 4K frames come to system memory, libplacebo uploads them again
        cmd += ["-init_hw_device", "vulkan"]
        hw = ["-hwaccel", "cuda"]
    else:
        hw = ["-hwaccel", "cuda"]
    seek = ["-ss", f"{start:.2f}", "-to", f"{end:.2f}"]
    # reconnect: a dropped TLS read used to silently truncate the audio
    net = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "4"]
    if stream:
        cmd += hw + net + ["-headers", stream["v_hdr"]] + seek + ["-i", stream["v"]]
        if stream["a"]:
            cmd += net + ["-headers", stream["a_hdr"]] + seek + ["-i", stream["a"]]
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a?"]
    else:
        cmd += (hw if nvenc else []) + seek + ["-i", str(local)]
    cmd += ["-vf", vf]
    if nvenc:
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0", "-profile:v", "high"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", config.CRF]
    cmd += ["-pix_fmt", "yuv420p", "-r", str(out_fps), "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "short.mp4"]
    subprocess.run(cmd, cwd=cdir, check=True)


_VULKAN = None


def _has_vulkan():
    global _VULKAN
    if _VULKAN is None:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
        _VULKAN = "libplacebo" in r.stdout
    return _VULKAN


_NVENC = None


def _has_nvenc():
    global _NVENC
    if _NVENC is None:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
        _NVENC = "h264_nvenc" in r.stdout
    return _NVENC
