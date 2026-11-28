import { Easing, Interactive, Sequence, interpolateColors, spring, useCurrentFrame, useVideoConfig, type InteractiveBaseProps, type InteractiveTransformProps, type InteractivitySchema, type SequenceControls } from "remotion";
import { forwardRef, useImperativeHandle, useMemo, useRef, type ComponentProps } from "react";

// Every timing in remocn is written in frames of a 30 fps timeline: a delay
// of 12, a rise over 20, a spring fed `fps`. Read straight from Remotion,
// those numbers mean something else in a 60 fps composition: a tween runs
// twice as fast, while a spring keeps its length, so a scene does not even
// speed up evenly.
//
// These two hooks stand in for Remotion's and answer on that 30 fps timeline
// whatever rate the composition runs at. At 60 fps the frame goes 0, 0.5, 1,
// 1.5: the scene lasts the same number of seconds and every frame in between
// is a new picture. At 30 fps they return exactly what Remotion does.
//
//   const frame = useSceneFrame();
//   const { fps, width } = useSceneConfig();
//
// What a component hands back to Remotion is still counted in the
// composition's own frames: `from` and `durationInFrames` of a `<Sequence>`,
// the length of a transition. `useCompositionFrames()` converts those.

/** The frame rate remocn timings are written in. */
const SCENE_FPS = 30;

/** `useCurrentFrame()` in 30 fps frames; fractional above 30 fps. */
function useSceneFrame(): number {
  const { fps } = useVideoConfig();
  return (useCurrentFrame() * SCENE_FPS) / fps;
}

/**
 * `useVideoConfig()` on the 30 fps timeline: `fps` is 30 and
 * `durationInFrames` counts 30 fps frames. Size and the rest are untouched.
 */
function useSceneConfig(): ReturnType<typeof useVideoConfig> {
  const config = useVideoConfig();
  return useMemo(
    () => ({
      ...config,
      fps: SCENE_FPS,
      durationInFrames: (config.durationInFrames * SCENE_FPS) / config.fps,
    }),
    [config],
  );
}


// A component's schedule, kept apart from its drawing: which elements the
// animation has (an entry, a word, a finale), when each starts and how long
// it runs. The schedule is a pure function of the props, so it can be read
// without rendering anything, and a `timing` prop can move, trim or stretch
// single elements without touching the code that draws them.
//
//   // timeline.ts, next to the component
//   export const titleTimeline = defineTimeline<TitleElementId, TitleProps>(
//     ({ words = WORDS }, { length }) =>
//       words.map((word, k) => ({
//         id: `word:${k}`,
//         lane: "Words",
//         label: word,
//         start: k * 8,
//         length: 8,
//         follows: k > 0 ? `word:${k - 1}` : undefined,
//         beats: { rise: 12 },
//       })),
//   );
//
//   // index.tsx
//   const tl = useTimeline(titleTimeline, props, length, timing);
//   const word = tl.get("word:0");
//   interpolate(t, [word.start, word.start + word.beat("rise")], [0, 1]);
//
// Every number is in frames of the 30 fps scene timeline, after `delay` and
// `speed`: those still apply to the whole animation, `timing` works inside it.
// Element ids are public API: a saved `timing` refers to them, so an id once
// shipped keeps its meaning.

/** One timed part of an animation, as its schedule lays it out. */
interface TimelineElement<Id extends string = string> {
  /** Stable name a `timing` override refers to: `entry:0`, `finale`. */
  id: Id;
  /** Row the element sits on in a timeline view. */
  lane: string;
  /** What the element shows, for people reading the timeline. */
  label: string;
  /** First frame of the element. */
  start: number;
  /** Frames until the next element of the lane takes over, or the end. */
  length: number;
  /**
   * The element this one comes after. When that element's end moves, this
   * one moves with it, keeping the gap between them.
   */
  follows?: Id;
  /**
   * Named frame counts inside the element, measured from its start: how long
   * a roll takes, when a second part begins. `stretch` scales them.
   */
  beats?: Record<string, number>;
}

