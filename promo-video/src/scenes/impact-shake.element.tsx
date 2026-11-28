import React, { forwardRef, useEffect, useId, useImperativeHandle, useLayoutEffect, useMemo, useRef, type ComponentProps } from "react";
import { AbsoluteFill, Easing, Interactive, Sequence, interpolate, random, spring, useCurrentFrame, useVideoConfig, type InteractiveBaseProps, type InteractiveTransformProps, type InteractivitySchema, type SequenceControls } from "remotion";

// Chrome parks a glyph raster on a whole pixel vertically for as long as the
// matrix that carries it is axis-aligned, so text under a slow transform
// clicks along pixel by pixel. A lean too small to see takes it off that grid.
//
// A transform that carries text is marked, and told when it moves:
//
//   const glide = useGlide();
//   transform: `scale(${s})${glide(moving)}`
//
// The mark changes nothing by itself. After every frame the blocks of text
// under a marked transform get the lean: each about its own centre, and each
// by no more than its size on the screen needs. A card, a hairline or an image
// is fine under a transform as it is, so they stay level.
//
// Text leans while its transform moves, and it keeps the lean at rest when it
// rests off the pixel grid (a scene shown smaller in a player, a camera that
// holds at 1.03): dropping the lean there would snap it to the nearest pixel,
// up to half a pixel in one frame, and picking it up would snap it back. Text
// that rests on the grid loses the lean without moving, so a scene at rest at
// full size is drawn exactly as it would be without any of this.

/**
 * Returns `glide(moving)`: append it to a transform that carries text, with
 * `moving` true on the frames where that transform changes.
 *
 * Everything else lives inside this one closure: the build of Studio
 * elements pastes this file whole into the component that uses it, where a
 * second `LEAN` or `lean` at the top level would collide.
 */
