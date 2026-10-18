#pragma once
// The manual "look" controls, and the declaration of eye_render().
//
// Listed under `esphome: includes:` in BOTH configs so this file is copied into
// src/ and reachable from main.cpp and from eye-render.cpp alike. That is the
// whole reason it exists: the animation state used to be declared by hand in
// each config's display lambda, where a swapped argument still compiled because
// the declaration carried types only. One declaration here cannot drift from the
// definition, and the lambdas shrink to a call.
//
// See eye-render.cpp for how DEMO gates every field below.

namespace eye {

// Everything the renderer needs to know about the manual look, in one struct.
//
// All floats, deliberately: these arrive from ESPHome `number` entities whose
// range and step are a UI convenience, not a guarantee. The renderer re-clamps
// what it must (see PUPIL_LO / PUPIL_HI in eye-render.cpp) because a stray
// automation writing a global must not be able to break the ellipse test.
struct EyeLook {
  // Non-zero -> the authored performance: random saccades, the presence
  // response, and every other field here IGNORED. Zero -> the eye holds the
  // gaze, yaw and pitch say, presence is ignored, and the tremor still runs.
  float demo;
  float yaw;        // degrees, clamped to the gaze limits by the caller
  float pitch;      // degrees
  float jitter;     // degrees of tremor amplitude
  // Iris HUE in degrees, absolute, wrapping. NOT RGB: the stroma fibres and the
  // crypts are separate authored colour pairs, so an RGB control left them at
  // their tuned green on a blue iris. Rotating hue turns all three together and
  // keeps each one's own saturation and value, which is the contrast that makes
  // an iris read as an iris. 130.3 is the authored IRIS_REST green.
  float hue;
  float pupil_w;    // fraction of the iris radius
  float pupil_h;    // fraction of the iris radius
  float vein_tint;  // 0..1 coverage scale
};

}  // namespace eye

// The animation state lives in eye-globals.yaml, which ESPHome emits into
// main.cpp where a separate translation unit cannot see it. Hence the pointers.
// The body rebinds them to local references so it reads them as plain locals.
void eye_render(esphome::display::Display *itp,
                float *yaw_p, float *pitch_p,
                float *yaw_t_p, float *pitch_t_p,
                float *yaw_s_p, float *pitch_s_p,
                int *gmove_p, int *ghold_p, int *frame_p,
                int *presence_p, float *pres_f_p,
                int *pres_hold_p, int *pres_seen_p,
                const eye::EyeLook &look);