/** A change to one element, made from outside the component. */
interface TimingOverride {
  /** New first frame. Wins over the shift from `follows`. */
  start?: number;
  /** New length, trimming or extending the element. Wins over `stretch`. */
  length?: number;
  /** Multiplies the length and every beat: 2 plays the element half as fast. */
  stretch?: number;
  /** Stops following: the element keeps its own start when the one before moves. */
  detach?: boolean;
}

/** Overrides by element id: the `timing` prop of a component. */
type Timing<Id extends string = string> = Partial<
  Record<Id, TimingOverride>
>;

/** A component's schedule: props and the scene length in, elements out. */
type Schedule<Id extends string, Props> = (
  props: Props,
  scene: { length: number },
) => TimelineElement<Id>[];

/** An element after `timing` has been applied. */
interface ResolvedElement<Id extends string = string>
  extends TimelineElement<Id> {
  /** `start + length`. */
  end: number;
  beats: Record<string, number>;
  /** A beat by name, stretched. Throws on a name the schedule didn't set. */
  beat(name: string): number;
  /**
   * 0 → 1 over the element, or over its first `beat` frames when a beat is
   * named. Clamped on both sides.
   */
  progress(frame: number, beat?: string): number;
}

interface ResolvedTimeline<Id extends string = string> {
  /** All elements, in the order the schedule returned them. */
  elements: ResolvedElement<Id>[];
  /** An element by id. Throws on an id the schedule didn't return. */
  get(id: Id): ResolvedElement<Id>;
  /** The elements of one lane, in order. */
  lane(name: string): ResolvedElement<Id>[];
}

/** Declares a schedule. Elements come back in time order. */
function defineTimeline<Id extends string, Props>(
  schedule: Schedule<Id, Props>,
): Schedule<Id, Props> {
  return schedule;
}

/** Applies `timing` to a schedule's elements and carries the `follows` chains. */
function resolve<Id extends string>(
  elements: TimelineElement<Id>[],
  timing: Timing<Id> = {},
): ResolvedTimeline<Id> {
  const byId = new Map<Id, TimelineElement<Id>>(elements.map((e) => [e.id, e]));
  const done = new Map<Id, ResolvedElement<Id>>();
  const visiting = new Set<Id>();

  const place = (element: TimelineElement<Id>): ResolvedElement<Id> => {
    const known = done.get(element.id);
    if (known) return known;
    if (visiting.has(element.id)) {
      throw new Error(`timeline: "${element.id}" follows itself`);
    }
    visiting.add(element.id);

    const override: TimingOverride = timing[element.id] ?? {};
    const stretch = override.stretch ?? 1;
    const beats: Record<string, number> = {};
    for (const [name, frames] of Object.entries(element.beats ?? {})) {
      beats[name] = frames * stretch;
    }

    let start = element.start;
    const leader = element.follows ? byId.get(element.follows) : undefined;
    if (leader && !override.detach) {
      // The leader's end moved by this much; this element moves as far.
      start += place(leader).end - (leader.start + leader.length);
    }
    if (override.start !== undefined) start = override.start;
    const length = override.length ?? element.length * stretch;

    const beat = (name: string) => {
      const frames = beats[name];
      if (frames === undefined) {
        throw new Error(`timeline: "${element.id}" has no beat "${name}"`);
      }
      return frames;
    };
    const resolved: ResolvedElement<Id> = {
      ...element,
      start,
      length,
      end: start + length,
      beats,
      beat,
      progress: (frame, name) => {
        const span = name === undefined ? length : beat(name);
        if (span <= 0) return frame >= start ? 1 : 0;
        return Math.min(1, Math.max(0, (frame - start) / span));
      },
    };
    visiting.delete(element.id);
    done.set(element.id, resolved);
    return resolved;
  };

  const all = elements.map(place);
  return {
    elements: all,
    get: (id) => {
      const element = done.get(id);
      if (!element) throw new Error(`timeline: no element "${id}"`);
      return element;
    },
    lane: (name) => all.filter((e) => e.lane === name),
  };
}