const useGlide = (() => {
  /** What `glide(false)` adds to a transform: an identity matrix, to find it by. */
  const AT_REST = " matrix(1, 0, 0, 1, 0, 0)";
  /** `glide(true)` adds it twice. */
  const MOVING = AT_REST + AT_REST;
  const MARKED = `[style*="${AT_REST.trim()}"]`;
  // Text leaves the grid once the matrix leans x into y by half of 1/1024 in
  // device pixels (Skia rounds the glyph matrix to 1/1024). A fifth over it.
  const LEAN = 0.6 / 1024;
  // Past this the text is a speck on the screen; it is left alone.
  const STEEPEST = 5;
  // How far from a whole pixel text may rest and still count as on the grid:
  // the jump it makes when the lean goes is no bigger than this.
  const ON_GRID = 0.05;

  /** The linear part of a 2D matrix: x' = a·x + c·y, y' = b·x + d·y. */
  type Lin = [a: number, b: number, c: number, d: number];
  const LEVEL: Lin = [1, 0, 0, 1];
  const times = (m: Lin, n: Lin): Lin => [
    m[0] * n[0] + m[2] * n[1],
    m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3],
  ];
  const turned = (degrees: number): Lin => {
    const t = (degrees * Math.PI) / 180;
    return [Math.cos(t), Math.sin(t), -Math.sin(t), Math.cos(t)];
  };
  const offWhole = (n: number) => Math.abs(n - Math.round(n));

  type Block = HTMLElement | SVGTextElement | SVGSVGElement;
  let leant: Block[] = [];
  // Fonts arrive after the first pass and change what is laid out where, with
  // no render to follow: a block or a marked element that changes size is read
  // again before the frame is painted.
  let watcher: ResizeObserver | undefined;
  const watched = new WeakSet<Element>();
  const watch = (el: Element) => {
    if (watched.has(el)) return;
    watched.add(el);
    watcher ??= new ResizeObserver(() => lean());
    watcher.observe(el);
  };

  const depthOf = (el: Element) => {
    let depth = 0;
    for (let up = el.parentElement; up; up = up.parentElement) depth += 1;
    return depth;
  };

  /** The nearest box around a text node that a transform applies to. */
  const blockOf = (node: Node): Block | null => {
    for (let el = node.parentElement; el; el = el.parentElement) {
      if (el instanceof SVGElement) {
        const text = el.closest("text");
        if (!(text instanceof SVGTextElement)) return null;
        // Text that only shapes a mask or a clip is not drawn where it stands
        // and cannot turn by itself: its whole drawing leans for it.
        if (!text.closest("defs, mask, clipPath, pattern, symbol, marker"))
          return text;
        let drawing = text.ownerSVGElement;
        while (drawing?.ownerSVGElement) drawing = drawing.ownerSVGElement;
        return drawing;
      }
      if (!(el instanceof HTMLElement)) continue;
      const { display } = getComputedStyle(el);
      if (display !== "inline" && display !== "contents") return el;
    }
    return null;
  };

  /** One pass over the page: what every element's own transforms do. */
  function reader(given: Map<Element, number>) {
    type Own = {
      /** `scale` and `transform`, without the `rotate` property. */
      lin: Lin;
      /** `rotate`, in degrees: a lean given in this pass, or the scene's own. */
      turn: number;
      /** How far down it is moved, and by what whole factor it is scaled from
       * its top left corner; null when it does anything else. */
      carry: { dy: number; k: number } | null;
    };
    const lens = new Map<Element, boolean>();
    /** Whether an element shows its children in perspective. */
    const lensOn = (el: Element | null): boolean => {
      if (!el) return false;
      const seen = lens.get(el);
      if (seen !== undefined) return seen;
      const style = getComputedStyle(el);
      const result =
        style.perspective !== "none" ||
        (style.transformStyle === "preserve-3d" && lensOn(el.parentElement));
      lens.set(el, result);
      return result;
    };
    const own = new Map<Element, Own | null>();
    const ownOf = (el: Element): Own | null => {
      const seen = own.get(el);
      if (seen !== undefined) return seen;
      const style = getComputedStyle(el);
      const m = new DOMMatrixReadOnly(
        style.transform === "none" ? "" : style.transform,
      );
      const scale = style.scale === "none" ? [] : style.scale.split(" ");
      const sx = scale.length ? Number.parseFloat(scale[0]) : 1;
      const sy = scale.length > 1 ? Number.parseFloat(scale[1]) : sx;
      const rotate = style.rotate === "none" ? [] : style.rotate.split(" ");
      let result: Own | null = null;
      // Seen in perspective, text is drawn on a layer of its own: not ours. A
      // turn out of the plane without perspective lands flat on the screen,
      // and text under it snaps like any other.
      // A push along z alone, or a half turn, leaves it flat even under a lens.
      const inPerspective =
        Math.max(Math.abs(m.m14), Math.abs(m.m24), Math.abs(m.m34)) > 1e-9 ||
        (Math.max(
          Math.abs(m.m13),
          Math.abs(m.m31),
          Math.abs(m.m23),
          Math.abs(m.m32),
        ) > 1e-6 &&
          lensOn(el.parentElement));
      if (!inPerspective && rotate.length < 2) {
        // The `scale` property acts on what `transform` has produced.
        const lin: Lin = [m.a * sx, m.b * sy, m.c * sx, m.d * sy];
        const moved =
          style.translate === "none"
            ? 0
            : (style.translate.split(" ")[1] ?? "0px");
        const k = Math.round(lin[0]);
        const whole =
          m.is2D &&
          k >= 1 &&
          Math.abs(lin[0] - k) < 1e-4 &&
          Math.abs(lin[3] - k) < 1e-4 &&
          Math.abs(lin[1]) < 1e-5 &&
          Math.abs(lin[2]) < 1e-5 &&
          rotate.length === 0 &&
          (moved === 0 || moved.endsWith("px")) &&
          // Scaled about its corner, a box stays where layout put it.
          (k === 1 || /^0(px)? 0(px)?/.test(style.transformOrigin));
        result = {
          lin,
          turn: rotate.length ? Number.parseFloat(rotate[0]) : 0,
          carry: whole
            ? { dy: sy * m.f + (moved === 0 ? 0 : Number.parseFloat(moved)), k }
            : null,
        };
      }
      own.set(el, result);
      return result;
    };
    const down = new Map<Element, Lin | null>();
    /** Everything from the page down to and including this element. */
    const linDown = (el: Element | null): Lin | null => {
      if (!el) return LEVEL;
      const seen = down.get(el);
      if (seen !== undefined) return seen;
      const above = linDown(el.parentElement);
      const mine = above && ownOf(el);
      const result =
        above && mine
          ? times(times(above, turned(given.get(el) ?? mine.turn)), mine.lin)
          : null;
      down.set(el, result);
      return result;
    };
    const carried = new Map<Element, { dy: number; k: number } | null>();
    const carryDown = (
      el: Element | null,
    ): { dy: number; k: number } | null => {
      if (!el) return { dy: 0, k: 1 };
      const seen = carried.get(el);
      if (seen !== undefined) return seen;
      const above = carryDown(el.parentElement);
      const mine = above && !given.has(el) ? ownOf(el)?.carry : null;
      const result =
        above && mine
          ? { dy: above.dy + above.k * mine.dy, k: above.k * mine.k }
          : null;
      carried.set(el, result);
      return result;
    };
    return { ownOf, linDown, carryDown };
  }

  /**
   * Whether text in an SVG rests on the grid: it is placed wherever it is told
   * to, so only when it is shown one to one and its baseline happens to land on
   * a whole pixel. `lands` is where its own space lands on the screen.
   */
  function restsOnGrid(text: SVGTextElement, lands: DOMMatrix | null) {
    if (!lands) return false;
    const dpr = window.devicePixelRatio;
    const style = getComputedStyle(text);
    const k = lands.d * dpr;
    const y = text.y.baseVal.numberOfItems
      ? text.y.baseVal.getItem(0).value
      : 0;
    return (
      text.y.baseVal.numberOfItems <= 1 &&
      text.dy.baseVal.numberOfItems === 0 &&
      !text.querySelector("tspan[y], tspan[dy], textPath") &&
      /^(auto|alphabetic)$/.test(style.dominantBaseline) &&
      /^(auto|baseline)$/.test(style.alignmentBaseline) &&
      Math.abs(lands.b) < 1e-6 &&
      Math.abs(lands.c) < 1e-6 &&
      Math.round(k) >= 1 &&
      offWhole(k) < 2e-3 &&
      offWhole((lands.d * y + lands.f) * dpr) < ON_GRID
    );
  }

  /**
   * The angle that takes a block off the grid, given what is above it (`above`)
   * and what its own transform does (`own`), both in device pixels: the lean is
   * a turn between the two. 0 when the block leans enough as it is, null when
   * no sane angle would do.
   */
  function angleFor(above: Lin, own: Lin): number | null {
    // y from x of `above · turn(θ) · own` is p·sin θ + q·cos θ.
    const p = above[3] * own[0] - above[1] * own[1];
    const q = above[1] * own[0] + above[3] * own[1];
    if (Math.abs(q) >= LEAN) return 0;
    if (Math.abs(p) < 1e-9) return null;
    // Along the turn the scene already has, so the two never cancel out.
    const sine = ((q < 0 ? -LEAN : LEAN) - q) / p;
    if (Math.abs(sine) > Math.sin((STEEPEST * Math.PI) / 180)) return null;
    return (Math.asin(sine) * 180) / Math.PI;
  }

  function lean() {
    for (const el of leant) {
      el.style.removeProperty("rotate");
      if (el instanceof SVGElement) el.style.removeProperty("translate");
    }
    leant = [];
    const zones = document.querySelectorAll<HTMLElement | SVGElement>(MARKED);
    if (zones.length === 0) return;
    // Each block of text under a mark, and whether any transform above it moves.
    const blocks = new Map<Block, boolean>();
    // The texts a whole drawing leans for.
    const standsFor = new Map<SVGSVGElement, SVGTextElement[]>();
    for (const zone of zones) {
      const moving = zone.style.transform.includes(MOVING.trim());
      const walker = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!/\S/.test(node.nodeValue ?? "")) continue;
        const block = blockOf(node);
        // A block that turns by a property of its own is left to the scene.
        if (!block || block.style.rotate) continue;
        blocks.set(block, moving || (blocks.get(block) ?? false));
        const text = node.parentElement?.closest("text");
        if (block instanceof SVGSVGElement && text instanceof SVGTextElement)
          standsFor.set(block, [...(standsFor.get(block) ?? []), text]);
      }
      watch(zone);
    }
    for (const block of blocks.keys()) watch(block);
    const dpr = window.devicePixelRatio;
    const scaled = (m: Lin): Lin => [
      m[0] * dpr,
      m[1] * dpr,
      m[2] * dpr,
      m[3] * dpr,
    ];
    // Outer blocks first: a block inside a leaning one takes only what it
    // still lacks, so leans never pile up. Everything is read before anything
    // is written; `given` stands in for the leans not yet on the page.
    const given = new Map<Element, number>();
    const { ownOf, linDown, carryDown } = reader(given);
    const writes: (() => void)[] = [];
    const ordered = [...blocks.keys()].sort((a, b) => depthOf(a) - depthOf(b));
    for (const el of ordered) {
      const moving = blocks.get(el) === true;
      if (el instanceof HTMLElement) {
        const above = linDown(el.parentElement);
        const mine = ownOf(el);
        if (!above || !mine) continue;
        if (!moving) {
          // Layout puts a baseline on a whole pixel wherever the box itself
          // sits, so text is on the grid when the transforms around it only
          // move it by whole pixels and show it one to one (or two, or three).
          const carry = carryDown(el);
          if (
            carry &&
            offWhole(carry.k * dpr) < 2e-3 &&
            offWhole(carry.dy * dpr) < ON_GRID
          )
            continue;
        }
        const angle = angleFor(scaled(above), mine.lin);
        if (!angle) continue;
        given.set(el, angle);
        writes.push(() => el.style.setProperty("rotate", `${angle}deg`));
        leant.push(el);
        continue;
      }
      if (el instanceof SVGSVGElement) {
        // A whole drawing: what it does itself is its own transform and the
        // scale of its viewBox, read off where it lands on the screen.
        const above = linDown(el.parentElement);
        const lands = el.getScreenCTM();
        const det = above ? above[0] * above[3] - above[1] * above[2] : 0;
        if (!above || !lands || Math.abs(det) < 1e-12) continue;
        if (
          !moving &&
          (standsFor.get(el) ?? []).every((text) =>
            restsOnGrid(text, text.getScreenCTM()),
          )
        )
          continue;
        const mine = times(
          [above[3] / det, -above[1] / det, -above[2] / det, above[0] / det],
          [lands.a, lands.b, lands.c, lands.d],
        );
        const angle = angleFor(scaled(above), mine);
        if (!angle) continue;
        given.set(el, angle);
        writes.push(() => el.style.setProperty("rotate", `${angle}deg`));
        leant.push(el);
        continue;
      }
      // Its drawing leans as a whole already.
      let drawing = el.ownerSVGElement;
      while (drawing?.ownerSVGElement) drawing = drawing.ownerSVGElement;
      if (drawing && given.has(drawing)) continue;
      // Text in an SVG is placed wherever it is told to, so it is on the grid
      // only when its baseline happens to land on a whole pixel.
      const frame = el.parentNode;
      if (!(frame instanceof SVGGraphicsElement) || el.style.translate)
        continue;
      const outer = frame.getScreenCTM();
      const whole = el.getScreenCTM();
      if (
        !outer ||
        !whole ||
        Math.abs(outer.a * outer.d - outer.b * outer.c) < 1e-12
      )
        continue;
      // What the text element itself does, in the space it is placed in.
      const mine = outer.inverse().multiply(whole);
      if (!moving && restsOnGrid(el, whole)) continue;
      const angle = angleFor(scaled([outer.a, outer.b, outer.c, outer.d]), [
        mine.a,
        mine.b,
        mine.c,
        mine.d,
      ]);
      if (!angle) continue;
      // An SVG element turns about the corner of its drawing. A move brings
      // the turn to the middle of the text instead.
      const box = el.getBBox();
      const [cx, cy] = [box.x + box.width / 2, box.y + box.height / 2];
      const [px, py] = [
        mine.a * cx + mine.c * cy + mine.e,
        mine.b * cx + mine.d * cy + mine.f,
      ];
      const [cos, sin] = [turned(angle)[0], turned(angle)[1]];
      const [tx, ty] = [px - (px * cos - py * sin), py - (px * sin + py * cos)];
      writes.push(() => {
        el.style.setProperty("rotate", `${angle}deg`);
        el.style.setProperty("translate", `${tx}px ${ty}px`);
      });
      leant.push(el);
    }
    for (const write of writes) write();
  }

  const useFrameEffect =
    typeof window === "undefined" ? useEffect : useLayoutEffect;

  function useGlide() {
    // No dependencies: the lean follows whatever this frame laid out.
    useFrameEffect(lean);
    return glide;
  }

  const glide = (moving: boolean) => (moving ? MOVING : AT_REST);

  return useGlide;
})();

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

