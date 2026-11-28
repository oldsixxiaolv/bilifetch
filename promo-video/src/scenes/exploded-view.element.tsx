import { AbsoluteFill, Easing, Interactive, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig, type InteractiveBaseProps, type InteractiveTransformProps, type InteractivitySchema, type SequenceControls } from "remotion";
import React, { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, type ComponentProps } from "react";

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

type ExplodedViewElementId =
  | `slab:${number}`
  | `label:${number}`
  | "close";

interface ExplodedViewTimingProps {
  layers?: number;
  labels?: string[];
}

const EXPLODED_LAYERS = 4;
const EXPLODED_LABELS = ["Interface", "Engine", "Storage", "Hardware"];

const OPEN = 3;
/** Frames between two slabs lifting off, top slab first. */
const SLAB_STAGGER = 1.5;
/** Frames the open spring takes to settle. */
const SLAB_OPEN = 20;
const LABEL_AT = 14;
const LABEL_STAGGER = 2.5;
/** Frames the leader line takes to draw. */
const LABEL_DRAW = 10;
const CLOSE = 38;

/** Slab count the stack draws, 2 to 6. */
function explodedLayerCount(layers: number) {
  return Math.round(Math.min(6, Math.max(2, layers)));
}

// The slabs lift apart top first, each label draws its leader line and
// slides in, then the stack snaps shut with a knock. Indices count from the
// top slab.
const explodedViewTimeline = defineTimeline<
  ExplodedViewElementId,
  ExplodedViewTimingProps
>(({ layers = EXPLODED_LAYERS, labels = EXPLODED_LABELS }) => {
  const n = explodedLayerCount(layers);
  const elements: TimelineElement<ExplodedViewElementId>[] = [];
  for (let fromTop = 0; fromTop < n; fromTop++) {
    elements.push({
      id: `slab:${fromTop}`,
      lane: "Slabs",
      label: `Slab ${fromTop + 1}`,
      start: OPEN + fromTop * SLAB_STAGGER,
      length: SLAB_OPEN,
      follows: fromTop > 0 ? `slab:${fromTop - 1}` : undefined,
    });
  }
  let last: ExplodedViewElementId | undefined;
  for (let fromTop = 0; fromTop < n; fromTop++) {
    const label = labels[fromTop];
    if (!label) continue;
    const id: ExplodedViewElementId = `label:${fromTop}`;
    elements.push({
      id,
      lane: "Labels",
      label,
      start: LABEL_AT + fromTop * LABEL_STAGGER,
      length: LABEL_DRAW,
      follows: last,
      // The text slides in 5 frames into the line and takes 8.
      beats: { show: 5, slide: 8 },
    });
    last = id;
  }
  elements.push({
    id: "close",
    lane: "Stack",
    label: "Close",
    start: CLOSE,
    length: 12,
    follows: last,
    // The labels fade out over the 5 frames before the close; the knock
    // starts 5 frames after it and peaks at 7.
    beats: { labelsOut: -5, knock: 5, peak: 7 },
  });
  return elements;
});

type ExplodedViewColors = {
  background: string;
  top: string;
  left: string;
  right: string;
  highlightTop: string;
  highlightLeft: string;
  highlightRight: string;
  line: string;
  label: string;
};

type ExplodedViewProps = {
  /** Number of slabs, 2 to 6. */
  layers?: number;
  /** One label per slab, top slab first. */
  labels?: string[];
  /** Index of the red slab, counted from the top. */
  highlight?: number;
  colors?: Partial<ExplodedViewColors>;
  /** Background color. Overrides `colors.background`. */
  backgroundColor?: string;
  /** Label text color. Overrides `colors.label`. */
  labelColor?: string;
  speed?: number;
  /**
   * Moves, trims or stretches the slabs opening, the labels and the close,
   * by the ids in `./timeline`. Frames on the scene timeline, after `speed`.
   */
  timing?: Timing<ExplodedViewElementId>;
};

const explodedViewDefaults = {
  layers: EXPLODED_LAYERS,
  labels: EXPLODED_LABELS,
  highlight: 1,
  colors: {
    background: "#111111",
    top: "#F4F4F4",
    left: "#A6A6A6",
    right: "#747474",
    highlightTop: "#E5322D",
    highlightLeft: "#B5231F",
    highlightRight: "#8A1A17",
    line: "#FFFFFF",
    label: "#FFFFFF",
  } satisfies ExplodedViewColors,
  speed: 1,
};

const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const COS30 = Math.cos(Math.PI / 6);
const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