/**
 * The component side: runs the schedule and applies `timing`, once per
 * change of its inputs. `length` is the scene length the schedule fits into,
 * in the same frames the component counts.
 */
function useTimeline<Id extends string, Props>(
  schedule: Schedule<Id, Props>,
  props: Props,
  length: number,
  timing?: Timing<Id>,
): ResolvedTimeline<Id> {
  return useMemo(
    () => resolve(schedule(props, { length }), timing),
    [schedule, props, length, timing],
  );
}

// The dot popping in, the segments launching out of it, the burst spinning,
// assembling and closing into a ring, the ring's anticipation and its exit
// past the frame. Frames on the 30 fps scene timeline, after `speed`; with
// `loop` the schedule repeats every cycle. The ids are public: a saved
// `timing` prop refers to them.

type RadialBurstElementId =
  | "dot"
  | "launch"
  | "spin"
  | "assemble"
  | "close"
  | "ring"
  | "anticipate"
  | "exit";

/** The scene's timing does not depend on its props. */
type RadialBurstTimingProps = object;

/** The ring has completely left the composition by this frame at 30 fps. */
const BURST_LENGTH = 114;

// `dot` pops over its length and shrinks away over `shrink` from `shrinkAt`.
// `launch` shows the segments until the ring takes over: they fade in over
// `fade`, grow over `grow`, the plane tilts over `tilt` and the launch
// spring runs `spring`. `assemble` pulls them onto the ring, curling from
// `curlAt` over `curl`. `exit` throws the ring past the frame, the echoes
// fading from `fadeAt`.
const radialBurstTimeline = defineTimeline<
  RadialBurstElementId,
  RadialBurstTimingProps
>((): TimelineElement<RadialBurstElementId>[] => [
  {
    id: "dot",
    lane: "Dot",
    label: "dot",
    start: 2,
    length: 16,
    beats: { shrinkAt: 16, shrink: 8 },
  },
  {
    id: "launch",
    lane: "Segments",
    label: "launch",
    start: 18,
    length: 66,
    follows: "dot",
    beats: { fade: 5, grow: 18, tilt: 30, spring: 26 },
  },
  {
    id: "spin",
    lane: "Spin",
    label: "spin",
    start: 34,
    length: 50,
    follows: "launch",
  },
  {
    id: "assemble",
    lane: "Segments",
    label: "assemble",
    start: 44,
    length: 32,
    follows: "spin",
    beats: { curlAt: 4, curl: 30 },
  },
  {
    id: "close",
    lane: "Segments",
    label: "close",
    start: 72,
    length: 12,
    follows: "assemble",
  },
  {
    id: "ring",
    lane: "Ring",
    label: "ring",
    start: 84,
    length: BURST_LENGTH - 84,
    follows: "close",
  },
  {
    id: "anticipate",
    lane: "Ring",
    label: "anticipate",
    start: 86,
    length: 10,
    follows: "ring",
  },
  {
    id: "exit",
    lane: "Ring",
    label: "exit",
    start: 96,
    length: BURST_LENGTH - 96,
    follows: "anticipate",
    beats: { fadeAt: 11 },
  },
]);

interface RadialBurstProps {
  /** Number of rounded segments, from 4 to 16. */
  segments?: number;
  /** Burst radius at a 720px reference size. */
  radius?: number;
  /** Segment thickness at a 720px reference size. */
  thickness?: number;
  /** Rotation during assembly, in degrees; negative reverses it. */
  rotation?: number;
  /** Sculptural stretch and tilt, from 0 (classic) to 1.5. */
  intensity?: number;
  /** Curvature of the flying ribbons in degrees. */
  twist?: number;
  /** Number of contour echoes, from 0 to 5. */
  echoes?: number;
  color?: string;
  accentColor?: string;
  backgroundColor?: string;
  speed?: number;
  loop?: boolean;
  className?: string;
  /**
   * Moves, trims or stretches the dot, the launch, the spin, the assembly,
   * the ring and its exit, by the ids in `./timeline`. Frames on the scene
   * timeline, after `speed`.
   */
  timing?: Timing<RadialBurstElementId>;
}