// The subject falling into the floor and the hit: squash, camera shake,
// colour split, flash and dust. Frames on the 30 fps scene timeline, after
// `speed`. The ids are public: a saved `timing` prop refers to them.

type ImpactShakeElementId = "fall" | "hit";

interface ImpactShakeTimingProps {
  impact?: number;
}

const DEFAULT_IMPACT = 7;

// `hit` follows the fall and runs as long as the longest dust grain lives.
// Its beats: the colour split's length (`split`), the flash's peak
// (`flashPeak`) and its end (`flash`).
const impactShakeTimeline = defineTimeline<
  ImpactShakeElementId,
  ImpactShakeTimingProps
>(({ impact = DEFAULT_IMPACT }): TimelineElement<ImpactShakeElementId>[] => [
  {
    id: "fall",
    lane: "Subject",
    label: "fall",
    start: 0,
    length: impact,
  },
  {
    id: "hit",
    lane: "Subject",
    label: "hit",
    start: impact,
    length: 20,
    follows: "fall",
    beats: { split: 2, flashPeak: 0.5, flash: 2.5 },
  },
]);

type ImpactShakeColors = {
  background: string;
  foreground: string;
  splitA: string;
  splitB: string;
  dust: string;
};

type ImpactShakeProps = {
  /** The heavy subject. Defaults to a big white word. */
  children?: React.ReactNode;
  /** Word used when no children are passed. */
  text?: string;
  /** Shake, split and dust strength, 0 to 2. */
  intensity?: number;
  /** Frame (at 30fps) when the subject hits. */
  impact?: number;
  colors?: Partial<ImpactShakeColors>;
  /** Default word and flash color. Overrides `colors.foreground`. */
  foregroundColor?: string;
  /** Background color. Overrides `colors.background`. */
  backgroundColor?: string;
  seed?: number;
  speed?: number;
  /**
   * Moves, trims or stretches the fall and the hit, by the ids in
   * `./timeline`. Frames on the scene timeline, after `speed`.
   */
  timing?: Timing<ImpactShakeElementId>;
};