function ExplodedViewBase(props: ExplodedViewProps) {
  const {
    layers = explodedViewDefaults.layers,
    labels = explodedViewDefaults.labels,
    highlight = explodedViewDefaults.highlight,
    colors: colorOverrides,
    backgroundColor,
    labelColor,
    speed = explodedViewDefaults.speed,
    timing,
  } = props;
  const glide = useGlide();
  const frame = useSceneFrame();
  const { width, height, fps, durationInFrames } = useSceneConfig();
  const tl = useTimeline(
    explodedViewTimeline,
    props,
    durationInFrames * speed,
    timing,
  );
  const closeEl = tl.get("close");
  const closeAt = closeEl.start;
  const baseColors = { ...explodedViewDefaults.colors, ...colorOverrides };
  const colors = {
    ...baseColors,
    background: backgroundColor ?? baseColors.background,
    label: labelColor ?? baseColors.label,
  };
  const n = explodedLayerCount(layers);
  const tAt = (f: number) => (f * speed * 30) / fps;
  const t = tAt(frame);

  const side = height * 0.36;
  const thick = height * 0.036;
  const gap = (height * 0.27) / (n - 1);
  const cx = width * 0.4;
  const cy = height * 0.5;

  const iso = (X: number, Y: number, Z: number) =>
    [(X - Y) * COS30, (X + Y) * 0.5 - Z] as const;
  const pts = (list: (readonly [number, number])[]) =>
    list.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");

  // The stack at time `tt`, so a label can tell motion from rest.
  const stack = (tt: number) => {
    const close = spring({
      frame: tt - closeAt,
      fps: 30,
      config: { damping: 26, stiffness: 320, mass: 0.8 },
    });
    // Top slab leaves first; bottom one barely waits.
    const spread = Array.from({ length: n }, (_, i) => {
      const fromTop = n - 1 - i;
      const open = spring({
        frame: tt - tl.get(`slab:${fromTop}`).start,
        fps: 30,
        config: { damping: 12, stiffness: 110 },
      });
      return Math.max(0, open * (1 - close));
    });
    const offsets: number[] = [];
    let z = 0;
    for (let i = 0; i < n; i++) {
      offsets.push(z);
      z += thick + (i < n - 1 ? gap * Math.max(spread[i + 1], 0) : 0);
    }
    const total = z;
    // The click: a short downward knock once the slabs meet again.
    const knock =
      interpolate(
        tt,
        [
          closeAt + closeEl.beat("knock"),
          closeAt + closeEl.beat("peak"),
          closeEl.end,
        ],
        [0, 1, 0],
        {
          ...clamp,
          easing: Easing.out(Easing.quad),
        },
      ) *
      height *
      0.008;
    return { offsets, baseY: cy + side * 0.02 + total / 2 + knock };
  };
  const { offsets, baseY } = stack(t);
  const prev = stack(tAt(frame - 1));
  const next = stack(tAt(frame + 1));
  const labelOut = interpolate(
    t,
    [closeAt + closeEl.beat("labelsOut"), closeAt],
    [1, 0],
    clamp,
  );
  const labelX = width * 0.66;
  const fontSize = height * 0.042;

  const slabs: React.ReactNode[] = [];
  const leaders: React.ReactNode[] = [];
  // The labels are SVG text placed by attributes, so the drawing carries the
  // mark, moving while any label rides its slab.
  let labelsMoving = false;
  for (let i = 0; i < n; i++) {
    const fromTop = n - 1 - i;
    const hot = fromTop === highlight;
    const z0 = offsets[i];
    const z1 = z0 + thick;
    const h = side / 2;
    const top = [
      iso(-h, -h, z1),
      iso(h, -h, z1),
      iso(h, h, z1),
      iso(-h, h, z1),
    ];
    const left = [iso(-h, h, z1), iso(h, h, z1), iso(h, h, z0), iso(-h, h, z0)];
    const right = [
      iso(h, -h, z1),
      iso(h, h, z1),
      iso(h, h, z0),
      iso(h, -h, z0),
    ];
    const inset = h * 0.78;
    const inner = [
      iso(-inset, -inset, z1),
      iso(inset, -inset, z1),
      iso(inset, inset, z1),
      iso(-inset, inset, z1),
    ];
    const ink = hot ? "#FFFFFF" : "#111111";
    slabs.push(
      <g key={i}>
        <polygon
          points={pts(left)}
          fill={hot ? colors.highlightLeft : colors.left}
        />
        <polygon
          points={pts(right)}
          fill={hot ? colors.highlightRight : colors.right}
        />
        <polygon
          points={pts(top)}
          fill={hot ? colors.highlightTop : colors.top}
        />
        <polygon
          points={pts(inner)}
          fill="none"
          stroke={ink}
          strokeOpacity={0.18}
          strokeWidth={height * 0.002}
        />
        {[-0.4, 0, 0.4].map((k) => {
          const a = iso(-inset * 0.7, k * inset, z1);
          const b = iso(inset * (fromTop % 2 ? 0.2 : 0.7), k * inset, z1);
          return (
            <line
              key={k}
              x1={a[0]}
              y1={a[1]}
              x2={b[0]}
              y2={b[1]}
              stroke={ink}
              strokeOpacity={0.22}
              strokeWidth={height * 0.006}
              strokeLinecap="round"
            />
          );
        })}
      </g>,
    );

    const label = labels[fromTop];
    if (!label) continue;
    const labelEl = tl.get(`label:${fromTop}`);
    const showAt = labelEl.start + labelEl.beat("show");
    const anchor = iso(h, -h, (z0 + z1) / 2);
    const draw = interpolate(t, [labelEl.start, labelEl.end], [0, 1], {
      ...clamp,
      easing: Easing.inOut(Easing.cubic),
    });
    const show =
      interpolate(t, [showAt, showAt + labelEl.beat("slide")], [0, 1], {
        ...clamp,
        easing: Easing.out(Easing.cubic),
      }) * labelOut;
    const ax = cx + anchor[0] + height * 0.012;
    const ay = baseY + anchor[1];
    // anchor[1] is -(z0 + z1) / 2, which only moves with the slab's offset
    const ayAt = (s: { offsets: number[]; baseY: number }) =>
      s.baseY - s.offsets[i] - thick / 2;
    const moving =
      Math.abs(ayAt(next) - ay) > 1e-3 || Math.abs(ay - ayAt(prev)) > 1e-3;
    // A label still hidden needs no lean, and the lean turns the slabs too.
    labelsMoving ||= moving && show > 0;
    const length = (labelX - ax) * draw * labelOut;
    leaders.push(
      <g key={`l${i}`}>
        <circle
          cx={ax}
          cy={ay}
          r={height * 0.006}
          fill={colors.line}
          opacity={Math.min(1, draw * 3) * labelOut}
        />
        <line
          x1={ax}
          y1={ay}
          x2={ax + length}
          y2={ay}
          stroke={colors.line}
          strokeOpacity={0.6}
          strokeWidth={Math.max(1, height * 0.0022)}
        />
        <g
          opacity={show}
          transform={`translate(${labelX + height * 0.02 + (1 - show) * height * 0.03} ${ay})`}
        >
          <text
            y={-fontSize * 0.62}
            fill={hot ? colors.highlightTop : colors.label}
            fillOpacity={hot ? 1 : 0.5}
            fontFamily={FONT}
            fontSize={fontSize * 0.5}
            fontWeight={600}
            letterSpacing="0.12em"
          >
            {`0${fromTop + 1}`}
          </text>
          <text
            y={fontSize * 0.42}
            fill={colors.label}
            fontFamily={FONT}
            fontSize={fontSize}
            fontWeight={700}
            letterSpacing="-0.02em"
          >
            {label}
          </text>
        </g>
      </g>,
    );
  }

  return (
    <AbsoluteFill
      style={{ backgroundColor: colors.background, overflow: "hidden" }}
    >
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        style={{
          position: "absolute",
          inset: 0,
          transform: glide(labelsMoving),
        }}
        aria-hidden
      >
        <ellipse
          cx={cx}
          cy={baseY + side * 0.5 + height * 0.035}
          rx={side * COS30 * 1.05}
          ry={side * 0.16}
          fill="#000000"
          opacity={0.5}
        />
        <g transform={`translate(${cx} ${baseY})`}>{slabs}</g>
        {leaders}
      </svg>
    </AbsoluteFill>
  );
}