const CYCLE = 120;
const finite = (value: number, fallback: number) =>
  Number.isFinite(value) ? value : fallback;
const clamp = (value: number) => Math.min(1, Math.max(0, value));
const mix = (from: number, to: number, progress: number) =>
  from + (to - from) * progress;
const easeInOut = Easing.bezier(0.65, 0, 0.25, 1);
const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
const progress = (frame: number, start: number, end: number) =>
  clamp((frame - start) / (end - start));

function getRadialBurstState(
  frame: number,
  {
    segments = 8,
    radius = 210,
    thickness = 30,
    rotation = 135,
    intensity = 1,
    loop = false,
    width = 1280,
    height = 720,
  }: Omit<
    RadialBurstProps,
    "color" | "accentColor" | "backgroundColor" | "speed" | "className"
  > & {
    width?: number;
    height?: number;
  } = {},
  tl: ResolvedTimeline<RadialBurstElementId> = resolve(
    radialBurstTimeline({}, { length: CYCLE }),
  ),
) {
  const dot = tl.get("dot");
  const launchEl = tl.get("launch");
  const spin = tl.get("spin");
  const assembleEl = tl.get("assemble");
  const closeEl = tl.get("close");
  const ring = tl.get("ring");
  const anticipateEl = tl.get("anticipate");
  const exitEl = tl.get("exit");
  const curlAt = assembleEl.start + assembleEl.beat("curlAt");
  const w = Math.max(1, finite(width, 1280));
  const h = Math.max(1, finite(height, 720));
  const unit = Math.min(w, h) / 720;
  const time = Math.max(0, finite(frame, 0));
  const local = loop ? time % CYCLE : time;
  const count = Math.round(Math.min(16, Math.max(4, finite(segments, 8))));
  const burstRadius = Math.min(280, Math.max(100, finite(radius, 210))) * unit;
  const stroke = Math.min(60, Math.max(8, finite(thickness, 30))) * unit;
  const ringRadius = burstRadius * 0.68;
  const assemble = easeInOut(progress(local, assembleEl.start, assembleEl.end));
  const curl = easeInOut(
    progress(local, curlAt, curlAt + assembleEl.beat("curl")),
  );
  const close = easeInOut(progress(local, closeEl.start, closeEl.end));
  const anticipate = easeInOut(
    progress(local, anticipateEl.start, anticipateEl.end),
  );
  const exit = progress(local, exitEl.start, exitEl.end) ** 2.6;
  const launch = spring({
    frame: Math.max(0, local - launchEl.start),
    fps: 30,
    durationInFrames: launchEl.beat("spring"),
    config: { damping: 13, stiffness: 170, mass: 0.8 },
  });
  const pop = spring({
    frame: Math.max(0, local - dot.start),
    fps: 30,
    durationInFrames: dot.length,
    config: { damping: 11, stiffness: 180, mass: 0.65 },
  });
  const ringStroke = mix(stroke * 0.8, stroke * 1.1, anticipate);
  const exitStroke = mix(ringStroke, stroke * 2.2, exit);
  // The inner edge, not just the centerline, must pass every corner.
  const clearRadius = Math.hypot(w, h) / 2 + stroke * 2.2 + 2;
  const orbitRadius = mix(
    mix(28 * unit, burstRadius, launch),
    ringRadius,
    assemble,
  );
  const finalRadius = mix(ringRadius, ringRadius * 0.84, anticipate);
  const strength = Math.min(1.5, Math.max(0, finite(intensity, 1)));
  const energy = Math.sin(
    Math.PI * progress(local, launchEl.start, ring.start),
  );
  const tilt =
    easeOut(
      progress(local, launchEl.start, launchEl.start + launchEl.beat("tilt")),
    ) *
    (1 - easeInOut(progress(local, exitEl.start, exitEl.end)));
  const plane = progress(local, launchEl.start, exitEl.end);
  const shrinkAt = dot.start + dot.beat("shrinkAt");

  return {
    frame: local,
    count,
    unit,
    strength,
    energy: Math.max(0, energy) * strength,
    planeScale: 1 - tilt * 0.46 * Math.min(1.5, strength),
    planeAngle: Math.sin(plane * Math.PI * 1.6) * 32 * strength,
    offsetX: Math.sin(Math.PI * plane) * 65 * unit * strength,
    offsetY: -Math.sin(Math.PI * plane) * 32 * unit * strength,
    dotRadius:
      37 *
      unit *
      pop *
      (1 - easeOut(progress(local, shrinkAt, shrinkAt + dot.beat("shrink")))),
    dotSquash:
      1 - Math.sin(Math.PI * progress(local, dot.start, dot.end)) * 0.16,
    showSegments: local >= launchEl.start && local < ring.start,
    showRing: local >= ring.start && local < exitEl.end,
    segmentOpacity: easeOut(
      progress(local, launchEl.start, launchEl.start + launchEl.beat("fade")),
    ),
    radius:
      local < ring.start ? orbitRadius : mix(finalRadius, clearRadius, exit),
    strokeWidth:
      local < ring.start ? mix(stroke, stroke * 0.8, assemble) : exitStroke,
    segmentLength: mix(
      12 * unit,
      Math.min(82 * unit, burstRadius * 0.42),
      easeOut(
        progress(local, launchEl.start, launchEl.start + launchEl.beat("grow")),
      ),
    ),
    curl,
    // Gaps close with a tiny overlap to prevent raster seams at the weld.
    arcAngle: ((Math.PI * 2) / count) * mix(0.62, 1.002, close),
    rotation:
      finite(rotation, 135) * easeInOut(progress(local, spin.start, spin.end)),
  };
}

