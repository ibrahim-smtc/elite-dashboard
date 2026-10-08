/**
 * A slow field of points behind the hero figure.
 *
 * The only three-dimensional thing on the sheet, and it is deliberately the
 * quietest: a lattice of fine points drifting at the speed of a minute hand,
 * in one ink colour at four percent, behind the one number everybody looks at
 * first. It is texture, not content - nothing in it encodes data, because a
 * 3D shape that looks like it means something while meaning nothing is worse
 * than no shape at all.
 *
 * Four things keep it from being a liability on a business dashboard:
 *
 *   It is imported dynamically. three.js is ~600KB and the bundle already
 *   carries a size warning; loading it with the page would make every visit
 *   pay for a decoration. It arrives after the dashboard is usable, or never.
 *
 *   It renders nothing under prefers-reduced-motion. Not paused - never
 *   mounted, so the library is not even fetched.
 *
 *   It stops when the tab is hidden. A rAF loop left running behind another
 *   window is a laptop fan and nothing else.
 *
 *   It fails silently. No WebGL, an old driver, a blocked context - the hero
 *   is a hero without it, and nobody sees an error where a backdrop should be.
 */

import React, { useEffect, useRef } from 'react';

/* Read from the stylesheet rather than hard-coded, so the field follows the
   theme the way everything else does - and recomputed on theme change, since
   the colour is baked into the material at build time. */
function inkColour() {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue('--ink').trim();
  return v || '#f0f1f3';
}

export default function HeroField() {
  const host = useRef(null);

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (reduced?.matches) return undefined;

    let alive = true;
    let cleanup = () => {};

    (async () => {
      let THREE;
      try {
        THREE = await import('three');
      } catch {
        return;                       // offline, blocked, or chunk missing
      }
      if (!alive || !host.current) return;

      const el = host.current;
      let renderer;
      try {
        renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
      } catch {
        return;                       // no WebGL; the hero is fine without it
      }

      const w = () => el.clientWidth || 1;
      const h = () => el.clientHeight || 1;

      // Capped at 2: a 3x display gains nothing visible here and costs four
      // times the pixels for a backdrop at four percent opacity.
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(w(), h(), false);
      renderer.domElement.style.cssText = 'width:100%;height:100%;display:block';
      el.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(46, w() / h(), 0.1, 100);
      camera.position.set(0, 0, 14);

      // A lattice rather than random noise. Random points read as dust or a
      // starfield; a grid gently displaced reads as a measured surface, which
      // is the register the rest of the sheet is in.
      const COLS = 46, ROWS = 14, GAP = 0.62;
      const count = COLS * ROWS;
      const pos = new Float32Array(count * 3);
      const base = new Float32Array(count);
      let i = 0;
      for (let x = 0; x < COLS; x++) {
        for (let y = 0; y < ROWS; y++) {
          pos[i * 3] = (x - COLS / 2) * GAP;
          pos[i * 3 + 1] = (y - ROWS / 2) * GAP;
          pos[i * 3 + 2] = 0;
          base[i] = (x + y) * 0.35;       // phase, so the wave travels
          i++;
        }
      }

      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));

      const mat = new THREE.PointsMaterial({
        color: new THREE.Color(inkColour()),
        size: 0.035,
        transparent: true,
        opacity: 0.4,                   // times the 0.04 on the wrapper
        depthWrite: false,
      });
      const points = new THREE.Points(geo, mat);
      scene.add(points);

      const onTheme = () => mat.color.set(inkColour());
      const themeWatch = new MutationObserver(onTheme);
      themeWatch.observe(document.documentElement,
                         { attributes: true, attributeFilter: ['data-theme'] });

      const resize = () => {
        camera.aspect = w() / h();
        camera.updateProjectionMatrix();
        renderer.setSize(w(), h(), false);
      };
      const ro = new ResizeObserver(resize);
      ro.observe(el);

      let frame = 0;
      const start = performance.now();
      const attr = geo.getAttribute('position');

      const tick = () => {
        frame = requestAnimationFrame(tick);
        // Seconds, not frame counts: the drift is then the same speed on a
        // 144Hz panel as on a 60Hz one.
        const t = (performance.now() - start) / 1000;
        for (let n = 0; n < count; n++) {
          attr.array[n * 3 + 2] = Math.sin(t * 0.25 + base[n]) * 0.9;
        }
        attr.needsUpdate = true;
        points.rotation.y = Math.sin(t * 0.05) * 0.12;
        renderer.render(scene, camera);
      };

      // Hidden tab, or scrolled away: stop entirely rather than render into
      // something nobody is looking at.
      const stop = () => { if (frame) { cancelAnimationFrame(frame); frame = 0; } };
      const go = () => { if (!frame && !document.hidden && onScreen) tick(); };

      let onScreen = true;
      const io = new IntersectionObserver(([e]) => {
        onScreen = e.isIntersecting;
        onScreen ? go() : stop();
      });
      io.observe(el);

      const onVis = () => (document.hidden ? stop() : go());
      document.addEventListener('visibilitychange', onVis);
      go();

      cleanup = () => {
        stop();
        document.removeEventListener('visibilitychange', onVis);
        io.disconnect();
        ro.disconnect();
        themeWatch.disconnect();
        geo.dispose();
        mat.dispose();
        renderer.dispose();
        if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
      };
    })();

    return () => { alive = false; cleanup(); };
  }, []);

  return (
    <div
      ref={host}
      aria-hidden="true"
      style={{
        position: 'absolute', inset: 0, zIndex: 0,
        opacity: 0.04, pointerEvents: 'none', overflow: 'hidden',
      }}
    />
  );
}