const elementSchema = {
  ...Interactive.baseSchema,
  labels: {
    type: "text-content",
    default: "Interface, Engine, Storage, Hardware",
    description: "Labels (comma-separated)",
  },
  layers: {
    type: "number",
    default: 4,
    min: 2,
    max: 6,
    step: 1,
    description: "Slabs",
    hiddenFromList: false,
  },
  highlight: {
    type: "number",
    default: 1,
    min: 0,
    max: 5,
    step: 1,
    description: "Highlighted slab",
    hiddenFromList: false,
  },
  backgroundColor: {
    type: "color",
    default: "#111111",
    description: "Background",
  },
  labelColor: {
    type: "color",
    default: "#FFFFFF",
    description: "Labels",
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

const ELEMENT_PROP_KEYS = new Set(["labels","layers","highlight","backgroundColor","labelColor","speed"]);

const ELEMENT_PROP_DEFAULTS: Record<string, unknown> = {
  labels: "Interface, Engine, Storage, Hardware",
  layers: 4,
  highlight: 1,
  backgroundColor: "#111111",
  labelColor: "#FFFFFF",
  speed: 1,
};

type ExplodedViewElementProps = InteractiveBaseProps &
  InteractiveTransformProps &
  ComponentProps<typeof ExplodedViewBase>;

const ExplodedViewInner = forwardRef<
  HTMLDivElement,
  ExplodedViewElementProps & { readonly controls: SequenceControls | undefined }
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
      name={name ?? "<ExplodedView>"}
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
        <ExplodedViewBase
          {...(componentProps as unknown as ComponentProps<typeof ExplodedViewBase>)}
        />
      </div>
    </Sequence>
  );
});

export const ExplodedView = Interactive.withSchema({
  Component: ExplodedViewInner,
  componentName: "<ExplodedView>",
  componentIdentity: null,
  schema: elementSchema,
  supportsEffects: false,
});