/** A straight rounded spoke curls continuously into a circular arc. */
function getSegmentPoints({
  radius,
  segmentLength,
  arcAngle,
  curl,
}: Pick<
  ReturnType<typeof getRadialBurstState>,
  "radius" | "segmentLength" | "arcAngle" | "curl"
>) {
  const half = arcAngle / 2;
  const x = radius * Math.cos(half);
  const y = radius * Math.sin(half);
  const tangent = (4 / 3) * Math.tan(arcAngle / 4) * radius;
  const arc = [
    [x, -y],
    [x + tangent * Math.sin(half), -y + tangent * Math.cos(half)],
    [x + tangent * Math.sin(half), y - tangent * Math.cos(half)],
    [x, y],
  ];
  const angle = (curl * Math.PI) / 2;
  return [-0.5, -1 / 6, 1 / 6, 0.5].map((offset, index) => {
    const px = radius + segmentLength * offset * Math.cos(angle);
    const py = segmentLength * offset * Math.sin(angle);
    return [mix(px, arc[index][0], curl), mix(py, arc[index][1], curl)];
  });
}

function getRadialBurstSegmentPath(
  state: Parameters<typeof getSegmentPoints>[0],
) {
  const points = getSegmentPoints(state).map((point) =>
    point.map((value) => value.toFixed(3)).join(" "),
  );
  return `M ${points[0]} C ${points[1]} ${points[2]} ${points[3]}`;
}