const impactShakeDefaults = {
  text: "LAUNCH",
  intensity: 1,
  impact: DEFAULT_IMPACT,
  colors: {
    background: "#111111",
    foreground: "#FFFFFF",
    splitA: "#FF2A2A",
    splitB: "#2A6BFF",
    dust: "#D9D9D9",
  } satisfies ImpactShakeColors,
  seed: 1,
  speed: 1,
};

const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const DUST = 36;

// Turns any content into a flat silhouette of one color, keeping its alpha.
function tintMatrix(hex: string) {
  const v = Number.parseInt(hex.replace("#", "").slice(0, 6), 16);
  const r = ((v >> 16) & 255) / 255;
  const g = ((v >> 8) & 255) / 255;
  const b = (v & 255) / 255;
  return `0 0 0 0 ${r} 0 0 0 0 ${g} 0 0 0 0 ${b} 0 0 0 1 0`;
}

function ImpactShakeBase(props: ImpactShakeProps) {
  const {
    children,
    text = impactShakeDefaults.text,
    intensity = impactShakeDefaults.intensity,
    colors: colorOverrides,
    foregroundColor,
    backgroundColor,
    seed = impactShakeDefaults.seed,
    speed = impactShakeDefaults.speed,
    timing,
  } = props;
  const tilt = useGlide();
  const frame = useSceneFrame();
  const { width, height, fps, durationInFrames } = useSceneConfig();
  const tl = useTimeline(
    impactShakeTimeline,
    props,
    durationInFrames * speed,
    timing,
  );
  const fallEl = tl.get("fall");
  const hit = tl.get("hit");
  const uid = `impact-shake-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const baseColors = { ...impactShakeDefaults.colors, ...colorOverrides };
  const colors = {
    ...baseColors,
    foreground: foregroundColor ?? baseColors.foreground,
    background: backgroundColor ?? baseColors.background,
  };
  const t = (frame * speed * 30) / fps;
  const k = Math.max(0, intensity);
  const unit = height / 720;
  const since = t - hit.start;

  const phase = random(`impact-shake-${seed}`) * Math.PI * 2;
  const motionAt = (tt: number) => {
    const sinceT = tt - hit.start;
    // Fall: pure acceleration into the hit, no easing out.
    const fall = interpolate(
      tt,
      [fallEl.start, fallEl.end],
      [-height * 0.85, 0],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.in(Easing.quad),
      },
    );
    const falling = sinceT < 0;
    const stretch = falling
      ? interpolate(tt, [fallEl.start, fallEl.end], [1, 1.18], {
          extrapolateRight: "clamp",
        })
      : 1;
    const squash = falling
      ? 0
      : 1 -
        spring({
          frame: sinceT,
          fps: 30,
          config: { damping: 9, stiffness: 260 },
        });
    const sx = falling
      ? 1 / Math.sqrt(stretch)
      : 1 + 0.16 * squash * Math.min(1, k);
    const sy = falling ? stretch : 1 - 0.2 * squash * Math.min(1, k);

    // Damped camera shake with incommensurate frequencies so it never looks looped.
    const decay = sinceT >= 0 ? Math.exp(-sinceT / 3.2) : 0;
    const shakeX = decay * Math.sin(sinceT * 2.9 + phase) * 26 * unit * k;
    const shakeY = decay * Math.cos(sinceT * 3.7 + phase) * 34 * unit * k;
    const shakeR = decay * Math.sin(sinceT * 2.3 + phase * 2) * 1.6 * k;
    return { fall, sx, sy, decay, shakeX, shakeY, shakeR };
  };
  const { fall, sx, sy, decay, shakeX, shakeY, shakeR } = motionAt(t);
  // The squash spring and the shake ring out with no clean progress, so the
  // word counts as moving while its vertical travel, its height or the
  // camera's turn still shifts it between neighbouring frames.
  const step = 30 / fps;
  const shift = (a: number, b: number) => {
    const p = motionAt(a);
    const q = motionAt(b);
    return (
      Math.abs(p.fall - q.fall) +
      Math.abs(p.sy - q.sy) * height +
      Math.abs(p.shakeY - q.shakeY) +
      Math.abs(p.decay - q.decay) * 0.04 * k * height +
      Math.abs(p.shakeR - q.shakeR) * width * 0.01
    );
  };
  const moving =
    shift(t + speed * step, t) > 1e-3 || shift(t, t - speed * step) > 1e-3;
  const glide = tilt(moving);

  const split =
    since >= 0 && since < hit.beat("split")
      ? (1 - since / hit.beat("split")) * 18 * unit * k + 6 * unit
      : 0;
  const flash = interpolate(
    since,
    [0, hit.beat("flashPeak"), hit.beat("flash")],
    [0, 0.12, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );

  const floorY = height * 0.62;
  const dust = useMemo(
    () =>
      Array.from({ length: DUST }, (_, i) => {
        const key = `impact-shake-${seed}-dust-${i}`;
        const side = i % 2 === 0 ? -1 : 1;
        return {
          chip: i % 3 === 0,
          x0: (0.04 + random(`${key}-x`) * 0.24) * side,
          vx: side * (0.4 + random(`${key}-v`) * 1),
          vy: 0.3 + random(`${key}-u`) * 0.9,
          size: 0.5 + random(`${key}-s`) * 0.9,
          life: 11 + random(`${key}-l`) * 9,
        };
      }),
    [seed],
  );

  const subject = children ?? (
    <span
      style={{
        fontFamily: FONT,
        fontSize: height * 0.24,
        fontWeight: 900,
        letterSpacing: "-0.05em",
        lineHeight: 1,
        color: colors.foreground,
      }}
    >
      {text}
    </span>
  );

  const layer = (filter: string | undefined, dx: number, key: string) => (
    <AbsoluteFill
      key={key}
      style={{
        alignItems: "center",
        justifyContent: "center",
        filter,
        transform: `translate(${dx}px, ${fall}px) scale(${sx}, ${sy})${glide}`,
        transformOrigin: `50% ${(floorY / height) * 100}%`,
        mixBlendMode: filter ? "screen" : undefined,
      }}
    >
      {subject}
    </AbsoluteFill>
  );

  return (
    <AbsoluteFill
      style={{ backgroundColor: colors.background, overflow: "hidden" }}
    >
      <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
        <filter id={`${uid}-a`} colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values={tintMatrix(colors.splitA)} />
        </filter>
        <filter id={`${uid}-b`} colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values={tintMatrix(colors.splitB)} />
        </filter>
      </svg>
      <AbsoluteFill
        style={{
          transform: `translate(${shakeX}px, ${shakeY}px) rotate(${shakeR}deg) scale(${1 + decay * 0.04 * k})`,
        }}
      >
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          style={{ position: "absolute", inset: 0 }}
          aria-hidden
        >
          <filter
            id={`${uid}-puff`}
            x="-50%"
            y="-50%"
            width="200%"
            height="200%"
          >
            <feGaussianBlur stdDeviation={height * 0.007} />
          </filter>
          {since >= 0
            ? dust.map((p, i) => {
                const age = since;
                if (age > p.life) return null;
                const life = age / p.life;
                const spread = Math.max(0.4, k);
                if (p.chip) {
                  // Debris: ballistic arc, small and bright.
                  const x =
                    width / 2 + p.x0 * width + p.vx * age * 10 * unit * spread;
                  const y =
                    floorY - p.vy * age * 16 * unit + age * age * 1.6 * unit;
                  const size = p.size * 6 * unit;
                  return (
                    <rect
                      key={i}
                      x={x - size / 2}
                      y={y - size / 2}
                      width={size}
                      height={size}
                      fill={colors.dust}
                      opacity={(1 - life) * 0.9}
                      transform={`rotate(${age * 40 * p.vx} ${x} ${y})`}
                    />
                  );
                }
                // Puffs: burst outward against heavy drag, then hang and swell.
                const travel = 1 - Math.exp(-age / 3.5);
                const x =
                  width / 2 +
                  p.x0 * width +
                  p.vx * travel * width * 0.16 * spread;
                const y = floorY - p.vy * travel * height * 0.07;
                const r =
                  height * p.size * (0.015 + 0.05 * travel + 0.02 * life);
                return (
                  <circle
                    key={i}
                    cx={x}
                    cy={y}
                    r={r}
                    fill={colors.dust}
                    opacity={(1 - life) ** 1.4 * 0.38}
                    filter={`url(#${uid}-puff)`}
                  />
                );
              })
            : null}
        </svg>
        {split > 0 ? (
          <>
            {layer(`url(#${uid}-a)`, -split, "a")}
            {layer(`url(#${uid}-b)`, split, "b")}
          </>
        ) : null}
        {layer(undefined, 0, "main")}
      </AbsoluteFill>
      <AbsoluteFill
        style={{ backgroundColor: colors.foreground, opacity: flash * k }}
      />
    </AbsoluteFill>
  );
}