/** Sample a bent centerline and its normals to make a tapered, filled ribbon. */
function getRadialBurstRibbonPath(
  state: ReturnType<typeof getRadialBurstState>,
  index: number,
  twist = 110,
) {
  const energy = state.energy;
  const points = getSegmentPoints({
    ...state,
    radius: state.radius * (1 + Math.sin(index * 2.4) * energy * 0.15),
    segmentLength: state.segmentLength * (1 + energy * 2.8),
  });
  const bend =
    (Math.min(180, Math.max(-180, finite(twist, 110))) / 110) *
    energy *
    145 *
    state.unit;
  points[1][1] += bend * 0.55;
  points[2][1] += bend;
  // Carry the tip with the bend so the centerline does not double back into
  // a hairpin while the ribbon transitions from a spoke to an arc.
  points[3][1] += bend * 1.25;
  points[2][0] += energy * 38 * state.unit;
  const upper: string[] = [];
  const lower: string[] = [];
  const format = (x: number, y: number) => `${x.toFixed(3)} ${y.toFixed(3)}`;
  let firstWidth = 0;
  let lastWidth = 0;
  for (let sample = 0; sample <= 36; sample++) {
    const t = sample / 36;
    const q = 1 - t;
    const x =
      q ** 3 * points[0][0] +
      3 * q * q * t * points[1][0] +
      3 * q * t * t * points[2][0] +
      t ** 3 * points[3][0];
    const y =
      q ** 3 * points[0][1] +
      3 * q * q * t * points[1][1] +
      3 * q * t * t * points[2][1] +
      t ** 3 * points[3][1];
    const dx =
      3 * q * q * (points[1][0] - points[0][0]) +
      6 * q * t * (points[2][0] - points[1][0]) +
      3 * t * t * (points[3][0] - points[2][0]);
    const dy =
      3 * q * q * (points[1][1] - points[0][1]) +
      6 * q * t * (points[2][1] - points[1][1]) +
      3 * t * t * (points[3][1] - points[2][1]);
    const length = Math.max(0.001, Math.hypot(dx, dy));
    const ddx =
      6 * q * (points[2][0] - 2 * points[1][0] + points[0][0]) +
      6 * t * (points[3][0] - 2 * points[2][0] + points[1][0]);
    const ddy =
      6 * q * (points[2][1] - 2 * points[1][1] + points[0][1]) +
      6 * t * (points[3][1] - 2 * points[2][1] + points[1][1]);
    const curvature = Math.abs(dx * ddy - dy * ddx) / length ** 3;
    const swell = Math.sin(Math.PI * t) ** 1.4;
    // Offset curves fold back on themselves when their width exceeds the
    // bend radius. Limit the width locally to keep tight curls smooth.
    const halfWidth = Math.min(
      (state.strokeWidth / 2) * (1 + energy * (2.4 * swell - 0.65 * t)),
      0.72 / Math.max(curvature, 0.00001),
    );
    if (sample === 0) firstWidth = halfWidth;
    if (sample === 36) lastWidth = halfWidth;
    upper.push(
      format(x - (dy / length) * halfWidth, y + (dx / length) * halfWidth),
    );
    lower.push(
      format(x + (dy / length) * halfWidth, y - (dx / length) * halfWidth),
    );
  }
  return `M ${upper.join(" L ")} A ${lastWidth} ${lastWidth} 0 0 0 ${lower[36]} L ${lower.slice(0, -1).reverse().join(" L ")} A ${firstWidth} ${firstWidth} 0 0 0 ${upper[0]} Z`;
}