const elementSchema = {
  ...Interactive.baseSchema,
  text: {
    type: "text-content",
    default: "LAUNCH",
    description: "Text",
  },
  intensity: {
    type: "number",
    default: 1,
    min: 0,
    max: 2,
    step: 0.1,
    description: "Intensity",
    hiddenFromList: false,
  },
  impact: {
    type: "number",
    default: 7,
    min: 2,
    max: 30,
    step: 1,
    description: "Impact frame",
    hiddenFromList: false,
  },
  foregroundColor: {
    type: "color",
    default: "#FFFFFF",
    description: "Foreground",
  },
  backgroundColor: {
    type: "color",
    default: "#111111",
    description: "Background",
  },
  seed: {
    type: "number",
    default: 1,
    min: 1,
    max: 24,
    step: 1,
    description: "Seed",
    hiddenFromList: false,
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

const ELEMENT_PROP_KEYS = new Set(["text","intensity","impact","foregroundColor","backgroundColor","seed","speed"]);

const ELEMENT_PROP_DEFAULTS: Record<string, unknown> = {
  text: "LAUNCH",
  intensity: 1,
  impact: 7,
  foregroundColor: "#FFFFFF",
  backgroundColor: "#111111",
  seed: 1,
  speed: 1,
};

type ImpactShakeElementProps = InteractiveBaseProps &
  InteractiveTransformProps &
  ComponentProps<typeof ImpactShakeBase>;

const ImpactShakeInner = forwardRef<
  HTMLDivElement,
  ImpactShakeElementProps & { readonly controls: SequenceControls | undefined }
>(({ controls, name, style, children, ...rest }, ref) => {
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
      name={name ?? "<ImpactShake>"}
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
        <ImpactShakeBase
          {...(componentProps as unknown as ComponentProps<typeof ImpactShakeBase>)}
        >
          {children}
        </ImpactShakeBase>
      </div>
    </Sequence>
  );
});

export const ImpactShake = Interactive.withSchema({
  Component: ImpactShakeInner,
  componentName: "<ImpactShake>",
  componentIdentity: null,
  schema: elementSchema,
  supportsEffects: false,
});