function RadialBurstBase(props: RadialBurstProps) {
  const {
    segments = 8,
    radius = 210,
    thickness = 30,
    rotation = 135,
    intensity = 1,
    twist = 110,
    echoes = 3,
    color = "#ffffff",
    accentColor = "#f4e4a7",
    backgroundColor = "#a800b7",
    speed = 1,
    loop = false,
    className,
    timing,
  } = props;
  const frame = useSceneFrame();
  const { width, height, fps, durationInFrames } = useSceneConfig();
  const rate = Math.max(0, finite(speed, 1));
  const time = frame * (30 / fps) * rate;
  const tl = useTimeline(
    radialBurstTimeline,
    props,
    durationInFrames * rate,
    timing,
  );
  const launchEl = tl.get("launch");
  const exitEl = tl.get("exit");
  const options = {
    segments,
    radius,
    thickness,
    rotation,
    intensity,
    loop,
    width,
    height,
  };
  const state = getRadialBurstState(time, options, tl);
  const path = getRadialBurstSegmentPath(state);
  const echoCount = Math.round(Math.min(5, Math.max(0, finite(echoes, 3))));
  const plane = (pose: typeof state) =>
    `translate(${pose.offsetX} ${pose.offsetY}) rotate(${pose.planeAngle}) scale(1 ${pose.planeScale})`;
  const ribbons = (pose: typeof state, outline: boolean) =>
    Array.from({ length: pose.count }, (_, index) => (
      <path
        key={index}
        d={getRadialBurstRibbonPath(pose, index, twist)}
        transform={`rotate(${(index * 360) / pose.count + pose.rotation - 90 + Math.sin(index * 1.7) * pose.energy * 16})`}
        fill={
          outline
            ? "none"
            : index % 3 === 0
              ? interpolateColors(
                  clamp(pose.energy),
                  [0, 1],
                  [color, accentColor],
                )
              : color
        }
        stroke={outline ? color : "none"}
        strokeWidth={1.5 * pose.unit}
      />
    ));

  return (
    <div
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        backgroundColor,
      }}
    >
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Geometric radial burst"
        style={{ display: "block" }}
      >
        <g transform={`translate(${width / 2} ${height / 2})`}>
          {state.strength > 0 &&
          state.frame >= launchEl.start &&
          state.frame < exitEl.end
            ? Array.from({ length: echoCount }, (_, index) => {
                const lag = (echoCount - index) * 2.2;
                const echo = getRadialBurstState(
                  Math.max(launchEl.start, state.frame - lag),
                  { ...options, loop: false },
                  tl,
                );
                const opacity =
                  0.36 *
                  (1 - index / (echoCount + 1)) *
                  Math.min(1, state.strength) *
                  (1 -
                    easeOut(
                      progress(
                        state.frame,
                        exitEl.start + exitEl.beat("fadeAt"),
                        exitEl.end,
                      ),
                    ));
                return (
                  <g key={index} transform={plane(echo)} opacity={opacity}>
                    {echo.showSegments ? (
                      ribbons(echo, true)
                    ) : echo.showRing ? (
                      <circle
                        r={echo.radius}
                        fill="none"
                        stroke={index % 2 ? color : accentColor}
                        strokeWidth={echo.strokeWidth * (0.22 + index * 0.07)}
                      />
                    ) : null}
                  </g>
                );
              })
            : null}
          <g transform={plane(state)}>
            {state.dotRadius > 0.001 ? (
              <circle
                r={state.dotRadius}
                fill={color}
                transform={`scale(${1 / state.dotSquash} ${state.dotSquash})`}
              />
            ) : null}
            {state.showSegments && state.strength > 0 ? (
              <g opacity={state.segmentOpacity}>{ribbons(state, false)}</g>
            ) : state.showSegments ? (
              <g
                fill="none"
                stroke={color}
                strokeWidth={state.strokeWidth}
                strokeLinecap="round"
                opacity={state.segmentOpacity}
                transform={`rotate(${state.rotation - 90})`}
              >
                {Array.from({ length: state.count }, (_, index) => (
                  <path
                    key={index}
                    d={path}
                    transform={`rotate(${(index * 360) / state.count})`}
                  />
                ))}
              </g>
            ) : null}
            {state.showRing ? (
              <circle
                r={state.radius}
                fill="none"
                stroke={color}
                strokeWidth={state.strokeWidth}
              />
            ) : null}
          </g>
        </g>
      </svg>
    </div>
  );
}

const elementSchema = {
  ...Interactive.baseSchema,
  segments: {
    type: "number",
    default: 8,
    min: 4,
    max: 16,
    step: 1,
    description: "Segments",
    hiddenFromList: false,
  },
  radius: {
    type: "number",
    default: 210,
    min: 100,
    max: 280,
    step: 5,
    description: "Burst radius",
    hiddenFromList: false,
  },
  thickness: {
    type: "number",
    default: 30,
    min: 8,
    max: 60,
    step: 1,
    description: "Thickness",
    hiddenFromList: false,
  },
  rotation: {
    type: "number",
    default: 135,
    min: -360,
    max: 360,
    step: 15,
    description: "Rotation",
    hiddenFromList: false,
  },
  intensity: {
    type: "number",
    default: 1,
    min: 0,
    max: 1.5,
    step: 0.1,
    description: "Intensity",
    hiddenFromList: false,
  },
  twist: {
    type: "number",
    default: 110,
    min: -180,
    max: 180,
    step: 10,
    description: "Ribbon twist",
    hiddenFromList: false,
  },
  echoes: {
    type: "number",
    default: 3,
    min: 0,
    max: 5,
    step: 1,
    description: "Contour echoes",
    hiddenFromList: false,
  },
  color: {
    type: "color",
    default: "#ffffff",
    description: "Shape color",
  },
  accentColor: {
    type: "color",
    default: "#f4e4a7",
    description: "Accent color",
  },
  backgroundColor: {
    type: "color",
    default: "#a800b7",
    description: "Background",
  },
  loop: {
    type: "boolean",
    default: false,
    description: "Loop animation",
  },
  speed: {
    type: "number",
    default: 1,
    min: 0.25,
    max: 4,
    step: 0.25,
    description: "Speed",
    hiddenFromList: false,
  },
  ...Interactive.transformSchema,
} as const satisfies InteractivitySchema;

const ELEMENT_PROP_KEYS = new Set(["segments","radius","thickness","rotation","intensity","twist","echoes","color","accentColor","backgroundColor","loop","speed"]);

const ELEMENT_PROP_DEFAULTS: Record<string, unknown> = {
  segments: 8,
  radius: 210,
  thickness: 30,
  rotation: 135,
  intensity: 1,
  twist: 110,
  echoes: 3,
  color: "#ffffff",
  accentColor: "#f4e4a7",
  backgroundColor: "#a800b7",
  loop: false,
  speed: 1,
};

type RadialBurstElementProps = InteractiveBaseProps &
  InteractiveTransformProps &
  ComponentProps<typeof RadialBurstBase>;

const RadialBurstInner = forwardRef<
  HTMLDivElement,
  RadialBurstElementProps & { readonly controls: SequenceControls | undefined }
>(({ controls, name, style, ...rest }, ref) => {
  const outlineRef = useRef<HTMLDivElement>(null);
  useImperativeHandle(ref, () => outlineRef.current as HTMLDivElement, []);
  const componentProps: Record<string, unknown> = { ...ELEMENT_PROP_DEFAULTS };
  const sequenceProps: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(rest)) {
    if (ELEMENT_PROP_KEYS.has(key)) {
      if (value !== undefined) componentProps[key] = value;
    } else {
      sequenceProps[key] = value;
    }
  }
  return (
    <Sequence
      layout="none"
      {...sequenceProps}
      controls={controls}
      name={name ?? "<RadialBurst>"}
      outlineRef={outlineRef}
    >
      <div
        ref={outlineRef}
        style={{
          position: "relative",
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          ...style,
        }}
      >
        <RadialBurstBase
          {...(componentProps as unknown as ComponentProps<typeof RadialBurstBase>)}
        />
      </div>
    </Sequence>
  );
});

export const RadialBurst = Interactive.withSchema({
  Component: RadialBurstInner,
  componentName: "<RadialBurst>",
  componentIdentity: null,
  schema: elementSchema,
  supportsEffects: false,
});
